"""A shipped hero's button, lent whole to a hero written from scratch.

Every shipped button is a working state machine the game already plays:
Scarlet's wolf bite (rush, then bite once an enemy is in reach, intangible
throughout), Geppetto's combo, Kintaro's held charge, Romeo's dash attack. A
hero written from scratch used to get each such behaviour only once the SDK
had re-written it by hand (``hero_ability``'s ``combo``, ``strike``). Here a
button names one (``template = "Red: Wolf Primary"``) and gets the real thing:

1. **Copy.** The button's entry part (what the donor's controller starts) and
   everything it reaches -- through links AND through its parts' owned
   sub-objects, so an animatic's timeline events count -- copied into the hero
   under the donor's own names and groups. The walk stops at the donor's own
   systems (``BOUNDARY``: its talents, HUD, body, controllers), which are not
   the button's.
2. **Re-point.** A link the copy keeps to something it did not copy is made to
   resolve in the new hero, as shipped files write such links:

   * the donor's controller of this button -> the hero's slot, by the SHARED
     BASE's GUID (17 of 17 shipped combos; an override's own GUID resolves to
     nothing, and a combo linked that way restarted at every press);
   * any other override of a shared base part -> the base part's GUID;
   * Hero_Alt_Form_Common's parts (a two-form hero's) -> the plain
     Character_Common / Hero_Common part of the same role (``ALT_FORM``);
   * a part another button of the SAME donor already lent -> that copy.

3. **Cut.** Whatever is still the donor's own (a talent's state, its combo
   points, its FX file's effects) is cut the way the game reads an absent link:
   a number slot falls back to its own number (a talent bonus read as 0), a
   list loses the entry, a timeline event moves past the clip's end and fires
   the hero's empty kit event, a plain link is emptied.
4. **Check.** No link of the copy may name a part the new hero cannot reach
   (its own, Hero_Common's or Character_Common's): the build fails instead.

Knobs (``Template``): ``clips`` swaps animations by name, ``values`` sets any
copied number part (damage multipliers, ranges, durations, by the part's
name), and the hero's ``frame.edits`` can edit any copied part afterwards.
``catalog`` lists every shipped button with its clips and numbers.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

from . import entity_fields as EF
from . import entity_graph as EG
from .entity_graph_edit import _B, _E, EntityEditError, EntityFile, _lstr, _mint

#: Groups a button's walk never enters: the donor's own systems. A talent
#: ("Skill ...") that changes the button belongs to the donor's card set; its
#: HUD, body, movement and controllers are the hero's own.
BOUNDARY = re.compile(r"^(Skill( |s$)|Hero Controller$|Life Bar|Base$|Bhv |Move$|Physic|"
                      r"Preview|Narrative|Weapons?$|Ultimate Upgrades?|Camera|Ui$|UI$)")
#: A two-form hero's parts -> the one-form part of the same role (base, name).
ALT_FORM = {
    "Main Anim Alt Form Player": ("Character_Common", "Main Anim Player"),
    "Character Alt Form Mesh": ("Character_Common", "Character Mesh"),
    "Physic Alt Form Layer": ("Character_Common", "Physic Layer"),
}
_CONTROLLER = "oCDtEntityCpntAbilityControllerSettings"
_ANIMATIC = "oCEntityCpntAnimaticSettings"
_VALUE = "oCEntityCpntValueSettings"
#: The donor controller's switches a lent button keeps (its kind of input:
#: held repeats, interruptible, stops movement ...); text, icons and links stay
#: the hero's.
CONTROLLER_SWITCHES = ("value_3", "value_5", "value_6", "value_7", "value_8", "value_9",
                       "value_10", "value_11", "value_12", "value_14", "value_16", "value_17",
                       "value_21", "value_22")
#: Where a hero's controllers come from: shipped heroes, by entity folder.
_HEROES_DIR = "EntitySettings/Heroes/"


class TemplateError(ValueError):
    pass


@dataclass
class Template:
    """``template = "<Hero>: <button>"`` plus its knobs, from a manifest."""
    hero: str                     # the donor's folder stem: "Red" (Hero_Red)
    button: str                   # its controller, short: "Wolf Primary" / "Alt Primary"
    clips: dict[str, str] = field(default_factory=dict)    # old clip (name or path) -> new
    values: dict[str, object] = field(default_factory=dict)  # copied Value part -> number

    @classmethod
    def parse(cls, spec: str, raw: dict) -> Template:
        if not isinstance(spec, str) or spec.count(":") != 1:
            raise TemplateError(f"template is \"<Hero>: <button>\" (rsmm templates lists them), "
                                f"not {spec!r}")
        hero, button = (x.strip() for x in spec.split(":"))
        clips, values = raw.get("clips") or {}, raw.get("values") or {}
        if not isinstance(clips, dict) or not all(isinstance(v, str) for v in clips.values()):
            raise TemplateError("clips is { \"<the template's clip>\" = \"<new clip>\" }")
        if not isinstance(values, dict) or not all(
                isinstance(v, (int, float, bool)) for v in values.values()):
            raise TemplateError("values is { \"<a part of the template>\" = <number> }")
        return cls(hero.removeprefix("Hero_"), button, dict(clips), dict(values))


# ---- reading a donor -------------------------------------------------------------

def donor_file(read, hero: str) -> EntityFile:
    stem = f"Hero_{hero}"
    raw = read(f"Heroes\\{stem}\\{stem}.entity.ot")
    if raw is None:
        raise TemplateError(f"template: no hero {hero!r} in the game files")
    return EntityFile(raw, stem)


def controllers(d: EntityFile) -> dict[str, EG.Component]:
    """The donor's buttons: ``{short name: controller}`` for every controller
    that starts something. Short names: the controller's name without
    "Ability Controller" / "Controller" ("Alt Primary", "Basic Attack"), and
    the group of what it starts ("Wolf Primary" for "Ability Wolf Primary")."""
    g = d.graph()
    idx = g.by_guid()
    out: dict[str, EG.Component] = {}
    for c in g.components:
        if c.cls != _CONTROLLER:
            continue
        entry = _entry(c, idx)
        if entry is None:
            continue
        short = re.sub(r"\s+", " ", re.sub(r"\s*(Ability )?Controller\b", "", c.name)).strip()
        out.setdefault(short, c)
        grp = entry.group.removeprefix("Ability ").strip()
        if grp and grp not in out:
            out[grp] = c
    return out


def _entry(ctl: EG.Component, idx: dict) -> EG.Component | None:
    f = next((x for x in EF.fields(ctl) if x.name == "ref_2"), None)
    if f is None:
        return None
    r = next((r for r in ctl.refs if r.path in f.text or f.text.endswith(r.path)), None)
    if r is None:
        return next((idx[r.guid] for r in ctl.refs if r.guid in idx
                     and idx[r.guid].cls != _CONTROLLER), None)
    return idx.get(r.guid)


@dataclass
class _Pick:
    obj: int          # object id
    a: int            # picker span in that object's payload
    b: int
    guid: bytes
    path: str


def _picker_head(ef: EntityFile) -> bytes:
    return _B + struct.pack("<I", [x.name for x in ef.cf.classes].index("oCEntityCpntPicker"))


def _scan(ef: EntityFile, obj: int, head: bytes, skip_before: int = 0) -> list[_Pick]:
    p = bytes(ef.objects[obj])
    out, i = [], p.find(head)
    while i >= 0:
        n = struct.unpack_from("<I", p, i + 24)[0]
        end = i + 28 + n + 4
        if i >= skip_before and p[i + 8:i + 24] != bytes(16):
            out.append(_Pick(obj, i, end, p[i + 8:i + 24],
                             p[i + 28:i + 28 + n].decode("latin-1")))
        i = p.find(head, end)
    return out


def _body_at(ef: EntityFile, c: EG.Component) -> int:
    return len(ef.objects[c.index - 1]) - len(c.body)


def _children(ef: EntityFile) -> dict[int, list[int]]:
    """``{object: sub-objects it may own}``, read once: an ambiguous sub-object
    counts under every candidate owner (a walk may over-read, never miss)."""
    owned, ambiguous = ef.pointers()
    kids: dict[int, list[int]] = {}
    for x, ptr in owned.items():
        kids.setdefault(ptr.owner, []).append(x)
    for x, cands in ambiguous.items():
        for ptr in cands:
            kids.setdefault(ptr.owner, []).append(x)
    return kids


def deep_picks(ef: EntityFile, c: EG.Component,
               kids: dict[int, list[int]] | None = None) -> list[_Pick]:
    """Every link component ``c`` holds: in its body and in every sub-object it
    owns (an animatic's timeline events, a selector's entries)."""
    head = _picker_head(ef)
    kids = _children(ef) if kids is None else kids
    picks = _scan(ef, c.index - 1, head, _body_at(ef, c))
    seen, todo = {c.index - 1}, list(kids.get(c.index - 1, []))
    while todo:
        s = todo.pop()
        if s in seen:
            continue
        seen.add(s)
        picks += _scan(ef, s, head)
        todo += kids.get(s, [])
    return picks


class Family:
    """A donor hero's entity files, loaded as the walk reaches them: its main
    file and the files of its own family it links (``Hero_Red_FX`` holds the
    effects Scarlet's buttons play). Only files named ``Hero_<H>...`` in the
    hero's folder count: anything else is a shared base or another entity."""

    def __init__(self, read, hero: str):
        self.read, self.hero = read, hero
        self.files: dict[str, EntityFile] = {}
        self.kids: dict[str, dict[int, list[int]]] = {}
        self.idx: dict[bytes, tuple[str, EG.Component]] = {}
        self.main = self.load(f"Hero_{hero}")

    def load(self, scope: str) -> EntityFile | None:
        if scope in self.files:
            return self.files[scope]
        if not scope.startswith(f"Hero_{self.hero}"):
            return None
        raw = self.read(f"Heroes\\Hero_{self.hero}\\{scope}.entity.ot")
        if raw is None:
            return None
        f = EntityFile(raw, scope)
        self.files[scope] = f
        self.kids[scope] = _children(f)
        for c in f.graph().components:
            self.idx.setdefault(c.guid, (scope, c))
        return f

    def find(self, guid: bytes, path: str) -> tuple[str, EG.Component] | None:
        hit = self.idx.get(guid)
        if hit is None:
            scope = path.split("] ", 1)[-1].split("\\", 1)[0]
            if self.load(scope) is not None:
                hit = self.idx.get(guid)
        return hit


def walk(fam: Family, entry: EG.Component) -> list[tuple[str, EG.Component]]:
    """The button's parts, ``(file scope, part)``: ``entry`` and what it
    reaches across the donor's family, stopping at BOUNDARY groups,
    controllers and overrides of a parent's part (those are re-pointed at the
    parent's part, never copied: a copied override would replace the shared
    part for the whole hero)."""
    main = fam.main.name if hasattr(fam.main, "name") else f"Hero_{fam.hero}"
    seen = {entry.guid}
    todo, out = [(main, entry)], [(main, entry)]
    while todo:
        scope, c = todo.pop()
        for pk in deep_picks(fam.files[scope], c, fam.kids[scope]):
            if pk.guid in seen:
                continue
            hit = fam.find(pk.guid, pk.path)
            if hit is None:
                continue
            seen.add(pk.guid)
            t = hit[1]
            if t.cls == _CONTROLLER or t.override is not None or BOUNDARY.match(t.group):
                continue
            out.append(hit)
            todo.append(hit)
    return out


# ---- what the new hero can reach -----------------------------------------------

@dataclass
class _Bases:
    hc: EntityFile
    cc: EntityFile
    reach: set[bytes]                             # every GUID the hero inherits
    by_name: dict[tuple[str, str], EG.Component]  # (scope, name) -> part

    @classmethod
    def load(cls, read, hc: EntityFile) -> _Bases:
        raw = read("Character_Common\\Character_Common.entity.ot")
        if raw is None:
            raise TemplateError("Character_Common is not readable")
        cc = EntityFile(raw, "Character_Common")
        reach, by_name = set(), {}
        for scope, f in (("Hero_Common", hc), ("Character_Common", cc)):
            for c in f.graph().components:
                reach.add(c.guid)
                by_name.setdefault((scope, c.name), c)
        return cls(hc, cc, reach, by_name)


def _kind(path: str) -> str:
    return path[:path.index("]") + 1] if path.startswith("[") and "]" in path else "[State]"


# ---- lending --------------------------------------------------------------------

@dataclass
class Lent:
    entry: str                    # the copied part the hero's controller starts
    parts: list[str]              # every copied part's name
    cut: list[str]                # links cut, "part -> what it named"
    donor_ctl: str                # the donor's controller


def lend(ef: EntityFile, hc: EntityFile, read, tpl: Template, *, slot_ctl: str,
         seed: str, sink: str) -> Lent:
    """Copy ``tpl``'s button into ``ef`` and start it from the hero's
    controller ``slot_ctl`` (filled by the caller). ``sink`` is the hero's
    empty event state (``hero_frame.KIT_EVENT``): what a cut timeline event
    fires. Raises TemplateError when anything copied cannot resolve."""
    fam = Family(read, tpl.hero)
    if fam.main is None:
        raise TemplateError(f"template: no hero {tpl.hero!r} in the game files")
    d = fam.main
    ctls = controllers(d)
    if tpl.button not in ctls:
        raise TemplateError(f"template {tpl.hero}: no button {tpl.button!r}; it has "
                            f"{', '.join(sorted(ctls))}")
    dctl = ctls[tpl.button]
    entry = _entry(dctl, d.graph().by_guid())
    parts = walk(fam, entry)
    bases = _Bases.load(read, hc)
    tseed = f"{seed}:template:{tpl.hero}"
    mine = {c.guid for c in ef.graph().components}
    # parts another button of the same donor already lent: reused, not copied
    fresh = [(s_, c) for s_, c in parts if _mint(tseed, c.guid) not in mine]
    taken = {c.name for c in ef.graph().components}
    n_before = len(ef.objects)
    renamed: dict[bytes, str] = {}
    for scope_ in dict.fromkeys(s_ for s_, _ in fresh):
        batch = [c for s_, c in fresh if s_ == scope_]
        rename = {}
        for c in batch:
            if c.name in taken or c.name in rename:
                rename[c.name] = f"{c.name} ({scope_.removeprefix('Hero_')})"
            taken.add(rename.get(c.name, c.name))
        for c in batch:
            renamed[c.guid] = rename.get(c.name, c.name)
        try:
            ef.clone([c.path for c in batch], rename=rename, seed=tseed,
                     source=fam.files[scope_])
        except EntityEditError as e:
            raise TemplateError(f"template {tpl.hero}: {tpl.button}: {e}") from e
    comps = {c.guid: c for c in ef.graph().components}
    own_now = set(comps)
    new_name = {c.guid: comps[_mint(tseed, c.guid)].name for _, c in parts}
    copies = {_mint(tseed, c.guid) for _, c in parts}
    scope = ef._scope()
    cut: list[str] = []
    head = _picker_head(ef)

    def resolve(guid: bytes, path: str) -> tuple[bytes, str] | None:
        """Where a link the copy holds should point in the new hero, or None."""
        if guid in copies or guid in bases.reach or guid in own_now:
            return guid, path
        minted = _mint(tseed, guid)
        if minted in comps:
            t = comps[minted]
            return minted, f"{_kind(path)} {scope}\\{t.path if t.group else t.name}"
        hit = fam.find(guid, path)
        if hit is not None:
            t = hit[1]
            if t.cls == _CONTROLLER:
                base = _base_controller(hc, slot_ctl if t.guid == dctl.guid else t.name)
                if base is not None:
                    return base.guid, f"{_kind(path)} {scope}\\Hero Controller\\{base.name}"
                return None
            if t.override is not None and t.override.guid in bases.reach:
                return t.override.guid, f"{_kind(path)} {scope}\\{t.path}"
            if t.override is not None:
                return _alt(t.name, path, bases)
            return None
        return _alt(path.rsplit("\\", 1)[-1], path, bases)

    # Re-point, then cut. Every copied object was appended by the clones
    # (ids from n_before), so only those are visited; an edit moves later
    # spans in its own object only, so each object is re-read after each edit.
    by_obj = {c.index - 1: c for c in ef.graph().components}
    blocs = _blocs(ef, [c for o, c in by_obj.items() if o >= n_before and c.cls == _ANIMATIC])
    owner_comp = _owners(ef, n_before, by_obj)
    for obj in range(n_before, len(ef.objects)):
        c = owner_comp.get(obj)
        if c is None:
            continue
        skip = _body_at(ef, c) if obj == c.index - 1 else 0
        todo = None
        for _ in range(10000):
            todo = None
            for pk in _scan(ef, obj, head, skip):
                where = resolve(pk.guid, pk.path)
                if where is None or where[0] != pk.guid or where[1] != pk.path:
                    todo = (pk, where)
                    break
            if todo is None:
                break
            pk, where = todo
            if where is not None:
                ef.objects[obj][pk.a:pk.b] = head + where[0] + _lstr(where[1]) + _E
            else:
                _cut(ef, c, pk, sink, obj in blocs)
                cut.append(f"{c.name} -> {pk.path}")
                if obj == c.index - 1:          # a removed list entry re-shapes the body
                    c = ef.component(c.name)
                    owner_comp[obj] = c
        else:  # pragma: no cover
            raise TemplateError(f"template {tpl.hero}: {tpl.button}: links never settled: "
                                f"{c.name}: {todo[0].path} -> {todo[1]}")
    _drop_empty_combo_steps(ef, copies, head)
    left = unresolved(ef, hc, read, only=copies, bases=bases)
    if left:
        raise TemplateError(f"template {tpl.hero}: {tpl.button}: still links "
                            f"{len(left)} part(s) the hero cannot reach: {left[:3]}")
    names = [new_name[c.guid] for _, c in parts]
    _knobs(ef, tpl, names)
    _switches(ef, d, dctl, slot_ctl)
    return Lent(new_name[entry.guid], names, cut, dctl.name)


def _drop_empty_combo_steps(ef: EntityFile, copies: set[bytes], head: bytes) -> None:
    """A combo step all of whose links were cut (a talent's extra step, Romeo's
    Kick) leaves the combo: its id leaves the step list, and its object (ids
    cannot shift) becomes a copy of a kept step, owned by nothing."""
    for c in ef.graph().components:
        if c.guid not in copies or c.cls != "oCDtEntityCpntAttackComboSettings":
            continue
        f = next((x for x in EF.fields(c) if x.name == "bytes_4"), None)
        if f is None:
            continue
        n = struct.unpack_from("<I", c.body, f.offset)[0]
        ids = list(struct.unpack_from(f"<{n}I", c.body, f.offset + 4))
        keep = [i for i in ids if _scan(ef, i, head)]
        if len(keep) == len(ids) or not keep:
            continue
        p = ef.objects[c.index - 1]
        at = _body_at(ef, c) + f.offset
        p[at:at + 4 + 4 * n] = struct.pack(f"<I{len(keep)}I", len(keep), *keep)
        for i in ids:
            if i not in keep:
                ef.objects[i][:] = bytes(ef.objects[keep[-1]])


def _base_controller(hc: EntityFile, name: str) -> EG.Component | None:
    try:
        return hc.component(name)
    except EntityEditError:
        return None


def _alt(name: str, path: str, bases: _Bases) -> tuple[bytes, str] | None:
    if name in ALT_FORM:
        scope, part = ALT_FORM[name]
        t = bases.by_name.get((scope, part))
        if t is not None:
            return t.guid, f"{_kind(path)} {scope}\\{t.path}"
    if "Hero_Alt_Form_Common\\" not in path:
        return None
    plain = name.replace(" Alt Form", "").replace("Alt ", "")
    for want in dict.fromkeys((plain, name)):
        for scope in ("Hero_Common", "Character_Common"):
            t = bases.by_name.get((scope, want))
            if t is not None:
                return t.guid, f"{_kind(path)} {scope}\\{t.path}"
    return None


def _cut(ef: EntityFile, c: EG.Component, pk: _Pick, sink: str, bloc: bool) -> None:
    buf = ef.objects[pk.obj]
    from . import cooked
    if bytes(buf[pk.a - 2:pk.a]) == b"\x01\x00" \
            and bytes(buf[pk.b + 4:pk.b + 8]) == cooked.MARK_BEGIN:
        # a number slot reading a part: back to its own number (the slot is
        # `01 00 <picker> <accessor> <number>` reading, `00 <number>` holding)
        buf[pk.a - 2:pk.b + 4] = b"\x00"
        return
    if pk.obj == c.index - 1:
        at = _body_at(ef, c)
        for f in EF.fields(c):
            if f.kind != "ref[]":
                continue
            # item offsets are relative to the body, as remove_ref reads them
            # (adding the field's offset too matched an entry of ANOTHER list:
            # each cut deleted a wrong entry and re-cut until Scarlet's bite
            # state had no `activates` left, its clip never played and the
            # button never ended; Blood Wolf playtest 2026-11-14)
            for i, e in enumerate(f.items):
                if e.offset <= pk.a - at < e.offset + e.size:
                    ef.remove_ref(c.name, f.name, i)
                    return
    if bloc:
        # a timeline event of an animatic: it never fires, and names the
        # hero's empty event instead of a part it does not have
        struct.pack_into("<f", buf, 4, 1.0e4)
        buf[pk.a:pk.b] = ef._picker(sink)
        return
    buf[pk.a:pk.b] = ef._picker(None)


def _blocs(ef: EntityFile, animatics: list[EG.Component]) -> set[int]:
    """The timeline events (``oCCinematic`` bloc ids) of these animatics."""
    names = [x.name for x in ef.cf.classes]
    if "oCCinematic" not in names:
        return set()
    tag = _B + struct.pack("<I", names.index("oCCinematic"))
    out: set[int] = set()
    kids = _children(ef)
    for c in animatics:
        for o in [c.index - 1, *kids.get(c.index - 1, [])]:
            p = bytes(ef.objects[o])
            pos = p.find(tag)
            if pos >= 0:
                n = struct.unpack_from("<I", p, pos + 8)[0]
                out.update(struct.unpack_from(f"<{n}I", p, pos + 12))
    return out


def _owners(ef: EntityFile, n0: int, by_obj: dict[int, EG.Component]) -> dict[int, EG.Component]:
    """Each object from ``n0`` on -> the copied component it is or belongs to."""
    kids = _children(ef)
    out: dict[int, EG.Component] = {}
    for o, c in by_obj.items():
        if o < n0:
            continue
        out[o] = c
        todo = list(kids.get(o, []))
        while todo:
            x = todo.pop()
            if x >= n0 and x not in out:
                out[x] = c
                todo += kids.get(x, [])
    return out


def unresolved(ef: EntityFile, hc: EntityFile, read, *, only: set[bytes] | None = None,
               bases: _Bases | None = None) -> list[str]:
    """Links of ``ef``'s parts (``only``: those GUIDs) that name a part the hero
    can reach neither in itself nor in its shared bases."""
    bases = bases or _Bases.load(read, hc)
    g = ef.graph()
    own = {c.guid for c in g.components}
    kids = _children(ef)
    out = []
    for c in g.components:
        if only is not None and c.guid not in only:
            continue
        for pk in deep_picks(ef, c, kids):
            if pk.guid not in own and pk.guid not in bases.reach:
                out.append(f"{c.name} -> {pk.path}")
    return out


def _knobs(ef: EntityFile, tpl: Template, parts: list[str]) -> None:
    from . import hero_frame as HF
    have = set(parts)
    for part, v in tpl.values.items():
        if part not in have:
            raise TemplateError(f"template {tpl.hero}: {tpl.button}: values: no part {part!r} "
                                "(rsmm templates lists its numbers)")
        c = ef.component(part)
        if c.cls != _VALUE:
            raise TemplateError(f"template values: {part!r} is a {c.cls}, not a number")
        try:
            ef.set_value(part, "value", v)
        except EntityEditError as e:
            raise TemplateError(f"template values: {part!r}: {e}") from e
    if not tpl.clips:
        return
    used = set()
    for part in parts:
        c = ef.component(part)
        if c.cls != _ANIMATIC:
            continue
        for old, new in tpl.clips.items():
            for m in re.finditer(rb"Characters\\[ -~]*?\.fbx", c.body):
                clip = m.group(0).decode()
                if clip == old or clip.rsplit("\\", 1)[-1] in (old, old + ".fbx"):
                    HF.replace_in_slot(ef, part, clip, new)
                    length = HF.clip_length(new)
                    if length:
                        HF._set_duration(ef, part, length)
                    used.add(old)
                    break
            c = ef.component(part)
    missing = set(tpl.clips) - used
    if missing:
        raise TemplateError(f"template {tpl.hero}: {tpl.button}: clips: it plays no "
                            f"{', '.join(sorted(missing))} (rsmm templates lists its clips)")


def _switches(ef: EntityFile, d: EntityFile, dctl: EG.Component, slot_ctl: str) -> None:
    for f in EF.fields(dctl):
        if f.name not in CONTROLLER_SWITCHES or "<-" in f.text:
            continue
        kind, _, txt = f.text.partition(" ")
        conv = {"bool": lambda s: s == "True", "f32": float, "int": int}.get(kind)
        if conv is None:
            continue
        try:
            ef.set_value(slot_ctl, f.name, conv(txt))
        except (EntityEditError, ValueError):
            continue


# ---- the catalog -----------------------------------------------------------------

@dataclass
class Entry:
    hero: str
    button: str
    names: list[str]              # every short name it answers to
    entry: str
    clips: list[str]
    values: dict[str, str]        # copied Value part -> its number


def catalog(read, heroes: list[str] | None = None) -> list[Entry]:
    """Every shipped button a template can name, with its clips and numbers."""
    from . import corpus
    stems = sorted({r.split("/")[2] for r in corpus.rels(_HEROES_DIR + "Hero_")
                    if r.count("/") >= 3})
    out = []
    for stem in stems:
        hero = stem.removeprefix("Hero_")
        if heroes and hero not in heroes:
            continue
        if hero in ("Common",) or read(f"Heroes\\{stem}\\{stem}.entity.ot") is None:
            continue
        fam = Family(read, hero)
        d = fam.main
        idx = d.graph().by_guid()
        by_ctl: dict[bytes, list[str]] = {}
        for short, c in controllers(d).items():
            by_ctl.setdefault(c.guid, []).append(short)
        for g, names in by_ctl.items():
            c = idx[g]
            entry = _entry(c, idx)
            parts = [c for _, c in walk(fam, entry)]
            clips = sorted({m.group(0).decode() for p in parts if p.cls == _ANIMATIC
                            for m in re.finditer(rb"Characters\\[ -~]*?\.fbx", p.body)})
            values = {}
            for p in parts:
                if p.cls == _VALUE:
                    f = next((x for x in EF.fields(p) if x.name == "value"), None)
                    if f is not None and "<-" not in f.text:
                        values[p.name] = f.text
            out.append(Entry(hero, names[0], names, entry.name, clips, values))
    return out
