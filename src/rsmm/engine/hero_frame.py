"""A hero written from scratch: its own two entity files on the shared hero
base, with no other hero inside them (roadmap "Hero from scratch A").

How a shipped hero is put together (corpus survey 2026-11-06):

* ``Hero_X`` (its parts: 660 for Juliet, the smallest) has ONE parent,
  ``Hero_X_FX``;
* ``Hero_X_FX`` (a few effect parts; Geppetto's is 6.8 KB) inherits the shared
  base through an ALIAS, not a parent path: an ``AliasPicker`` object holding
  ``Hero_Common``'s alias GUID (``ApplicationSettings.ot``), listed in the
  entity trailer's alias-parent vector right after the (empty) parent list;
* ``Hero_Common`` brings ``Character_Common`` and the interaction/quest parts.
  Kintaro is the exception: his chain runs through his bear's rig
  (``Hero_Kintaro_Bear_Common``) and the alt-form system.

Every hero fills the same SLOTS of that base: 59 parts all 12 shipped heroes
override (idle/dash/death/revive/hit-stun/teleport/spawn/preview/victory/defeat
animations and their sounds, the 5 ability controllers, the ultimates'
controllers, portrait, minimap marker, preview camera), 16 more most do. The
base defines each slot EMPTY (no clip, no sound event, no picture); a hero's
override is the slot with its value in. So a slot here is written as the
base's own part, copied in as an override of itself, its value filled: the
only file read is the shared base, as ``item_frame`` reads only the item model.

What is filled so far: an animation slot's clip and length, a Value slot's
value. Sounds (an FMod event GUID + its 3D settings) come next.
"""

from __future__ import annotations

import re
import struct
import uuid

from . import cooked
from . import entity_parts as P
from .entity_graph_edit import EntityEditError, EntityFile, kind_label
from .item_frame import _ROOT, _empty_entity

HERO_COMMON = "Heroes\\Hero_Common\\Hero_Common.entity.ot"
CHARACTER_COMMON = "Character_Common\\Character_Common.entity.ot"
#: The shared bases a hero's slots live in, by the scope their labels use.
BASES = {"Hero_Common": HERO_COMMON, "Character_Common": CHARACTER_COMMON}
_ANIMATIC = "oCEntityCpntAnimaticSettings"
_VALUE = "oCEntityCpntValueSettings"
#: Where an animation slot keeps its clip(s): (field, bytes before the first
#: clip, how many clips). Each clip is a resource, two strings: empty in the
#: base's slot, ``"3D"`` + the clip path in a hero's override. An animatic
#: has one after its play rate (``00 00 80 3f``); the movement slot (a
#: two-speed animatic) has walk then run after ``01`` + its blend float.
_CLIPS = {_ANIMATIC: ("bytes_8", 4, 1),
          "oCEntityCpntTwoSpeedAnimaticSettings": ("bytes_8", 5, 2)}


class FrameError(ValueError):
    pass


def guid(hid: str, what: str) -> bytes:
    return uuid.uuid5(P._NS, f"hero-frame:{hid}:{what}").bytes


def fx_frame(alias_guid: bytes, identity: bytes) -> bytes:
    """An entity with no parts that inherits the entity behind ``alias_guid``
    (``Hero_Common``'s) the way every hero's FX file does: one ``AliasPicker``
    object, listed in the trailer's alias-parent vector."""
    if len(alias_guid) != 16 or len(identity) != 16:
        raise FrameError("an alias GUID and an identity are 16 bytes")
    cf = cooked.CookedFile(variant="A", hdr_a=0x10, flags=1, extra=1, type_tag=0x31)
    for name in (*_ROOT, "AliasPicker", "oIUniqueObjectPicker"):
        src = P.class_source(name)
        c = next(x for x in src.classes if x.name == name)
        cf.classes.append(cooked.ClassDef(c.name, c.class_id, c.version_major,
                                          c.version_minor, c.parent_id))
    names = [c.name for c in cf.classes]
    settings, picker = names.index("oCEntitySettings"), names.index("AliasPicker")
    table = struct.pack("<II", 1, picker)               # one object: the picker
    alias = struct.pack("<I", picker) + alias_guid
    trailer = (struct.pack("<I", 0) + cooked.MARK_BEGIN + struct.pack("<I", settings)
               + struct.pack("<I", 0)                  # no components
               + b"\x00" + struct.pack("<I", 16) + identity
               + struct.pack("<I", 0)                  # no parent paths
               + b"\xff" * 4 + struct.pack("<II", 1, 0)  # alias parents: [object 0]
               + bytes(4) + cooked.MARK_END)
    cf.sections = [cooked.Section(table), cooked.Section(alias), cooked.Section(trailer)]
    return cooked.emit(cf)


