"""Add gameplay COMPONENTS to a shipped entity, in place.

Every POI note in this repo said a minimap marker and an interaction were
unreachable for a mod, because "a level cannot reference a mod-owned entity and
an in-place override cannot ADD a component". The first half holds. The second
half is false, and the machinery to disprove it has been here since the menu
work:

* a cooked entity's section 0 is a component DIRECTORY and every component
  record is self-framed, so components append -- :mod:`entity_append`;
* a class the host's table lacks can be copied in from the donor by name --
  :func:`mods_modal.extend_class_table`;
* a cloned record's class indices are rewritten donor->host by
  :func:`mods_modal._remap_class_tags`.

Pointing those three at an entity's components rather than a UI page is what
:func:`add_components` does, and it is byte-stable (2026-09-04). It is NOT how
you give an entity a minimap marker or an interaction prompt -- measured
in-game 2026-09-05, the spliced records were inert.

**Use :func:`add_parents`.** The trailing section of every entity carries a
list of PARENT entity references, and that is where behaviour comes from:
``Chest_Model`` is interactable and map-marked because it names
``Interactive_Object_Model`` and ``Minimap_Marker_Reveal_Model`` as parents,
not because it carries those components. A settings component is an OVERRIDE
whose fields are named bindings into a parent's namespace
(``[State] Interactive_Object_Model\\Interaction\\State Interaction In
Progress``); with no such parent they bind to nothing, so the component loads,
does nothing, and logs nothing. The interaction behaviour alone is a
74-component sub-graph that only inheritance brings along.

:func:`add_components` is kept because it is the way to override a parent's
settings once inheritance supplies the machinery -- a custom marker icon, say.
"""

from __future__ import annotations

import struct

from . import cooked
from . import entity_append as EA
from . import entity_strings as ES
from . import mods_modal as MM

#: The component class that puts an icon on the map.
MARKER_CLASS = "oCDtEntityCpntMinimapMarkerSettings"


class EntityComponentError(ValueError):
    pass


#: name -> the entity whose behaviour a host inherits by naming it as a PARENT.
#:
#: This is how the game does it. `Chest_Model` is interactable and shows on the
#: map because it lists `Interactive_Object_Model` and
#: `Minimap_Marker_Reveal_Model` as parents -- not because it carries a marker
#: or an interaction component of its own. Both mappings are copied straight
#: off that chest, which demonstrably has a prompt and an icon in-game.
PARENTS: dict[str, str] = {
    "minimap": "Common_Settings\\Minimap_Marker_Reveal_Model.entity.ot",
    "interaction": "Interactive_Common\\Interactive_Object_Model.entity.ot",
}

#: The resource root every parent reference is filed under.
_PARENT_ROOT = "EntitySettings"

#: Bytes between the end of the parent list and the record's END marker: a u32
#: field (0xffffffff on most entities, a small enum on 127 of them) plus two
#: zero u32s -- and, on 127 entities, one more u32. Both shapes appear in the
#: shipped corpus and nothing else does, so this doubles as the walk's proof:
#: land anywhere but here and the offsets were wrong.
_TAIL_SIZES = (16, 20)


#: name -> (donor entity ref, component class).
#:
#: Donors are chosen for being PLACEABLE, which is the property that matters:
#: the marker-bearing entities that look more natural (Reward_Spawner_-
#: Interactive_Model, Key_Keeper_Key, Map_Boss_Spawner_Model, Teleporter_Model)
#: are sub-entities a spawner selects and are never placed on their own.
DONORS: dict[str, tuple[str, str]] = {
    "minimap": (
        "Avalon\\Objects_Tree_Quest\\Orchard_Minimap_Marker.entity.ot",
        "oCDtEntityCpntMinimapMarkerSettings",
    ),
    "interaction": (
        "Objects\\Key_Lock\\Key_Lock.entity.ot",
        "oCDtEntityCpntInteractionSettings",
    ),
}


