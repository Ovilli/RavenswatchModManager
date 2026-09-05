"""Adding components to a shipped entity, in place.

This is the capability that reopened the POI work: every note in the repo said
a mod could not give a prop a minimap marker or an interaction, because "an
in-place override cannot ADD a component". It can, and these tests pin the two
facts that make it work and the one that makes it fail loudly.

Corpus-dependent (data/uncooked is gitignored), so skipped where absent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rsmm.engine import cooked
from rsmm.engine import entity_append as EA
from rsmm.engine import entity_components as EC
from rsmm.engine import mods_modal as MM

HOST = "DarkHills\\SceneryObjects_DarkHills\\Menhir_Big_A.entity.ot"


def _load(ref: str) -> bytes:
    from rsmm.engine import prop_cook as PC
    from rsmm.sdk.kinds import poi as P
    return P._corpus(PC.entity_cooked_path(ref), "test", ref)


@pytest.fixture()
def host() -> bytes:
    try:
        return _load(HOST)
    except Exception:  # noqa: BLE001 - corpus absent is a skip, not a failure
        pytest.skip("uncooked corpus not present in this checkout")


@pytest.mark.parametrize("name", sorted(EC.DONORS))
def test_component_appends_and_round_trips(host, name):
    before = cooked.parse(host)
    n_before = EA.validate_layout(before)

    out = EC.add_components(host, [name], load_donor=_load)

    after = cooked.parse(out)
    assert EA.validate_layout(after) == n_before + 1
    # Byte-stable through the codec: a record the codec cannot re-emit is one
    # the engine will not read back either.
    assert cooked.emit(after) == out
    _ref, cls = EC.DONORS[name]
    assert MM._class_index_of(after, cls) is not None


def test_class_closure_covers_more_than_the_component_itself(host):
    """The trap that cost the first attempt.

    Extending the host with only the component's own class fails with
    "class 'oCEntityGameUiSpawner' absent from host after extend". The record
    names several helper classes and every one has to be copied over.
    """
    donor_ref, cls = EC.DONORS["minimap"]
    donor_cf = cooked.parse(_load(donor_ref))
    rec = EC._donor_record(donor_cf, cls, donor_ref)
    closure = EC.class_closure(rec, donor_cf)
    assert cls in closure
    assert len(closure) > 1, "a closure of one is the bug this guards"
    assert "oCEntityGameUiSpawner" in closure


def test_adding_twice_is_a_no_op(host):
    """Two markers on one entity is worse than none — the second call must not
    stack another copy."""
    once = EC.add_components(host, ["minimap"], load_donor=_load)
    twice = EC.add_components(once, ["minimap"], load_donor=_load)
    assert EA.validate_layout(cooked.parse(twice)) == \
        EA.validate_layout(cooked.parse(once))


def test_both_components_compose(host):
    out = EC.add_components(host, ["minimap", "interaction"], load_donor=_load)
    cf = cooked.parse(out)
    assert EA.validate_layout(cf) == EA.validate_layout(cooked.parse(host)) + 2
    for _ref, cls in EC.DONORS.values():
        assert MM._class_index_of(cf, cls) is not None


def test_unknown_component_is_refused(host):
    with pytest.raises(EC.EntityComponentError, match="unknown component"):
        EC.add_components(host, ["teleporter"], load_donor=_load)


def test_guid_is_reminted(host):
    """A copied record keeps the donor's instance GUID; two components claiming
    one identity is exactly the kind of fault that surfaces far from its cause."""
    donor_ref, cls = EC.DONORS["minimap"]
    donor_cf = cooked.parse(_load(donor_ref))
    rec = EC._donor_record(donor_cf, cls, donor_ref)
    out = EC.add_components(host, ["minimap"], load_donor=_load)
    assert rec not in out, "the donor record was appended verbatim, GUID and all"


# --- the `poi` kind's wiring ------------------------------------------------
#
# The engine splice above is only reachable through `poi.toml`'s `components`
# key, and that path has no other coverage: `discover` raises on any key it
# does not consume, so dropping the wiring turns the whole mod's content
# discovery into a warning and the POI silently stops emitting. That happened
# on 2026-09-05 and `rsmm apply` still exited 0.

def _poi_dir(tmp_path, body: str):
    from rsmm.sdk.kinds.poi import POIS_DIRNAME
    d = tmp_path / POIS_DIRNAME / "shrine"
    d.mkdir(parents=True)
    (d / "poi.toml").write_text(body, encoding="utf-8")
    return tmp_path


def test_parent_list_round_trips_across_the_whole_entity_corpus():
    """The walk must reproduce every shipped entity byte-for-byte.

    Editing the parent list means computing an offset into a record this repo
    has no schema for. The proof that the offset is right is that the same walk
    re-emits all 4699 shipped entity files unchanged — a wrong walk lands in
    the middle of a field and cannot.
    """
    import pytest

    from rsmm.engine import cooked
    from rsmm.engine import entity_components as EC
    from rsmm.engine.paths import REPO_ROOT

    corpus = REPO_ROOT / "data" / "uncooked" / "EntitySettings"
    if not corpus.is_dir():
        pytest.skip("uncooked corpus absent (run scripts/extract_uncooked.py)")

    ok = 0
    bad: list[str] = []
    for f in corpus.rglob("*.entity.ot.EntitySettingsResource.gen"):
        raw = f.read_bytes()
        try:
            cf = cooked.parse(raw)
        except ValueError:
            continue                    # container the codec cannot frame yet
        payload = cf.sections[-1].payload
        try:
            start, end, entries = EC._parent_list_span(payload)
        except EC.EntityComponentError as e:
            bad.append(f"{f.name}: {e}")
            continue
        if payload[start:end] != EC._render_parents(entries):
            bad.append(f"{f.name}: parent list does not re-render")
            continue
        cf.sections[-1].payload = (payload[:start]
                                   + EC._render_parents(entries)
                                   + payload[end:])
        if cooked.emit(cf) != raw:
            bad.append(f"{f.name}: file does not round-trip")
            continue
        ok += 1
    assert ok > 4000, f"corpus too small to be a proof: {ok}"
    assert not bad, f"{len(bad)} entity file(s) failed:\n  " + "\n  ".join(bad[:10])


def test_add_parents_appends_and_is_idempotent():
    from rsmm.engine import entity_components as EC

    host = _corpus_entity("DarkHills/SceneryObjects_DarkHills/"
                          "Menhir_Big_A.entity.ot.EntitySettingsResource.gen")
    assert EC.parents(host) == [], "premise: the donor inherits nothing"

    once = EC.add_parents(host, ["minimap", "interaction"])
    assert EC.parents(once) == [EC.PARENTS["minimap"], EC.PARENTS["interaction"]]
    # A duplicated parent would apply the whole sub-graph twice.
    assert EC.add_parents(once, ["minimap", "interaction"]) == once
    assert EC.add_parents(once, ["minimap"]) == once


def test_add_parents_refuses_an_unknown_name():
    import pytest

    from rsmm.engine import entity_components as EC

    host = _corpus_entity("DarkHills/SceneryObjects_DarkHills/"
                          "Menhir_Big_A.entity.ot.EntitySettingsResource.gen")
    with pytest.raises(EC.EntityComponentError, match="unknown component"):
        EC.add_parents(host, ["teleporter"])


def test_the_chest_is_the_reference_for_both_mappings():
    """`PARENTS` is copied off `Chest_Model`, which has a prompt and an icon
    in-game. If a game update reshapes that entity, the mapping is guesswork
    again and should be re-derived rather than trusted."""
    from rsmm.engine import entity_components as EC

    chest = _corpus_entity("Objects_Common/Chest_Model.entity.ot"
                           ".EntitySettingsResource.gen")
    inherited = EC.parents(chest)
    for name, ref in EC.PARENTS.items():
        assert ref in inherited, f"{name} -> {ref} is no longer a Chest_Model parent"


def _corpus_entity(rel: str) -> bytes:
    import pytest

    from rsmm.engine.paths import REPO_ROOT

    p = REPO_ROOT / "data" / "uncooked" / "EntitySettings" / rel
    if not p.is_file():
        pytest.skip(f"uncooked corpus absent: {rel}")
    return p.read_bytes()


def test_discover_carries_components_into_the_prop_block(tmp_path):
    from rsmm.sdk.kinds import poi as P

    root = _poi_dir(tmp_path, (
        'replace_base  = true\n'
        'base          = "Dark_Hills/64x64_Dark_Hills_Menhir_Cultist_Camp"\n'
        'chapters      = ["Dark_Hills"]\n'
        'replaces      = "DarkHills\\\\SceneryObjects_DarkHills\\\\Menhir_Big_A.entity.ot"\n'
        'entity_base   = "DarkHills\\\\SceneryObjects_DarkHills\\\\Menhir_Big_A.entity.ot"\n'
        'material_base = "Scenery\\\\DarkHills\\\\M_Menhirs_Moss.mat.ot"\n'
        'components    = ["minimap", "interaction"]\n'
    ))
    (block,) = P.discover(root)
    assert block["prop"]["components"] == ["minimap", "interaction"]


def test_discover_rejects_an_unknown_component(tmp_path):
    import pytest

    from rsmm.sdk.content import ContentError
    from rsmm.sdk.kinds import poi as P

    root = _poi_dir(tmp_path, (
        'replace_base  = true\n'
        'base          = "Dark_Hills/64x64_Dark_Hills_Menhir_Cultist_Camp"\n'
        'chapters      = ["Dark_Hills"]\n'
        'replaces      = "DarkHills\\\\SceneryObjects_DarkHills\\\\Menhir_Big_A.entity.ot"\n'
        'entity_base   = "DarkHills\\\\SceneryObjects_DarkHills\\\\Menhir_Big_A.entity.ot"\n'
        'material_base = "Scenery\\\\DarkHills\\\\M_Menhirs_Moss.mat.ot"\n'
        'components    = ["teleporter"]\n'
    ))
    with pytest.raises(ContentError, match="unknown component"):
        P.discover(root)


def test_copy_components_takes_both_marker_records_and_repaints_the_icon():
    """A marker is spliced (not inherited) because the RECORD carries the art.

    Two things this pins. All 12 marker-bearing entities ship TWO marker
    records — "Minimap Big Marker" for the map screen, "Minimap Small Marker"
    for the HUD — so copying one lights at most half the UI. And the record
    names the `.png` it draws, which is the only handle a mod has on the icon.
    """
    from rsmm.engine import entity_components as EC

    host = _corpus_entity("DarkHills/SceneryObjects_DarkHills/"
                          "Wall_Ruins_Block_Big_B.entity.ot"
                          ".EntitySettingsResource.gen")
    donor = _corpus_entity("Avalon/Objects_Tree_Quest/"
                           "Orchard_Minimap_Marker.entity.ot"
                           ".EntitySettingsResource.gen")

    uis, pics = EC.marker_refs(donor)
    assert len(uis) == 2, f"expected a Big and a Small marker UI, got {uis}"
    assert pics, "premise: this donor's markers name a picture to repaint"

    out = EC.copy_components(host, donor, EC.MARKER_CLASS,
                             string_swaps={pics[0]: "MiniMap\\Icons\\X.png"})
    assert EC._donor_records(_parse(out), EC.MARKER_CLASS).__len__() == 2
    assert b"MiniMap\\Icons\\X.png" in out
    assert pics[0].encode() not in out, "the donor's icon path survived the swap"


def test_copy_components_refuses_a_donor_without_the_class():
    import pytest

    from rsmm.engine import entity_components as EC

    host = _corpus_entity("DarkHills/SceneryObjects_DarkHills/"
                          "Menhir_Big_A.entity.ot.EntitySettingsResource.gen")
    with pytest.raises(EC.EntityComponentError, match="no top-level"):
        EC.copy_components(host, host, EC.MARKER_CLASS)


def test_ping_markers_carry_no_picture_to_repaint():
    """Why the marker donor and the machinery parent are different entities.

    The only two zero-gate marker entities are the pings, and their records
    name no `.png` at all — the art is baked into the UI entity they spawn. So
    inheriting one gives a working icon that is permanently the ping art, and
    the picture has to come from a donor of the other shape.
    """
    from rsmm.engine import entity_components as EC

    ping = _corpus_entity("GameUis/MinimapMarkers/"
                          "Minimap_Warning_Ping.entity.ot"
                          ".EntitySettingsResource.gen")
    uis, pics = EC.marker_refs(ping)
    assert uis and not pics, f"expected art baked into {uis}, found {pics}"


def _parse(data: bytes):
    from rsmm.engine import cooked

    return cooked.parse(data)


def test_gate_count_reproduces_the_measured_marker_results():
    """The one invariant three playtests bought.

    A marker draws iff the entity carrying it has no gating component. This is
    the check that stops the next author paying for that finding again, so it
    is pinned against the exact entities that produced it.
    """
    from rsmm.engine import entity_components as EC

    showed = ["GameUis/MinimapMarkers/Minimap_Warning_Ping",
              "GameUis/MinimapMarkers/Minimap_Ping"]
    hidden = ["Avalon/Objects_Avalon/Stairs_Location_Minimap_Marker",
              "Avalon/Objects_Tree_Quest/Orchard_Minimap_Marker",
              "Common_Settings/Minimap_Marker_Reveal_Model"]
    for rel in showed + hidden:
        raw = _corpus_entity(f"{rel}.entity.ot.EntitySettingsResource.gen")
        assert EC.has_marker(raw), f"{rel} should carry marker records"
        gates = EC.gate_count(raw)
        if rel in showed:
            assert gates == 0, f"{rel} drew an icon in-game but reads {gates} gates"
        else:
            assert gates > 0, f"{rel} drew NO icon in-game but reads 0 gates"


def test_two_defs_editing_one_tile_keep_both_their_cache_lines(tmp_path):
    """A shared base tile must not lose the first def's dependencies.

    `_emit_tile_caches` used to rebuild each cache from the CORPUS copy, so
    when two defs edit the same shipped tile the second silently discarded the
    first's lines. A resource a cache never lists resolves to null — either
    nothing renders or the engine faults at level build, nowhere near the
    cause. Hit 2026-09-05 on the menhir camp, which `runestone_shrine` and
    `shrine_marked` both edit.
    """
    import pytest

    from rsmm.engine import rsc_cache as RC
    from rsmm.sdk.content import ContentError, SchemaNotMined
    from rsmm.sdk.kinds import poi as P

    donor_rel = ("Definitions/Tiles/Dark_Hills/"
                 "64x64_Dark_Hills_Menhir_Cultist_Camp.tiledef"
                 ".ot.DtTileDefinition.gen")
    try:
        P._corpus(RC.cache_path_for(donor_rel), "t", "the donor cache")
    except (SchemaNotMined, ContentError, OSError):
        pytest.skip("uncooked corpus absent")

    base = "Dark_Hills/64x64_Dark_Hills_Menhir_Cultist_Camp"
    written: list = []
    # Two emits into the same out_dir, each contributing a different asset.
    P._emit_tile_caches(tmp_path, base, "first", ["Ui/AAA.png.Texture.dxt"],
                        [donor_rel], written)
    P._emit_tile_caches(tmp_path, base, "second", ["Ui/BBB.png.Texture.dxt"],
                        [donor_rel], written)

    text = (tmp_path / RC.cache_path_for(donor_rel)).read_text(errors="replace")
    assert "AAA.png" in text, "the first def's dependency was clobbered"
    assert "BBB.png" in text
    lines = text.splitlines()
    assert lines == sorted(lines), "cache must stay sorted or lookups miss"


def test_copy_overrides_takes_only_the_named_parent_and_repaints_the_icon():
    """The half `add_parents` does not supply.

    `Minimap_Marker_Reveal_Model` ships every texture Value empty, so a host
    that only inherits it draws nothing — three playtests measured that and
    blamed "gating components" on the parent. What fills it in is a handful of
    `oCEntityCpntValueSettings` records whose FIRST string is a binding path
    into the parent; `Leprechaun_Cauldron_Minimap_Marker` is made of nothing
    else, which is why it is the donor.
    """
    host = _corpus_entity("DarkHills/SceneryObjects_DarkHills/"
                          "Dolmen_A.entity.ot.EntitySettingsResource.gen")
    parent, donor_ref, prefix = EC.OVERRIDE_DONORS["minimap"]
    donor = _corpus_entity(donor_ref.replace("\\", "/")
                           .replace(".entity.ot",
                                    ".entity.ot.EntitySettingsResource.gen"))

    out = EC.add_parents(host, [parent])
    out = EC.copy_overrides(
        out, donor, prefix,
        string_swaps={p: "MiniMap\\Icons\\Map_Icons_Corpse.png"
                      for p in EC.resource_refs(donor)
                      if p.lower().endswith(".png")},
        exclude=EC.OVERRIDE_EXCLUDE["minimap"])

    assert parent in EC.parents(out)
    text = out.decode("latin-1")
    assert "Minimap Big Marker Texture Value" in text
    assert "Map_Icons_Corpse.png" in text
    # The donor's own job stays with the donor: its caption would render as
    # "Cauldron" on the mod's POI, and its outline is a cauldron silhouette.
    assert "Notification_Cauldron_Activity_Title" not in text
    assert "Cauldron_Outline" not in text
    # And nothing from the donor's OTHER bindings came along.
    assert "LEPRECHAUN_CAULDRON_DESTROYED" not in text
    cooked.parse(out)


def test_copy_overrides_interaction_leaves_the_donors_payload_behind():
    """`Ingredient_Stock_Model` is an interaction plus the ingredient it hands
    out. Copy the second half and the POI dispenses cooking ingredients."""
    host = _corpus_entity("DarkHills/SceneryObjects_DarkHills/"
                          "Dolmen_A.entity.ot.EntitySettingsResource.gen")
    parent, donor_ref, prefix = EC.OVERRIDE_DONORS["interaction"]
    donor = _corpus_entity(donor_ref.replace("\\", "/")
                           .replace(".entity.ot",
                                    ".entity.ot.EntitySettingsResource.gen"))

    out = EC.copy_overrides(EC.add_parents(host, [parent]), donor, prefix,
                            exclude=EC.OVERRIDE_EXCLUDE["interaction"])
    text = out.decode("latin-1")
    # This one record is what ARMS the interaction when the entity spawns.
    assert "Event Interaction Available At Start" in text
    assert "Ingredient" not in text
    cooked.parse(out)


def test_copy_overrides_refuses_a_donor_that_does_not_inherit_the_parent():
    host = _corpus_entity("DarkHills/SceneryObjects_DarkHills/"
                          "Dolmen_A.entity.ot.EntitySettingsResource.gen")
    with pytest.raises(EC.EntityComponentError):
        EC.copy_overrides(host, host, "Minimap_Marker_Reveal_Model\\")


def test_resource_refs_finds_the_parents_whole_closure():
    """A resource the placing tile's cache never lists resolves to null and the
    teardown loop destroys it unchecked — an access violation nowhere near the
    real mistake. The reveal model brings four of them along."""
    parent = _corpus_entity("Common_Settings/Minimap_Marker_Reveal_Model"
                            ".entity.ot.EntitySettingsResource.gen")
    refs = EC.resource_refs(parent)
    assert "GameUis\\MinimapMarkers\\Minimap_Marker_BigUi_Standard.entity.ot" in refs
    assert "Primitives\\DiamondFull.png" in refs


def test_a_clone_inherits_the_base_tiles_edited_cache(tmp_path):
    """A clone made without `own_level` SHARES the base tile's level.

    So whatever a `replace_base` def added to that level's dependencies — an
    inherited marker parent and its whole closure — is reached through the
    clone too. Seeding the clone from the pristine shipped cache lists none of
    it, and the crash lands on the tiles the mod ADDED rather than on the one it
    edited: a null in the preloaded vector, destroyed unchecked at 0x1401273b6.
    """
    from rsmm.engine import rsc_cache as RC
    from rsmm.sdk.content import ContentError, SchemaNotMined
    from rsmm.sdk.kinds import poi as P

    base = "Dark_Hills/64x64_Dark_Hills_Menhir_Cultist_Camp"
    base_rel = (f"Definitions/Tiles/{base}.tiledef.ot.DtTileDefinition.gen")
    try:
        P._corpus(RC.cache_path_for(base_rel), "t", "the donor cache")
    except (SchemaNotMined, ContentError, OSError):
        pytest.skip("uncooked corpus absent")

    clone_rel = ("Definitions/Tiles/Dark_Hills/"
                 "mod_clone.tiledef.ot.DtTileDefinition.gen")
    written: list = []
    # The `replace_base` def runs first — `discover` sorts to guarantee it.
    P._emit_tile_caches(tmp_path, base, "override",
                        ["EntitySettings/Common_Settings/Marker"
                         ".entity.ot.EntitySettingsResource.gen"],
                        [base_rel], written)
    P._emit_tile_caches(tmp_path, base, "clone", [], [clone_rel], written)

    text = (tmp_path / RC.cache_path_for(clone_rel)).read_text(errors="replace")
    assert "Common_Settings\\Marker.entity.ot" in text, (
        "the clone was seeded from the shipped cache and lost the base def's "
        "dependencies")


def test_discover_emits_replace_base_defs_first(tmp_path):
    """Which is what makes the seeding above deterministic."""
    from rsmm.sdk.kinds import poi as P

    root = tmp_path / "mod"
    for name, extra in (("z_clone", 'copies = 2\n'),
                        ("a_override", 'replace_base = true\n'
                         'replaces = "DarkHills\\\\SceneryObjects_DarkHills'
                         '\\\\Dolmen_A.entity.ot"\n'
                         'entity_base = "DarkHills\\\\SceneryObjects_DarkHills'
                         '\\\\Dolmen_A.entity.ot"\n'
                         'material_base = "Scenery\\\\DarkHills'
                         '\\\\M_Menhirs_Moss.mat.ot"\n'
                         'interactive = true\n')):
        d = root / "pois" / name
        d.mkdir(parents=True)
        (d / "poi.toml").write_text(
            'chapters = ["Dark_Hills"]\n'
            'base = "Dark_Hills/64x64_Dark_Hills_Menhir_Cultist_Camp"\n'
            + extra)

    ids = [b["id"] for b in P.discover(root)]
    assert ids.index("a_override") < ids.index("z_clone")


def test_a_borrowed_cache_sees_a_sibling_defs_edit(tmp_path):
    """`swaps` stands a shipped entity in a mod-owned level, and its closure is
    covered by borrowing the cache of a tile that already places it.

    That entity is routinely one the SAME mod edited — standing a re-skinned,
    map-marked prop in a tile of its own is the whole point — and the shipped
    cache of the tile it is borrowed from knows nothing about what that edit
    introduced. Borrowing the pristine copy loses it.

    The borrow is trimmed to what the swapped-in entity actually REACHES, so
    what has to survive is the edit's own new references — here an inherited
    parent, which is how a prop gains a marker. An unrelated line that happens
    to sit in the donor's cache is not inherited and should not be: that is the
    1344-line, foreign-biome bloat the trim exists to remove.
    """
    from rsmm.engine import rsc_cache as RC
    from rsmm.sdk.content import ContentError, SchemaNotMined
    from rsmm.sdk.kinds import poi as P

    dolmen = "DarkHills\\SceneryObjects_DarkHills\\Dolmen_A.entity.ot"
    host = "Dark_Hills/64x64_Dark_Hills_Menhir_Cultist_Camp"
    host_rel = f"Definitions/Tiles/{host}.tiledef.ot.DtTileDefinition.gen"
    other = "Dark_Hills/6x6_Healing_01"
    other_rel = f"Definitions/Tiles/{other}.tiledef.ot.DtTileDefinition.gen"
    try:
        P._corpus(RC.cache_path_for(host_rel), "t", "the donor cache")
        assert P._tile_cache_by_placed_entity().get(dolmen)
    except (SchemaNotMined, ContentError, OSError, AssertionError):
        pytest.skip("uncooked corpus absent, or Dolmen_A is no longer "
                    "placed by exactly one tile")

    from rsmm.engine import entity_components as EC
    from rsmm.engine.prop_cook import entity_cooked_path

    # The sibling def's edit: Dolmen_A gains the marker parent. Written where
    # the emitter writes, so the closure walk reads THIS and not the corpus.
    edited = EC.add_parents(P._corpus(entity_cooked_path(dolmen), "t",
                                      "the swapped-in entity"), ["minimap"])
    dest = tmp_path / Path(*entity_cooked_path(dolmen).split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(edited)

    written: list = []
    P._emit_tile_caches(tmp_path, host, "prop-edit", [], [host_rel], written)
    P._emit_tile_caches(tmp_path, other, "swapped-tile", [], [other_rel],
                        written, borrow_for=[dolmen])

    text = (tmp_path / RC.cache_path_for(other_rel)).read_text(errors="replace")
    assert "Minimap_Marker_Reveal_Model" in text, (
        "the borrow read the shipped entity and lost the parent the sibling "
        "def inherited onto it")
    assert "Minimap_Marker_BigUi_Standard" in text, (
        "the parent's own UI closure has to come with it — every shipped tile "
        "carrying a marker lists all eight MinimapMarkers entities")


def test_reveal_radius_is_retuned_on_the_way_in():
    """`Minimap_Marker_Reveal_Model` is a hero-PRESENCE marker: it reveals only
    once the hero is already close. For a shipped landmark that is right; for a
    mod POI it is circular, because the icon is how a player finds the thing.

    The parent ships no radius at all — exactly two shipped entities override
    it, with a plain float at the tail of the record (`Ruin_Model` 25.0). So the
    record is copied and the literal rewritten.
    """
    import struct

    from rsmm.engine import entity_strings as ES

    host = _corpus_entity("DarkHills/SceneryObjects_DarkHills/"
                          "Dolmen_A.entity.ot.EntitySettingsResource.gen")
    parent, _donor_ref, prefix = EC.OVERRIDE_DONORS["minimap"]
    d_ref, target, literal = EC.REVEAL_DONORS["radius"]
    donor = _corpus_entity(d_ref.replace("\\", "/")
                           .replace(".entity.ot",
                                    ".entity.ot.EntitySettingsResource.gen"))

    out = EC.copy_overrides(EC.add_parents(host, [parent]), donor, prefix,
                            only=(target,), f32_swap=(literal, 300.0))

    found = None
    for sec in cooked.parse(out).sections[1:-1]:
        if len(sec.payload) < 4:
            continue
        strings = [t for _o, t in ES._scan_payload(sec.payload)]
        if strings and target in strings[0]:
            found = {round(struct.unpack_from("<f", sec.payload, o)[0], 1)
                     for o in range(len(sec.payload) - 3)}
    assert found is not None, "the radius override was not copied"
    assert 300.0 in found, "the donor's literal was not retuned"
    assert literal not in found, "the donor's own radius survived the copy"


def test_an_override_target_is_never_written_twice():
    """Two donors can bind the same field — every marker child sets
    `Minimap Marker Priority Value`. Appending a second override of one field
    is a coin flip over which one the engine reads."""
    host = _corpus_entity("DarkHills/SceneryObjects_DarkHills/"
                          "Dolmen_A.entity.ot.EntitySettingsResource.gen")
    parent, donor_ref, prefix = EC.OVERRIDE_DONORS["minimap"]
    donor = _corpus_entity(donor_ref.replace("\\", "/")
                           .replace(".entity.ot",
                                    ".entity.ot.EntitySettingsResource.gen"))
    out = EC.copy_overrides(EC.add_parents(host, [parent]), donor, prefix,
                            exclude=EC.OVERRIDE_EXCLUDE["minimap"])
    # Same donor twice: every target is already present, so nothing may be added.
    with pytest.raises(EC.EntityComponentError):
        EC.copy_overrides(out, donor, prefix,
                          exclude=EC.OVERRIDE_EXCLUDE["minimap"])