def skin_frame(hero_alias: bytes, identity: bytes,
               values: list[tuple[str, str, bytes, str, str, str]], *, seed: str) -> bytes:
    """A skin: an entity inheriting the hero through its alias (as the FX file
    inherits Hero_Common) that overrides the hero's own material Values.
    ``values``: ``(name, group, hero part GUID, its label, root, path)`` each,
    e.g. ``("Character Mesh Material Value", "Base", guid, "[Value]
    Hero_Jack\\Base\\Character Mesh Material Value", "3D", "...M_Jack.mat.ot")``
    (Hero_Geppetto_Default is exactly this: 4 Values and the alias)."""
    ef = EntityFile(fx_frame(hero_alias, identity), "")
    w = P.PartWriter(ef, f"skin:{seed}")
    for name, group, guid_, label, root, path in values:
        w.add(_VALUE, name, {"value": P.Num(9, P._lstr(root) + P._lstr(path)), "flag": 0},
              flags=0x101, group=group, override=P.Link(guid_, label))
    return ef.to_bytes()


def main_frame(fx_ref: str, identity: bytes) -> bytes:
    """The hero's own entity, empty, inheriting its FX file (``fx_ref``)."""
    return _empty_entity(fx_ref, identity)


def common(read, scope: str = "Hero_Common") -> EntityFile:
    """A shared base (``BASES``), to fill slots from."""
    raw = read(BASES[scope])
    if raw is None:
        raise FrameError(f"{scope} is not readable (no install or mirror)")
    return EntityFile(raw, scope)


def fill_slot(ef: EntityFile, base: EntityFile, slot: str, *,
              clip: str | list[str] | None = None,
              duration: float | None = None, value=None,
              texture: tuple[str, str] | None = None, seed: str = "") -> str:
    """Override ``base``'s part ``slot`` in ``ef``: the base's own part copied
    in, marked as its override, with ``clip`` (and its ``duration`` in seconds)
    for an animation slot (a list for the movement slot: walk, run), ``value``
    (a number or vector) or ``texture`` (``(root, path)``, e.g. ``("Ui",
    "Heroes\\Jack\\Portrait.png")``) for a Value slot. Returns its name."""
    try:
        c = base.component(slot)
    except EntityEditError as e:
        raise FrameError(f"the hero base has no slot {slot!r}") from e
    if any(x.name == slot for x in ef.graph().components):
        raise FrameError(f"slot {slot!r} is already filled")
    try:
        ef.clone([c.path], seed=f"{seed}:{slot}", source=base)
        # When the base's part is itself an override (Hero_Common's "Dying
        # Death Anim Default" overrides Character_Common's), every shipped hero
        # overrides the ORIGINAL part's GUID under the base's label; an
        # override record's own GUID is never resolved (see HERO_CONTROLLER).
        target = c.override.guid if c.override is not None else c.guid
        ef.set_override(slot, target, f"[{kind_label(c.cls)}] {base.name}\\{c.path}")
        if clip is not None:
            if c.cls not in _CLIPS:
                raise FrameError(f"slot {slot!r} is a {c.cls}, not an animation")
            _set_clips(ef, slot, [clip] if isinstance(clip, str) else list(clip))
            if duration is not None:
                _set_duration(ef, slot, float(duration))
        if value is not None or texture is not None:
            if c.cls != _VALUE:
                raise FrameError(f"slot {slot!r} is a {c.cls}, not a value")
            if value is not None:
                ef.set_value(slot, "value", value)
            else:
                _set_texture(ef, slot, *texture)
    except EntityEditError as e:
        raise FrameError(f"slot {slot!r}: {e}") from e
    return slot


def _set_clips(ef: EntityFile, slot: str, clips: list[str]) -> None:
    from . import entity_fields as EF
    c = ef.component(slot)
    field, skip, count = _CLIPS[c.cls]
    if len(clips) != count:
        raise FrameError(f"slot {slot!r} takes {count} clip(s), got {len(clips)}")
    f = next((x for x in EF.fields(c) if x.name == field), None)
    empty = (P._lstr("") + P._lstr("")) * count
    at = f.offset + skip if f is not None else -1
    if f is None or c.body[at:at + len(empty)] != empty:
        raise FrameError(f"slot {slot!r}: the clip field is not where this kind keeps it")
    p = ef.objects[c.index - 1]
    a = len(p) - len(c.body) + at
    p[a:a + len(empty)] = b"".join(P._lstr("3D") + P._lstr(x) for x in clips)


def replace_in_slot(ef: EntityFile, slot: str, old: str, new: str) -> int:
    """Swap the string ``old`` for ``new`` inside the filled slot ``slot`` (a
    mesh path); how many times. The payload re-frames on write."""
    c = ef.component(slot)
    p = ef.objects[c.index - 1]
    head = len(p) - len(c.body)
    body = bytes(p[head:])
    n = body.count(P._lstr(old))
    if not n:
        raise FrameError(f"slot {slot!r} does not hold {old!r}")
    p[head:] = body.replace(P._lstr(old), P._lstr(new))
    return n