#: Curated OVERRIDE donors -- ``key -> (parent ref, donor ref, binding prefix)``.
#:
#: Inheriting a parent supplies the MACHINERY; it does not supply the settings
#: that machinery reads. `Minimap_Marker_Reveal_Model` ships with no icon in
#: its texture Values, so a host that only inherits it runs the whole reveal
#: state machine and draws nothing -- which is exactly what three playtests
#: measured and mis-attributed to "gating components". A shipped child says
#: what the missing half looks like: `Leprechaun_Cauldron_Minimap_Marker`'s
#: entire body is seven `oCEntityCpntValueSettings` records whose first string
#: is a binding path into the parent (``[Value] Minimap_Marker_Reveal_Model\\
#: Hero Presence MiniMap Marker Model\\Minimap Big Marker Texture Value``) and
#: whose payload is a literal ``.png``. Copy those and the icon appears.
#:
#: Both donors are the MINIMAL child in the corpus for their parent: the
#: cauldron marker is 10 records and inherits nothing else, and
#: `Ingredient_Stock_Model` is the only `Interactive_Object_Model` child whose
#: interaction overrides are literal rather than routed through a selector.
OVERRIDE_DONORS: dict[str, tuple[str, str, str]] = {
    "minimap": (
        "Common_Settings\\Minimap_Marker_Reveal_Model.entity.ot",
        "Objects\\Leprechaun_Cauldron\\Leprechaun_Cauldron_Minimap_Marker.entity.ot",
        "Minimap_Marker_Reveal_Model\\",
    ),
    "interaction": (
        "Interactive_Common\\Interactive_Object_Model.entity.ot",
        "Objects_Common\\Ingredient_Stock_Model.entity.ot",
        "Interactive_Object_Model\\Interaction\\",
    ),
}

#: Extra overrides that decide whether a marker can be SEEN, and the shipped
#: entity to take each from -- ``(donor ref, target suffix, known literal)``.
#:
#: `Minimap_Marker_Reveal_Model` is a HERO-PRESENCE marker: it reveals when the
#: hero is already close. For a shipped landmark that is right; for a mod POI it
#: is circular, because the icon is how you find the thing in the first place.
#: Measured 2026-09-05 -- eight shrines placed and instantiated in one map, and
#: no icon was ever seen, so nobody went looking.
#:
#: The parent ships NO detection radius at all. Exactly two shipped entities
#: override it, and both do it with a plain float at the tail of the record:
#: `Ruin_Model` 25.0, `Collectible_Ingredient_Key` 20.0. So the record is the
#: knob, and the literal is what :func:`set_f32` rewrites.
#:
#: `Main POI Flag` is a GPN custom flag the parent exposes (`Main POI`), set by
#: the landmarks you can see on the chapter map -- the beanstalk, Mordred's
#: entrance, the Roc cave. `Bean_Stalk` is the donor because that is ALL it
#: overrides besides priority, so nothing else comes with it.
REVEAL_DONORS: dict[str, tuple[str, str, float | None]] = {
    "radius": ("Objects_Common\\Ruin_Model.entity.ot",
               "Hero Presence Detection Radius", 25.0),
    "main_poi": ("DarkHills\\Jack\\Bean_Stalk.entity.ot",
                 "Main POI Flag", None),
}


def set_f32(record: bytes, old: float, new: float) -> bytes:
    """Rewrite the single f32 equal to `old` in `record`.

    Used to retune a donor's literal on the way in -- a reveal radius copied
    off a shipped ruin is that ruin's radius, not the one this POI wants.

    Fails closed on anything but exactly one match: zero means the donor's
    layout is not what was measured, and several means the edit would be a
    guess about which one matters.
    """
    hits = [o for o in range(0, len(record) - 3)
            if abs(struct.unpack_from("<f", record, o)[0] - old) < 1e-4]
    if len(hits) != 1:
        raise EntityComponentError(
            f"expected exactly one f32 == {old} in the record, found "
            f"{len(hits)} — the donor's layout is not what was measured")
    o = hits[0]
    return record[:o] + struct.pack("<f", new) + record[o + 4:]


#: Records to leave behind, per override donor. The donor is a real object with
#: a job of its own; only the part that is generic to the parent transfers.
#:
#: `Outline`/`Label` drop the cauldron's silhouette and its "Cauldron" caption,
#: so the parent's own defaults apply and the mod's icon arrives unlabelled
#: rather than mislabelled. `Ingredient` drops the two records that route the
#: interaction into `oCDtEntityCpntIngredientGainSettings`, which is the
#: donor's actual payload -- copy those and interacting hands out a cooking
#: ingredient.
OVERRIDE_EXCLUDE: dict[str, tuple[str, ...]] = {
    "minimap": ("Outline", "Label"),
    "interaction": ("Ingredient",),
}


