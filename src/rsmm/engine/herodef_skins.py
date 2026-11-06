"""A hero's skin list inside its cooked herodef, and adding skins to it.

A herodef (``oCDtHeroDefinition``) is an object GRAPH (decoded 2026-11-06 on
Update 6, all 12 shipped heroes):

* ``sections[0]`` is the OBJECT TABLE: ``u32 n`` then ``n`` class indices
  (into the file's class table), one per sub-object;
* ``sections[1..n]`` are those sub-objects, in table order — object id ``k``
  is ``sections[k + 1]``: the talent rows, the story pages, the skins
  (``SkinProfileDataSettings``), their unlock conditions;
* the last section is the root, which lists its sub-objects BY ID: the skin
  list is ``u32 count`` then ``count`` u32 ids (Scarlet: ``9 | 35..43``).

A skin object is ``u32 class | 16-byte GUID | ... | title text ref | icon
(lstr "Ui", lstr png) | skin entity (lstr "EntitySettings", lstr path) | a
lock block whose condition list names unlock objects by id | description and
unlock-condition text refs``. Default carries an EMPTY condition list, which
is what makes it always available; the DLC skins name an
``AdditionalContentGameUnlockConditionSettings`` object holding the Steam DLC
app id, the earned ones a game-event or progression condition.

Adding a skin = append a copy of an unlocked skin object as the LAST
sub-object (id ``n``), add its class to the object table and its id to the
root's skin list. Appending at the end is the rule that matters: inserting a
sub-object mid-table renumbers every object after it while every reference to
them (the root's lists, each skin's condition ids) keeps the old number.
That is what ``skill_clone.clone_skill`` does, and its net-new talent crashed
the game twice in ``HeroDef_PostLoad`` with a desynchronised stream.

The engine side needs no hook: ``HeroDef_LoadSkinEntity`` loads skin N from a
growable table built from this list (count at herodef+0x900), and both skin
pages (Select_Hero_Book_Page, Hero_Meta_Progression) fill a Skin List Spawner
with one ``HeroSkin_Miniature`` per entry. A peer without the mod that is sent
a skin index it does not have falls back to skin 0 (the loader's own bounds
check), so co-op degrades to Default rather than failing.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from . import cooked

SKIN_CLASS = "SkinProfileDataSettings"
_TEXT_HEAD = b"\x04\x00\x00\x00Text"
_LOCK_OPEN = cooked.MARK_BEGIN + struct.pack("<I", 7)   # oCGameLockSettings block


class HerodefSkinError(ValueError):
    """The herodef is not in the shape this module reads; nothing was changed."""


def _lstr(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<I", len(b)) + b


@dataclass(frozen=True)
class TextRef:
    bank: str
    row: int
    key: str


@dataclass(frozen=True)
class Skin:
    obj_id: int
    guid: bytes
    title: TextRef | None
    icon: str
    entity: str
    conditions: tuple[int, ...]      # unlock-condition object ids; () = always available

    @property
    def unlocked(self) -> bool:
        return not self.conditions


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------

def _object_table(cf: cooked.CookedFile) -> list[int]:
    p = cf.sections[0].payload
    if len(p) < 4:
        raise HerodefSkinError("herodef has no object table")
    (n,) = struct.unpack_from("<I", p, 0)
    if len(p) != 4 + 4 * n:
        raise HerodefSkinError(f"object table says {n} objects but is {len(p)} bytes")
    if len(cf.sections) != n + 2:
        raise HerodefSkinError(
            f"object table lists {n} objects but the file has {len(cf.sections) - 2} "
            "sub-object sections — refusing to edit a graph I cannot account for")
    return list(struct.unpack_from(f"<{n}I", p, 4))


def _skin_class(cf: cooked.CookedFile) -> int:
    names = [c.name for c in cf.classes]
    if SKIN_CLASS not in names:
        raise HerodefSkinError(f"herodef has no {SKIN_CLASS} class")
    return names.index(SKIN_CLASS)


def _read_lstr(p: bytes, at: int) -> tuple[str, int]:
    (n,) = struct.unpack_from("<I", p, at)
    return p[at + 4:at + 4 + n].decode("utf-8", "replace"), at + 4 + n


def _text_refs(p: bytes) -> list[tuple[int, int, TextRef]]:
    """Every ``Text`` reference in a payload: (start, end, ref)."""
    out = []
    at = p.find(_TEXT_HEAD)
    while at != -1:
        bank, r = _read_lstr(p, at + len(_TEXT_HEAD))
        (row,) = struct.unpack_from("<I", p, r)
        key, end = _read_lstr(p, r + 4)
        out.append((at, end, TextRef(bank, row, key)))
        at = p.find(_TEXT_HEAD, end)
    return out


def _after(p: bytes, tag: str) -> tuple[int, int, str]:
    """The lstr that follows the first ``tag`` lstr: (start, end, value)."""
    t = _lstr(tag)
    at = p.find(t)
    if at == -1:
        raise HerodefSkinError(f"skin object has no {tag} reference")
    val, end = _read_lstr(p, at + len(t))
    return at + len(t), end, val


def _conditions(p: bytes) -> tuple[int, ...]:
    at = p.find(_LOCK_OPEN)
    if at == -1:
        raise HerodefSkinError("skin object has no lock block")
    (n,) = struct.unpack_from("<I", p, at + 8)
    if n > 64:
        raise HerodefSkinError(f"implausible unlock-condition count {n}")
    return tuple(struct.unpack_from(f"<{n}I", p, at + 12))


def _parse_skin(obj_id: int, p: bytes) -> Skin:
    refs = _text_refs(p)
    _s, _e, icon = _after(p, "Ui")
    _s, _e, entity = _after(p, "EntitySettings")
    return Skin(obj_id, p[4:20], refs[0][2] if refs else None, icon, entity, _conditions(p))


def _root_skin_list(root: bytes, ids: list[int]) -> int:
    """Offset of the root's ``u32 count | ids`` skin list. Unique or raise."""
    needle = struct.pack(f"<{len(ids) + 1}I", len(ids), *ids)
    at = root.find(needle)
    if at == -1 or root.find(needle, at + 1) != -1:
        raise HerodefSkinError(
            "the root's skin list was not found exactly once — refusing to guess")
    return at