def relabel_base_links(ef: EntityFile, filled: dict[bytes, tuple[str, str]], scope: str) -> int:
    """Links among the filled slots name the base's part by its GUID; a shipped
    hero labels them with its OWN scope (Geppetto's mesh reads ``[Anim
    skeleton] Hero_Geppetto\\Base\\Mesh Skeleton`` with Character_Common's
    GUID). ``filled``: base GUID -> (kind label, path) of each filled slot."""
    n = 0
    for c in ef.graph().components:
        for r in c.refs:
            if r.guid in filled and not r.path.startswith(f"[{filled[r.guid][0]}] {scope}\\"):
                kind, path = filled[r.guid]
                n += ef.retarget_external(c.name, r.guid, r.guid, f"[{kind}] {scope}\\{path}")
    return n


#: How a Value is read as a resource through a link (Geppetto's mesh reading
#: its material value part).
_RESOURCE_ACCESSOR = 0x0FD2C96D


def source_resource(ef: EntityFile, slot: str, field: str, target: str) -> None:
    """Make resource field ``field`` of ``slot`` read Value part ``target``
    (the mesh's material: the skin overrides that Value)."""
    from . import entity_fields as EF
    c = ef.component(slot)
    f = next((x for x in EF.fields(c) if x.name == field), None)
    if f is None or f.kind != "value":
        raise FrameError(f"slot {slot!r} has no value field {field!r}")
    w = P.PartWriter(ef, "source")
    new = (P._B + struct.pack("<I", w.ci("oCEntityCpntValuePicker")) + b"\x01\x00"
           + ef._picker(target) + struct.pack("<I", _RESOURCE_ACCESSOR)
           + P._B + struct.pack("<I", w.ci("oCEntityValueUnion"))
           + struct.pack("<II", 9, 0) + P._lstr("") + P._lstr("") + P._E + P._E)
    p = ef.objects[c.index - 1]
    a = len(p) - len(c.body) + f.offset
    p[a:a + f.size] = new


def resource_value(ef: EntityFile, name: str, root: str, path: str, *, group: str,
                   seed: str) -> str:
    """A Value part of the hero's own holding a resource (a material)."""
    w = P.PartWriter(ef, f"{seed}:{name}")
    w.add(_VALUE, name, {"value": P.Num(9, P._lstr(root) + P._lstr(path)), "flag": 0},
          flags=0x101, group=group)
    return name


#: The shared body slots and the mesh path the base puts in them (Scarlet's).
_BASE_MESH = "Characters\\Heroes\\RED\\RED_Human_GEO.fbx"


def fill_body(ef: EntityFile, character_common: EntityFile, *, mesh: str, material: str,
              acc_material: str | None = None, seed: str = "") -> None:
    """The hero's body: ``Character Mesh`` and ``Mesh Skeleton`` (Character_Common
    slots) on ``mesh``, the mesh's materials read from two Value parts of the
    hero's own, as every shipped hero's are (its skins override those)."""
    for slot in ("Mesh Skeleton", "Character Mesh"):
        fill_slot(ef, character_common, slot, seed=seed)
        replace_in_slot(ef, slot, _BASE_MESH, mesh)
    for name, mat, field in (("Character Mesh Material Value", material, "value_15"),
                             ("Character Mesh Acc Material Value", acc_material or material,
                              "value_16")):
        resource_value(ef, name, "3D", mat, group="Base", seed=seed)
        source_resource(ef, "Character Mesh", field, name)


#: The shared hero controller every shipped talent links: Hero_Common's ORIGINAL
#: part's GUID (bfe7f660..., 739 shipped links), under the Update 5 label. NOT
#: the Update 5 override record's own GUID (f8e4064e...): nothing resolves a
#: link by an override's own id, so a talent linked that way never found its
#: hero controller (ctrl+0x78 null), never joined an offer pool, and every pick
#: window closed empty (Jack, playtest 2026-11-08; activation 0x1402e8250).
HERO_CONTROLLER = (bytes.fromhex("bfe7f6604385cb4887f6b4b79f6812a5"),
                   "[Dt Hero Controller] Hero_Common_Update5\\Hero Controller\\Hero Controller")
#: The base's own talent card parts, used as the layout of a hero's talent.
_CONTROLLER = "Skill Controller Ultimate 1 Upgrade 1"
_DESC = "Skill String Desc Ultimate 1 Upgrade 1"
_EMPTY_TEXT = struct.pack("<II", 0, 3) + P._lstr("") + P._lstr("") + struct.pack("<i", -1) \
    + P._lstr("")


def _set_text(ef: EntityFile, comp: str, bank: str, key: str) -> None:
    """Fill the one empty localized text in ``comp``: ``Text`` + bank + key."""
    c = ef.component(comp)
    p = ef.objects[c.index - 1]
    head = len(p) - len(c.body)
    at = c.body.find(_EMPTY_TEXT)
    if at < 0:
        raise FrameError(f"{comp!r} holds no empty text")
    a = head + at
    p[a:a + len(_EMPTY_TEXT)] = (struct.pack("<II", 0, 3) + P._lstr("Text") + P._lstr(bank)
                                 + struct.pack("<i", -1) + P._lstr(key))