def _parent_list_span(payload: bytes) -> tuple[int, int, list[tuple[str, str]]]:
    """Locate the parent-reference list inside an entity-settings record.

    Layout, from the record's nested BEGIN:

        u32 class index
        u32 child_count, child_count * u32   -- the component directory
        u8  flag
        u32 16, 16 bytes                     -- the entity's instance GUID
        u32 parent_count                     <-- the span starts here
        parent_count * { u32 len, root, u32 len, path }
        <12 or 16 bytes>  END

    Returns ``(start, end, entries)``; ``payload[start:end]`` is exactly what
    :func:`_render_parents` reproduces. Verified on the whole shipped corpus:
    4699 of 4699 entity files re-emit byte-identical through this walk.
    """
    i = payload.find(cooked.MARK_BEGIN)
    if i < 0:
        raise EntityComponentError("entity record has no nested BEGIN")
    o = i + 4 + 4                                   # BEGIN, class index
    (nchild,) = struct.unpack_from("<I", payload, o)
    o += 4 + 4 * nchild + 1                         # child list, flag byte
    (glen,) = struct.unpack_from("<I", payload, o)
    if glen != 16:
        raise EntityComponentError(
            f"expected a 16-byte instance GUID, found a {glen}-byte field — "
            f"the component directory was not walked correctly")
    o += 4 + glen

    start = o
    (count,) = struct.unpack_from("<I", payload, o)
    o += 4
    entries: list[tuple[str, str]] = []
    try:
        for _ in range(count):
            (a,) = struct.unpack_from("<I", payload, o)
            o += 4
            root = payload[o:o + a].decode("utf-8")
            o += a
            (b,) = struct.unpack_from("<I", payload, o)
            o += 4
            path = payload[o:o + b].decode("utf-8")
            o += b
            entries.append((root, path))
    except (struct.error, UnicodeDecodeError) as e:
        raise EntityComponentError(f"parent list is not walkable: {e}") from e

    if len(payload) - o not in _TAIL_SIZES or payload[-4:] != cooked.MARK_END:
        raise EntityComponentError(
            f"parent list ends {len(payload) - o} bytes before the record end, "
            f"which is not one of {_TAIL_SIZES} — refusing to edit a record "
            f"this walk does not understand")
    return start, o, entries


def _render_parents(entries: list[tuple[str, str]]) -> bytes:
    out = struct.pack("<I", len(entries))
    for root, path in entries:
        r, p = root.encode("utf-8"), path.encode("utf-8")
        out += struct.pack("<I", len(r)) + r + struct.pack("<I", len(p)) + p
    return out


def parents(host_bytes: bytes) -> list[str]:
    """Entity references `host_bytes` inherits from, in order."""
    cf = cooked.parse(host_bytes)
    _s, _e, entries = _parent_list_span(cf.sections[-1].payload)
    return [path for _root, path in entries]


def add_parents(host_bytes: bytes, names: list[str]) -> bytes:
    """Return `host_bytes` inheriting the entity behind each name in `names`.

    Appending a parent is how a shipped entity gains a minimap marker or an
    interaction prompt. Splicing the *component* instead does not work and the
    reason is worth keeping: `oCDtEntityCpntInteractionSettings` is a settings
    OVERRIDE whose every field is a named binding into another entity's
    namespace (``[State] Interactive_Object_Model\\Interaction\\State
    Interaction In Progress`` and eleven more). On a host with no such parent
    those bind to nothing, so the component loads, does nothing, and does not
    complain — measured in-game 2026-09-05: the pillar rendered, carried a
    byte-perfect marker and interaction record, and had neither an icon nor a
    prompt. The behaviour lives in a 74-component sub-graph that only
    inheritance brings along.
    """
    refs = [resolve_parent(n) for n in names]

    cf = cooked.parse(host_bytes)
    payload = cf.sections[-1].payload
    start, end, entries = _parent_list_span(payload)
    have = {path for _root, path in entries}
    added = False
    for ref in refs:
        if ref in have:
            # Already inherited. A duplicate parent would apply the whole
            # sub-graph twice, which is worse than a no-op.
            continue
        entries.append((_PARENT_ROOT, ref))
        have.add(ref)
        added = True
    if not added:
        return host_bytes

    cf.sections[-1].payload = payload[:start] + _render_parents(entries) + payload[end:]
    out = cooked.emit(cf)
    # Re-walk what we just wrote: the only cheap proof the edit stayed framed.
    _parent_list_span(cooked.parse(out).sections[-1].payload)
    return out