def skins(blob: bytes) -> list[Skin]:
    """The hero's skins, in the order the book shows them (Default first)."""
    cf = cooked.parse(blob)
    table = _object_table(cf)
    sc = _skin_class(cf)
    ids = [k for k, c in enumerate(table) if c == sc]
    if not ids:
        raise HerodefSkinError("herodef has no skins")
    root = cf.sections[-1].payload
    # The book order IS the root's list; the object ids happen to be
    # contiguous in shipped data, but the list is what the engine reads.
    at = _root_skin_list(root, ids)
    (n,) = struct.unpack_from("<I", root, at)
    order = struct.unpack_from(f"<{n}I", root, at + 4)
    return [_parse_skin(k, cf.sections[k + 1].payload) for k in order]


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class NewSkin:
    guid: bytes                      # 16 bytes; the profile keys skins by it
    entity: str                      # Heroes\Hero_X\Hero_X_<Name>.entity.ot
    icon: str                        # BookMenu\Skins\<file>.png
    title: TextRef
    description: TextRef
    unlock_text: TextRef | None = None   # shown under a locked skin; ours never are


def _set_text(p: bytes, index: int, ref: TextRef) -> bytes:
    refs = _text_refs(p)
    if index >= len(refs):
        raise HerodefSkinError(f"skin object has no text reference #{index}")
    s, e, _old = refs[index]
    new = (_TEXT_HEAD + _lstr(ref.bank) + struct.pack("<I", ref.row) + _lstr(ref.key))
    return p[:s] + new + p[e:]


def _set_after(p: bytes, tag: str, value: str) -> bytes:
    s, e, _old = _after(p, tag)
    return p[:s] + _lstr(value) + p[e:]


def _skin_object(template: bytes, spec: NewSkin) -> bytes:
    if len(spec.guid) != 16:
        raise HerodefSkinError("a skin GUID is 16 bytes")
    p = template[:4] + spec.guid + template[20:]
    if _conditions(p):
        raise HerodefSkinError("the template skin is locked; build from an unlocked one")
    n_text = len(_text_refs(p))
    p = _set_text(p, 0, spec.title)
    if n_text > 1:
        p = _set_text(p, 1, spec.description)
    if n_text > 2:
        p = _set_text(p, 2, spec.unlock_text or spec.description)
    p = _set_after(p, "Ui", spec.icon)
    return _set_after(p, "EntitySettings", spec.entity)


def add_skins(blob: bytes, specs: list[NewSkin], *, template: int | None = None) -> bytes:
    """Append ``specs`` to the hero's skin list. Returns the new herodef.

    Each new skin is a copy of ``template`` (an object id; default: the first
    unlocked skin, i.e. Default) with its own GUID, texts, icon and entity.
    Fails closed on any shape it cannot account for, and re-reads its own
    output to prove the graph is consistent before returning it.
    """
    if not specs:
        return blob
    cf = cooked.parse(blob)
    table = _object_table(cf)
    sc = _skin_class(cf)
    have = skins(blob)
    known = {s.guid for s in have}
    for s in specs:
        if s.guid in known:
            raise HerodefSkinError(f"skin GUID {s.guid.hex()} is already in this herodef")
        known.add(s.guid)
    if template is None:
        free = next((s for s in have if s.unlocked), None)
        if free is None:
            raise HerodefSkinError("hero has no unlocked skin to build from")
        template = free.obj_id
    if not (0 <= template < len(table)) or table[template] != sc:
        raise HerodefSkinError(f"object {template} is not a skin")
    tpl = cf.sections[template + 1].payload

    root = cf.sections[-1].payload
    order = [s.obj_id for s in have]
    at = _root_skin_list(root, sorted(order))
    new_ids = []
    objects = []
    for spec in specs:
        new_ids.append(len(table) + len(new_ids))
        objects.append(cooked.Section(payload=_skin_object(tpl, spec)))

    # Append-only: the new objects are the last sub-objects, so no existing
    # id moves; the root is still the last section.
    full = table + [sc] * len(specs)
    cf.sections[0] = cooked.Section(payload=struct.pack(f"<{len(full) + 1}I", len(full), *full))
    old_list = struct.pack(f"<{len(order) + 1}I", len(order), *order)
    new_list = struct.pack(f"<{len(order) + len(new_ids) + 1}I",
                           len(order) + len(new_ids), *order, *new_ids)
    root = root[:at] + new_list + root[at + len(old_list):]
    cf.sections = cf.sections[:-1] + objects + [cooked.Section(payload=root)]
    out = cooked.emit(cf)

    # Prove it: the graph reads back with every new skin at the end, in order.
    back = skins(out)
    if [s.obj_id for s in back] != order + new_ids or \
            [s.entity for s in back[len(order):]] != [s.entity for s in specs]:
        raise HerodefSkinError("the edited herodef does not read back as written")
    return out