#: A talent controller's offer pool (``bytes_4``), read off every shipped
#: controller: 1 = the level-up pool (most talents), 0 = the STARTING pick at
#: the beginning of a run (4-5 per hero: Kintaro's Attack Quest Lightning,
#: Passive Bear Combo, Passive Move Speed, Power Bear Charge), 2 = ultimate
#: powers, 3 = ultimate upgrades. All cards in 0 left the level-up pick empty;
#: none in 0 showed "available in an upcoming update" on every starting card
#: (playtests 2026-11-07).
POOL_LEVEL_UP, POOL_STARTER = 1, 0
#: A component's header flag "starts active" (0x100). A talent controller
#: registers in the hero's offer pools only when it activates (FUN_1402ed820,
#: R.talent notes), and every ordinary shipped talent starts active
#: (0x1000101); only ultimate UPGRADES start off (0x1000001) until their
#: ultimate is owned. Cards copied from an upgrade without it were never dealt,
#: and opening one in the compendium crashed the game (playtest 2026-11-07).
STARTS_ACTIVE = 0x100


def _header_flags(ef: EntityFile, name: str) -> tuple[bytearray, int]:
    c = ef.component(name)
    p = ef.objects[c.index - 1]
    return p, len(p) - len(c.body) - 8 - len(c.group.encode("latin-1"))


def set_starts_active(ef: EntityFile, name: str, on: bool = True) -> None:
    p, at = _header_flags(ef, name)
    v = struct.unpack_from("<I", p, at)[0]
    struct.pack_into("<I", p, at, (v | STARTS_ACTIVE) if on else (v & ~STARTS_ACTIVE))


def add_talent(ef: EntityFile, hero_common: EntityFile, talent: str, *, bank: str,
               name_key: str, desc_key: str, icon: str, seed: str = "",
               pool: int = POOL_LEVEL_UP) -> str:
    """One talent card of the hero's own: its owned state (``Skill <T>``, what
    the talent's effect hangs off; ``talent_add_stat`` builds on it), its
    controller (``Skill Controller <T>``: the row the herodef lists, by GUID)
    and its description format, written on the base's own talent card parts.
    The category is the name's first word (Attack, Power, Special, Defense,
    Trait, Dash, Passive): the book's grid reads it from the name."""
    from . import talent_writer as TW
    ctl, desc, state = (f"Skill Controller {talent}", f"Skill String Desc {talent}",
                        f"Skill {talent}")
    try:
        TW.TalentWriter(ef, f"{seed}:{talent}", state).state(state, mode=2)
        ef.clone([f"Skills\\{_CONTROLLER}", f"Skills\\{_DESC}"], seed=f"{seed}:{talent}",
                 rename={_CONTROLLER: ctl, _DESC: desc}, source=hero_common)
        base_ctl = hero_common.component("Hero Controller")
        ef.retarget_external(ctl, base_ctl.guid, *HERO_CONTROLLER)
        ef.set_ref(ctl, "ref_3", state)
        ef.set_value(ctl, "bytes_4", struct.pack("<I", pool).hex())   # its offer pool
        set_starts_active(ef, ctl)                 # registers in the pools (see above)
        _set_text(ef, ctl, bank, name_key)
        _set_text(ef, desc, bank, desc_key)
        import re
        found = re.search(rb"[ -~]+?\.png", bytes(ef.objects[ef.component(ctl).index - 1]))
        if found is None:
            raise FrameError("the base talent card has no icon to replace")
        old_icon = found.group(0).decode()
        replace_in_slot(ef, ctl, old_icon, icon)
    except EntityEditError as e:
        raise FrameError(f"talent {talent!r}: {e}") from e
    return ctl


#: The ultimate cards every hero overrides on Hero_Common's own controllers
#: (Kintaro: all six, each with its own name, description, icon; the upgrades
#: with a state of their own). Left alone they draw as EMPTY cards (playtest
#: 2026-11-07). Herodef rows keep naming the base GUIDs; the override wins.
ULTIMATES = ("Ultimate Power 1", "Ultimate 1 Upgrade 1", "Ultimate 1 Upgrade 2",
             "Ultimate Power 2", "Ultimate 2 Upgrade 1", "Ultimate 2 Upgrade 2")