def resolve_parent(name: str) -> str:
    """The entity reference `name` selects.

    A curated key from :data:`PARENTS`, or a literal entity reference. The
    literal form is the escape hatch: the curated map only holds parents proven
    to do something, and an author (or an experiment) that needs one we have not
    named should not be blocked on this file being edited. It still has to name
    a real cooked entity — the caller reads it out of the corpus and fails if
    it does not exist.
    """
    if name in PARENTS:
        return PARENTS[name]
    if "\\" in name and name.lower().endswith(".entity.ot"):
        return name
    raise EntityComponentError(
        f"unknown component {name!r}; known: {sorted(PARENTS)} — or give a "
        f"literal entity reference like "
        f"'Interactive_Common\\Interactive_Object_Model.entity.ot'")


def parent_cooked_paths(names: list[str]) -> list[str]:
    """Decoded cooked paths of the parents `names` selects.

    An inherited parent is a resource the host now depends on, so it has to be
    in the preload cache of anything that places the host — a reference the
    cache never listed resolves to null and the engine's cleanup destroys it
    unchecked. Callers union these into the tile and map caches.
    """
    from .prop_cook import entity_cooked_path

    return [entity_cooked_path(resolve_parent(n)) for n in names]


def class_closure(record: bytes, donor_cf: cooked.CookedFile) -> set[str]:
    """Every donor class the record's tags name.

    Extending the host with only the component's OWN class is not enough and
    fails loudly: the marker record also names ``oCEntityGameUiSpawner``,
    ``oCCustomFlagFilter``, ``oCCustomFlagList``, ``oCEntityCpntPicker``,
    ``oCEntityCpntValuePicker`` and ``oCEntityValueUnion``, and a missing one
    aborts `_remap_class_tags` with "class ... absent from host after extend".

    The record's leading directory u32 and every post-``BEGIN`` u32 are indices
    into the DONOR's class table (the same fact `_remap_class_tags` rewrites).
    """
    out: set[str] = set()

    def name_of(idx: int) -> str | None:
        if 0 <= idx < len(donor_cf.classes):
            return donor_cf.classes[idx].name
        return None

    if len(record) >= 4:
        n = name_of(struct.unpack_from("<I", record, 0)[0])
        if n:
            out.add(n)
    i = 0
    while True:
        i = record.find(cooked.MARK_BEGIN, i)
        if i < 0 or i + 8 > len(record):
            break
        n = name_of(struct.unpack_from("<I", record, i + 4)[0])
        if n:
            out.add(n)
        i += 4
    return out


def _donor_records(donor_cf: cooked.CookedFile, cls: str) -> list[bytes]:
    """Every top-level component record of class `cls` in `donor_cf`.

    Plural on purpose. All 12 marker-bearing entities carry TWO
    `oCDtEntityCpntMinimapMarkerSettings` records -- "Minimap Big Marker" for
    the map screen and "Minimap Small Marker" for the HUD minimap -- so copying
    the first one alone lights at most half the UI.
    """
    idx = MM._class_index_of(donor_cf, cls)
    if idx is None:
        return []
    out = []
    for sec in donor_cf.sections[1:-1]:
        if len(sec.payload) >= 4 and struct.unpack_from("<I", sec.payload, 0)[0] == idx:
            out.append(sec.payload)
    return out


def copy_components(host_bytes: bytes, donor_bytes: bytes, cls: str, *,
                    string_swaps: dict[str, str] | None = None) -> bytes:
    """Append every `cls` component of `donor_bytes` to `host_bytes`.

    Unlike :func:`add_components` this takes the donor as bytes and copies ALL
    matching records, and it can rewrite strings inside them on the way in --
    which is how a marker gets custom art: the record names both the UI entity
    that draws it and the `.png` it draws, so swapping that path re-points the
    icon without touching the donor.

    Splicing is only half a working marker. The behaviour needs machinery the
    host does not have, which is what :func:`add_parents` supplies -- measured
    2026-09-05, a marker record spliced onto a bare scenery entity does
    nothing. Use both.
    """
    donor_cf = cooked.parse(donor_bytes)
    records = _donor_records(donor_cf, cls)
    if not records:
        raise EntityComponentError(
            f"donor carries no top-level {cls} record — it is referenced from "
            f"inside another component, so there is nothing to copy")

    return _splice(host_bytes, donor_cf, records, string_swaps)