def fill_ultimate(ef: EntityFile, hero_common: EntityFile, name: str, *, bank: str,
                  name_key: str, desc_key: str, icon: str = "", seed: str = "") -> str:
    """Hero_Common's ``Skill Controller <name>`` overridden with the hero's
    own card: name, description (a String Format of its own), icon. An
    upgrade also gets an owned state of its own (``Skill <name>``), so
    ``talent_add_stat`` can hang effects off it as on any talent."""
    from . import talent_writer as TW
    if name not in ULTIMATES:
        raise FrameError(f"ultimate {name!r}: one of {', '.join(ULTIMATES)}")
    ctl, desc = f"Skill Controller {name}", f"Skill String Desc {name}"
    fill_slot(ef, hero_common, ctl, seed=seed)
    try:
        ef.clone([f"Skills\\{_DESC}"], seed=f"{seed}:{name}:desc", rename={_DESC: desc},
                 source=hero_common)
        _set_text(ef, ctl, bank, name_key)
        _set_text(ef, desc, bank, desc_key)
        ef.set_ref(ctl, "ref_10", desc)
        # An ultimate POWER card reads its name through a format part of the
        # base's (empty there; Kintaro overrides it with his text): override it.
        fmt = f"Skill String Name {name}"
        if any(c.name == fmt for c in hero_common.graph().components):
            fill_slot(ef, hero_common, fmt, seed=seed)
            _set_text(ef, fmt, bank, name_key)
        if "Upgrade" in name:
            state = f"Skill {name}"
            TW.TalentWriter(ef, f"{seed}:{name}", state).state(state, mode=2)
            ef.set_ref(ctl, "ref_3", state)
        if icon:
            import re
            found = re.search(rb"[ -~]+?\.png", bytes(ef.objects[ef.component(ctl).index - 1]))
            if found is None:
                raise FrameError(f"{ctl} has no icon to replace")
            replace_in_slot(ef, ctl, found.group(0).decode(), icon)
    except EntityEditError as e:
        raise FrameError(f"ultimate {name!r}: {e}") from e
    return ctl


#: The hand weapon: Character_Common's "Weapon In Right Hand Mesh", which
#: every hero overrides with its mesh hung on a bone of its body (Kintaro:
#: Kintaro_Axe_GEO.fbx on 'DEF.Weapon.R'). A hero written from scratch had
#: none, so held nothing (playtest 2026-11-07).
WEAPON_SLOT = "Weapon In Right Hand Mesh"


#: Hero_Common's preview behaviour (the select screen, the hero's book page):
#: the weapon is shown there too. In the run, Character_Common's "Event
#: Initialize" switches it on; the preview never runs that, so the hero stood
#: there empty-handed (playtest 2026-11-07). Kintaro shows his through his
#: alt-form system's default state, which a hero without one does not have.
PREVIEW_STATE = "Child Behaviour Preview"


def add_weapon(ef: EntityFile, donor: EntityFile, character_common: EntityFile, *,
               mesh: str = "", material: str = "", seed: str = "",
               hero_common: EntityFile | None = None) -> str:
    """``donor``'s own hand-weapon override (a shipped hero's) copied in, its
    parent re-pointed from the donor's body mesh to the shared base's
    ``Character Mesh`` (the bone it hangs on is kept), and its mesh swapped
    for ``mesh`` when given. Every other link into the donor's own files is
    resolved, or the weapon draws nothing (playtest 2026-11-07: no axe): one to
    an override of a base part goes to that base part; the material link
    (the donor's "Weapon In Right Hand Material", which its skins override)
    reads a material Value of the hero's own holding ``material``."""
    from . import entity_fields as EF
    try:
        d = donor.component(WEAPON_SLOT)
        ef.clone([d.path], seed=f"{seed}:weapon", source=donor)
        body = character_common.component("Character Mesh")
        parent = next(r for r in d.refs if r.path.startswith("[3d graphic object]")
                      and "Weapons" not in r.path)
        ef.retarget_external(WEAPON_SLOT, parent.guid, body.guid,
                             f"[3d graphic object] {character_common.name}\\{body.path}")
        own = {c.guid: c for c in donor.graph().components}
        base_by_name = {c.name: c for c in character_common.graph().components}
        for r in d.refs:
            if r.guid == parent.guid:
                continue
            t = own.get(r.guid)
            if t is not None and t.override is not None:
                ef.retarget_external(WEAPON_SLOT, r.guid, t.override.guid, t.override.path)
            elif r.path.startswith("[Value]") and "Material" in r.path:
                continue                    # the material Value: re-sourced below
            elif r.path.split("] ", 1)[-1].startswith(donor.name + "\\"):
                # A part of the donor's own (Aladdin's "Weapons Emissive Mix
                # Shader Param") or of a file only it inherits (Kintaro's
                # Bear_Common): the shared base's part of that name, which the
                # hero inherits too -- else a link into a file the hero never
                # loads, and the weapon draws nothing.
                name = r.path.rsplit("\\", 1)[-1]
                b = base_by_name.get(name) or base_by_name.get(name.removeprefix("Weapons "))
                if b is None:
                    raise FrameError(f"weapon links {r.path}, which the hero cannot reach")
                kind = r.path.split("] ", 1)[0]
                ef.retarget_external(WEAPON_SLOT, r.guid, b.guid,
                                     f"{kind}] {character_common.name}\\{b.path}")
        # the material: the donor's skin's own, unless one is given
        # The field reading the material Value, whatever the donor named it
        # (Kintaro "Weapon In Right Hand Material", Aladdin "Weapon Mesh
        # Material Value"); left on the donor's own Value it links into a file
        # the hero does not inherit and the weapon draws nothing.
        mat_field = next((f.name for f in EF.fields(ef.component(WEAPON_SLOT))
                          if f.kind == "value" and "[Value]" in f.text
                          and "Material" in f.text), None)
        if mat_field is not None:
            if not material:
                material = _donor_weapon_material(donor)
            if not material:
                raise FrameError(f"{donor.name}'s weapon material is not known; give one")
            resource_value(ef, "Weapon In Right Hand Material Value", "3D", material,
                           group="Weapons", seed=seed)
            source_resource(ef, WEAPON_SLOT, mat_field, "Weapon In Right Hand Material Value")
        if mesh:
            import re
            old = re.search(rb"[ -~]+?\.fbx", d.body)
            if old is None:
                raise FrameError(f"{donor.name}'s weapon names no mesh")
            replace_in_slot(ef, WEAPON_SLOT, old.group(0).decode(), mesh)
        if hero_common is not None:
            fill_slot(ef, hero_common, PREVIEW_STATE, seed=seed)
            ef.add_ref(PREVIEW_STATE, "while_active", WEAPON_SLOT)
    except (EntityEditError, StopIteration) as e:
        raise FrameError(f"weapon: {e}") from e
    return WEAPON_SLOT


def _donor_weapon_material(donor: EntityFile) -> str:
    """The material the donor's default skin gives its hand weapon (Kintaro:
    M_KintaroAxe.mat.ot), else its own Value's."""
    import re

    from . import corpus
    stem = donor.name
    # The weapon names its material Value by link; heroes name it differently
    # (Kintaro "Weapon In Right Hand Material", Aladdin "Weapon Mesh Material
    # Value"), and the skin overrides that Value with the real material.
    names = {"Weapon In Right Hand Material"}
    try:
        names |= {r.path.rsplit("\\", 1)[-1] for r in donor.component(WEAPON_SLOT).refs
                  if r.path.startswith("[Value]") and "Material" in r.path}
    except EntityEditError:
        pass
    for ref in (f"Heroes\\{stem}\\{stem}_Default.entity.ot", f"Heroes\\{stem}\\{stem}.entity.ot"):
        raw = corpus.read(f"EntitySettings/{ref.replace(chr(92), '/')}.EntitySettingsResource.gen")
        if not raw:
            continue
        from . import entity_graph as EG
        for c in EG.parse(raw).components:
            if c.name in names:
                m = re.search(rb"[ -~]+?\.mat\.ot", c.body)
                if m and b"Dt_" not in m.group(0):
                    return m.group(0).decode()
    return ""


#: A texture literal: union type 6, a pad u32, then root and path strings
#: (both empty in the base's slot).
_TEXTURE = struct.pack("<II", 6, 0)


def _set_texture(ef: EntityFile, slot: str, root: str, path: str) -> None:
    """The slot's one texture literal set to ``(root, path)``: empty in most
    base slots, a shipped picture in a few (``Abilities Banner Picture``
    holds Red's banner)."""
    c = ef.component(slot)
    hits = [m.start() for m in re.finditer(re.escape(_TEXTURE), c.body)]
    if len(hits) != 1:
        raise FrameError(f"slot {slot!r} holds {len(hits)} textures, not one")
    at = hits[0] + len(_TEXTURE)
    old = 0
    for _ in range(2):                     # root, then path: u32 length + bytes
        (n,) = struct.unpack_from("<I", c.body, at + old)
        old += 4 + n
    p = ef.objects[c.index - 1]
    a = len(p) - len(c.body) + at
    p[a:a + old] = P._lstr(root) + P._lstr(path)


def _set_duration(ef: EntityFile, slot: str, seconds: float) -> None:
    """The animatic timeline's length (``oCCinematic``: bloc count, bloc ids,
    then the length in seconds; 0 in the base)."""
    c = ef.component(slot)
    names = [x.name for x in ef.cf.classes]
    p = ef.objects[c.index - 1]
    pos = p.find(P._B + struct.pack("<I", names.index("oCCinematic")))
    if pos < 0:
        raise FrameError(f"slot {slot!r} has no timeline")
    count = struct.unpack_from("<I", p, pos + 8)[0]
    struct.pack_into("<f", p, pos + 12 + 4 * count, seconds)