def _splice(host_bytes: bytes, donor_cf, records: list[bytes],
            string_swaps: dict[str, str] | None) -> bytes:
    """Append `records` (donor-indexed) to `host_bytes`, one at a time.

    Each append re-parses, because every record extends the host's class table
    and shifts the indices the next one has to be remapped against.
    """
    out = host_bytes
    for record in records:
        host_cf = cooked.parse(out)
        EA.validate_layout(host_cf)
        MM.extend_class_table(host_cf, donor_cf, class_closure(record, donor_cf))
        remapped = MM._remap_class_tags(record, donor_cf, host_cf)
        if string_swaps:
            # Per record, and only the keys this one actually carries: a donor
            # spreads its icons over several records (big here, small there)
            # and `replace_blob_strings` refuses a key it cannot find.
            here = {k: v for k, v in string_swaps.items() if k.encode() in remapped}
            if here:
                remapped = EA.replace_blob_strings(remapped, here)
        remapped = EA.remint_guid(remapped)
        out = EA.append_components(cooked.emit(host_cf), [remapped])
        EA.validate_layout(cooked.parse(out))
    return out


def _record_strings(payload: bytes) -> list[str]:
    return [text for _off, text in ES._scan_payload(payload)]


def copy_overrides(host_bytes: bytes, donor_bytes: bytes, prefix: str, *,
                   string_swaps: dict[str, str] | None = None,
                   exclude: tuple[str, ...] = (),
                   only: tuple[str, ...] = (),
                   f32_swap: tuple[float, float] | None = None) -> bytes:
    """Copy the donor records that OVERRIDE a parent's components.

    An override record is recognised by its FIRST string being a binding path
    into another entity's namespace -- ``[Value] Minimap_Marker_Reveal_Model\\
    Hero Presence MiniMap Marker Model\\Minimap Big Marker Texture Value``.
    `prefix` is matched inside that path, so it selects one parent's overrides
    and leaves the donor's own components (and its overrides of OTHER parents,
    of which a shipped child usually has several) behind.

    This is the half :func:`add_parents` does not supply. Inheritance brings the
    machinery; the settings it reads still have to be authored on the host, and
    on a marker the icon IS a setting -- the parent ships an empty texture Value
    and draws nothing until a child fills it in.

    `exclude` drops any record naming one of those substrings anywhere, which is
    how a donor's own job (the cauldron's caption, the ingredient it hands out)
    stays with the donor. See :data:`OVERRIDE_EXCLUDE`.
    """
    donor_cf = cooked.parse(donor_bytes)
    # Targets the host already overrides. Two donors can bind the same field
    # (every marker child sets `Minimap Marker Priority Value`), and appending
    # a second override of one field is a coin flip over which the engine reads.
    have = {s[0] for s in (_record_strings(sec.payload)
                           for sec in cooked.parse(host_bytes).sections[1:-1])
            if s and s[0].startswith("[")}
    records = []
    for sec in donor_cf.sections[1:-1]:
        if len(sec.payload) < 4:
            continue
        strings = _record_strings(sec.payload)
        if not strings or not strings[0].startswith("[") or prefix not in strings[0]:
            continue
        if only and not any(strings[0].endswith(o) for o in only):
            continue
        if strings[0] in have:
            continue
        if any(bad in text for bad in exclude for text in strings):
            continue
        records.append(sec.payload)
    if not records:
        raise EntityComponentError(
            f"donor carries no override records binding into {prefix!r} — "
            f"either it does not inherit that parent or it configures it "
            f"through a selector rather than a literal")
    if f32_swap:
        records = [set_f32(r, *f32_swap) for r in records]
    return _splice(host_bytes, donor_cf, records, string_swaps)