def talent_effects(raw: bytes, hero_common: EntityFile, effects: dict[str, dict], *,
                   scope: str, seed: str) -> bytes:
    """Each talent's effect, written onto its owned state (``talent_add_stat``):
    ``add_stats`` (the talent kind's entries without ``talent``: always on,
    ``during``/``after`` an ability, ``on`` a game event) and ``actions``
    (``{on, hits}``: each time game event ``on`` fires while the talent is
    owned, area hits as the buttons' are written)."""
    from . import hero_ability as HA
    from . import talent_add_stat as TA
    from . import talent_writer as TW
    for talent, spec in effects.items():
        try:
            for e in spec.get("add_stats") or []:
                raw, _added = TA.add_stat(
                    raw, talent=talent, stat=e["stat"], values=e.get("values"),
                    percent=e.get("percent", True), seed=f"{seed}:{talent}",
                    during=e.get("during"), after=e.get("after"), seconds=e.get("seconds"),
                    cooldown=e.get("cooldown"), next_ability=e.get("next"), on=e.get("on"))
            for n, a in enumerate(spec.get("actions") or [], 1):
                raw, state = TA.add_action_trigger(raw, talent=talent, on=str(a["on"]), n=n,
                                                   seed=f"{seed}:{talent}")
                ef = EntityFile(raw, scope)
                group = f"Skill {talent}"
                w = TW.TalentWriter(ef, f"{seed}:{talent}:action{n}", group)
                todo = HA.parse_hits(a.get("hits"), f"talent {talent}")
                # An action fired by an ability counts as that ability's damage
                # (so its talents boost it); one fired by an event, as none.
                for t in HA.hits(ef, hero_common, w, todo, tag=f"{talent} Action {n}",
                                 group=group, seed=f"{seed}:{talent}:action{n}",
                                 kind=str(a["on"])):
                    ef.add_ref(state, "activates", t)
                HA.statuses(ef, todo, tag=f"{talent} Action {n}", switch=state,
                            seed=f"{seed}:{talent}:action{n}")
                raw = ef.to_bytes()
        except (TA.AddStatError, HA.AbilityError, EntityEditError, KeyError) as e:
            raise FrameError(f"talent {talent!r}: {e}") from e
    return raw


#: What the hero builder's kit (engine/hero_kit.py) builds from, for a hero
#: with no base to lend it: ability steps that copy, into the hero's own file,
#: a projectile spawner of the shape every hero projectile uses (no
#: attachment, aimed through one node: Update 5's melody zone spawner), its aim (Hero_Common's
#: Divine Revive node, which hangs off Character_Common's Entity Node, so no
#: link leads into another hero; its yaw zeroed), a spawner value, a plain
#: number and an empty state (Hero_Common's, all parts of their own). The node
#: turns with the hero, so shots go where the button turned him: the buttons'
#: look-at (hero_ability.LOOK_AT) is what aims them.
KIT_DONORS: list[dict] = [
    {"clone": ["Divine Revive 3d Node"], "from": "Heroes/Hero_Common/Hero_Common",
     "rename": {"Divine Revive 3d Node": "Kit Aim"}},
    {"set": "Kit Aim.obj_4[8]", "value": 0.0},
    # The shared base's own attack spawner (Update 5's melody zone): every
    # field Kintaro's Ultimate 2 projectile spawner has, except the template,
    # aim and values each shot re-sets; no hero's spawner is copied.
    {"clone": ["Melody Deal Damage Around Attack Zone Spawner"],
     "from": "Heroes/Hero_Common/Hero_Common_Update5",
     "rename": {"Melody Deal Damage Around Attack Zone Spawner": "Kit Projectile Spawner"}},
    {"link": "Kit Projectile Spawner.position[0]", "to": "Kit Aim"},
    {"remove_link": "Kit Projectile Spawner.spawner_values[0]"},
    {"clone": ["Bean Gain Spawner Value"], "from": "Heroes/Hero_Common/Hero_Common",
     "rename": {"Bean Gain Spawner Value": "Kit Spawner Value"}},
    {"clone": ["AP Basic Value"], "from": "Heroes/Hero_Common/Hero_Common",
     "rename": {"AP Basic Value": "Kit Number"}},
    {"clone": ["Child Event On Deathdoor Revive"], "from": "Heroes/Hero_Common/Hero_Common",
     "rename": {"Child Event On Deathdoor Revive": "Kit Empty State"}},
]


__all__ = ["BASES", "CHARACTER_COMMON", "HERO_COMMON", "HERO_CONTROLLER", "FrameError",
           "add_talent", "build_hero", "clip_length", "common", "fill_body", "fill_slot",
           "fx_frame", "guid", "KIT_DONORS", "main_frame", "relabel_base_links", "replace_in_slot",
           "resource_value", "rig_slots", "skin_frame", "source_resource",
           "talent_effects"]


# --------------------------------------------------------------------------
# a whole hero
# --------------------------------------------------------------------------

_ANIM_KINDS = tuple(_CLIPS)
_CLIP_RE = __import__("re").compile(rb"Characters\\[ -~]+?\.fbx")


def clip_length(clip: str) -> float | None:
    """A cooked clip's length in seconds (None if the game does not ship it)."""
    from . import corpus
    from .cooked_schemas import animation as A
    raw = corpus.read("3D/" + clip.replace("\\", "/") + ".Animation.gen")
    if raw is None:
        return None
    cf = cooked.parse(raw)
    return A.parse_payload(b"".join(s.payload for s in cf.sections)).duration


def _shipped_clip(clip: str) -> bool:
    from . import corpus
    return corpus.read("3D/" + clip.replace("\\", "/") + ".Animation.gen") is not None


def rig_slots(read, rig: str) -> dict[str, dict]:
    """``{slot: {"clip": path | [walk, run], "duration": s}}`` for every shared
    animation slot the rig hero (``Hero_Kintaro``) fills, its ON-FOOT clip
    where it has two forms: its alt-form slot of the same name (``Deathdoor
    Alt Anim In`` for ``Deathdoor Anim In``) first, then a clip not ridden
    (``Bear_`` prefix), then the ``Bear_``-less twin of a ridden clip. The rig
    lends only motion: its files, look and abilities are not used."""
    import re

    from . import corpus
    from . import entity_graph as EG
    picked: dict[str, tuple[int, list[str]]] = {}
    for rel in corpus.rels(f"EntitySettings/Heroes/{rig}/", ".EntitySettingsResource.gen"):
        for c in EG.parse(corpus.read(rel)).components:
            if c.cls not in _ANIM_KINDS or c.override is None:
                continue
            base = c.override.path.split("] ", 1)[-1]
            scope, _, path = base.partition("\\")
            if scope not in (*BASES, "Hero_Alt_Form_Common"):
                continue
            name = path.rsplit("\\", 1)[-1]
            alt = scope == "Hero_Alt_Form_Common"
            slot = re.sub(r" Alt\b", "", name) if alt else name
            clips = [m.decode() for m in _CLIP_RE.findall(c.body)]
            if not clips:
                continue
            rank = 0 if alt else 1
            if any("\\Bear_" in x for x in clips):
                twins = [x.replace("\\Bear_", "\\") for x in clips]
                if all(_shipped_clip(x) for x in twins):
                    clips, rank = twins, 2
                else:
                    continue
            if slot not in picked or rank < picked[slot][0]:
                picked[slot] = (rank, clips)
    out = {}
    for slot, (_r, clips) in picked.items():
        spec = {"clip": clips[0] if len(clips) == 1 else clips}
        if len(clips) == 1 and (length := clip_length(clips[0])) is not None:
            spec["duration"] = length
        out[slot] = spec
    return out


def build_hero(read, *, scope: str, fx_ref: str, common_alias: bytes, mesh: str,
               material: str, slots: dict[str, dict], talents: list[tuple[str, bytes, dict]],
               seed: str, abilities: list | None = None,
               effects: dict[str, dict] | None = None,
               indicators: bool = True, ultimates: list[tuple[str, dict]] | None = None,
               weapon: tuple | None = None) -> tuple[bytes, bytes, list[tuple]]:
    """A hero written from scratch: ``(main entity, FX entity, skin values)``.

    ``slots``: shared slot -> its fill (``fill_slot``'s ``clip``/``duration``/
    ``texture``/``value``); a slot neither base has is refused. ``talents``:
    ``(name, row GUID, card)`` per herodef row, the controller written with
    that GUID so the herodef's row reaches it (``card``: ``bank``,
    ``name_key``, ``desc_key``, ``icon``). The skin values are what a skin
    overrides (``skin_frame``)."""
    hc, cc = common(read, "Hero_Common"), common(read, "Character_Common")
    fx = fx_frame(common_alias, guid(scope, "fx"))
    ef = EntityFile(main_frame(fx_ref, guid(scope, "main")), scope)
    fill_body(ef, cc, mesh=mesh, material=material, seed=seed)
    for slot, fill in sorted(slots.items()):
        if slot in ("Mesh Skeleton", "Character Mesh"):
            continue
        base = hc if any(c.name == slot for c in hc.graph().components) else cc
        if not any(c.name == slot for c in base.graph().components):
            raise FrameError(f"no shared slot {slot!r}")
        fill_slot(ef, base, slot, seed=seed, **fill)
    from . import hero_ability as HA
    for ab in abilities or []:
        HA.build(ef, hc, ab, seed=seed, with_indicator=indicators)
    for name, row, card in talents:
        ctl = add_talent(ef, hc, name, seed=seed, **card)
        c = ef.component(ctl)
        p = ef.objects[c.index - 1]
        p[:] = bytes(p).replace(c.guid, row)
    for name, card in ultimates or []:
        fill_ultimate(ef, hc, name, seed=seed, **card)
    if weapon is not None:
        donor, mesh_ref, mat_ref = (*weapon, "")[:3]
        add_weapon(ef, donor, cc, mesh=mesh_ref, material=mat_ref, seed=seed, hero_common=hc)
    out = ef.to_bytes()
    out = talent_effects(out, hc, effects or {}, scope=scope, seed=seed)
    from . import entity_graph as EG
    comps = EG.parse(out, scope).components
    filled = {c.override.guid: (c.override.path.split("]")[0][1:], c.path)
              for c in comps if c.override}
    ef = EntityFile(out, scope)
    relabel_base_links(ef, filled, scope)
    out = ef.to_bytes()
    skin = [(c.name, c.group, c.guid, f"[Value] {scope}\\{c.path}", "3D", material)
            for c in EG.parse(out, scope).components
            if c.name in ("Character Mesh Material Value", "Character Mesh Acc Material Value")]
    return out, fx, skin