def resource_refs(entity_bytes: bytes) -> list[str]:
    """Every ``.entity.ot`` and ``.png`` this entity names.

    An inherited parent drags its own resources in with it -- the reveal model
    alone names three UI entities and a primitive texture -- and a resource the
    placing tile's `UsedRscCache` never listed resolves to null, which the
    engine's teardown then destroys unchecked. Callers union these in beside
    :func:`parent_cooked_paths`.
    """
    out: list[str] = []
    for sec in cooked.parse(entity_bytes).sections[1:-1]:
        for _off, text in ES._scan_payload(sec.payload):
            low = text.lower()
            if (low.endswith(".entity.ot") or low.endswith(".png")) and text not in out:
                out.append(text)
    return out


def marker_refs(donor_bytes: bytes) -> tuple[list[str], list[str]]:
    """`(ui_entity_refs, picture_paths)` named by a donor's marker records.

    Both are resources the host will now reach, so both have to reach the
    preload caches; the picture is also the thing a mod overrides to get its
    own art onto the map.
    """
    donor_cf = cooked.parse(donor_bytes)
    uis: list[str] = []
    pics: list[str] = []
    for record in _donor_records(donor_cf, MARKER_CLASS):
        for _off, text in ES._scan_payload(record):
            low = text.lower()
            if low.endswith(".entity.ot") and text not in uis:
                uis.append(text)
            elif low.endswith(".png") and text not in pics:
                pics.append(text)
    return uis, pics


#: Component classes that GATE a marker: it stays hidden until they are
#: satisfied. Measured over three playtests (2026-09-05) — every entity with
#: one or more of these showed no icon; the two with none both showed.
GATE_CLASSES = ("StateSettings", "TesterSettings", "TestSettings")


def gate_count(entity_bytes: bytes) -> int:
    """How many gating components an entity carries.

    A marker on an entity with any of them waits for a quest step, a reveal
    event or a proximity test that a scenery prop never fires, and it simply
    never draws. Nothing logs. This is the check that keeps the measured result
    from having to be re-derived by playtest.
    """
    cf = cooked.parse(entity_bytes)
    n = 0
    for sec in cf.sections[1:-1]:
        if len(sec.payload) < 4:
            continue
        i = struct.unpack_from("<I", sec.payload, 0)[0]
        if 0 <= i < len(cf.classes):
            name = cf.classes[i].name
            if any(g in name for g in GATE_CLASSES):
                n += 1
    return n


def has_marker(entity_bytes: bytes) -> bool:
    """Does this entity already carry marker records of its own?"""
    return bool(_donor_records(cooked.parse(entity_bytes), MARKER_CLASS))


def _donor_record(donor_cf: cooked.CookedFile, cls: str, donor_ref: str) -> bytes:
    idx = MM._class_index_of(donor_cf, cls)
    if idx is None:
        raise EntityComponentError(
            f"{donor_ref} has no {cls} in its class table")
    for sec in donor_cf.sections[1:-1]:
        if len(sec.payload) >= 4 and struct.unpack_from("<I", sec.payload, 0)[0] == idx:
            return sec.payload
    raise EntityComponentError(
        f"{donor_ref} names {cls} but carries no top-level component record "
        f"for it — it is referenced from inside another component, not a "
        f"component of its own, so there is nothing to copy")


def add_components(host_bytes: bytes, names: list[str], *,
                   load_donor) -> bytes:
    """Return `host_bytes` with each named component appended.

    `load_donor(ref) -> bytes` reads a cooked entity from the corpus; injected
    so this module stays free of path/corpus policy.
    """
    unknown = [n for n in names if n not in DONORS]
    if unknown:
        raise EntityComponentError(
            f"unknown component(s) {unknown}; known: {sorted(DONORS)}")

    out = host_bytes
    for name in names:
        donor_ref, cls = DONORS[name]
        host_cf = cooked.parse(out)
        EA.validate_layout(host_cf)
        if MM._class_index_of(host_cf, cls) is not None:
            # Already present. Appending a second one would give the entity two
            # markers, which is a worse outcome than a no-op.
            continue
        donor_cf = cooked.parse(load_donor(donor_ref))
        record = _donor_record(donor_cf, cls, donor_ref)
        MM.extend_class_table(host_cf, donor_cf, class_closure(record, donor_cf))
        remapped = MM._remap_class_tags(record, donor_cf, host_cf)
        # Fresh instance GUID: the donor's identity must not be duplicated, or
        # the engine sees two components claiming to be the same one.
        remapped = EA.remint_guid(remapped)
        out = EA.append_components(cooked.emit(host_cf), [remapped])
        EA.validate_layout(cooked.parse(out))
    return out
