"""Tile / map-pool codecs and the `poi` content kind.

The corpus-wide round-trip tests are the load-bearing ones: a POI mod edits
defs the engine reads at map generation, so a codec that drops or reorders a
field does not fail loudly — it produces a map that generates wrong.
"""

from __future__ import annotations

import glob

import pytest

from rsmm.engine import map_pool as MP
from rsmm.engine import tile_cook as TC
from rsmm.engine.paths import DATA_DIR
from rsmm.sdk.content import ContentDef, ContentError, SchemaNotMined
from rsmm.sdk.kinds import poi

TILES_DIR = DATA_DIR / "uncooked" / "Definitions" / "Tiles"
MAPS_DIR = DATA_DIR / "uncooked" / "Definitions" / "Maps"

_tiles = sorted(glob.glob(str(TILES_DIR / "**" / ("*" + TC.GEN_SUFFIX)), recursive=True))
_maps = sorted(glob.glob(str(MAPS_DIR / ("*" + MP.GEN_SUFFIX))))

needs_corpus = pytest.mark.skipif(
    not _tiles or not _maps,
    reason="uncooked corpus absent (run scripts/extract_uncooked.py)",
)

BASE = "Avalon/40x40_Avalon_Cauldron_T1"


# --------------------------------------------------------------------------- #
# tile_cook
# --------------------------------------------------------------------------- #

@needs_corpus
@pytest.mark.slow
def test_every_shipped_tiledef_round_trips_byte_exact():
    bad = []
    for p in _tiles:
        raw = open(p, "rb").read()
        try:
            if TC.write(TC.read(raw)) != raw:
                bad.append((p, "byte mismatch"))
        except Exception as e:  # noqa: BLE001 — collect all failures, report once
            bad.append((p, repr(e)))
    assert not bad, f"{len(bad)}/{len(_tiles)} tiledefs failed: {bad[:5]}"


@needs_corpus
def test_tiledef_exposes_kinds_size_and_icon():
    td = TC.read((TILES_DIR / "Dark_Hills" / f"6x6_Teleporter_01{TC.GEN_SUFFIX}").read_bytes())
    assert td.kinds == ["Teleporter"]
    assert (td.width, td.height) == (6, 6)
    assert td.has_icon and td.icon[2].endswith(".png")
    # The NxN_ filename prefix is the footprint, which is what makes the
    # width/height read a fact rather than an inference.
    assert td.entity_ref[0] == "EntitySettings"


@needs_corpus
def test_tiledef_edits_survive_a_round_trip():
    raw = (TILES_DIR / "Avalon" / f"40x40_Avalon_Cauldron_T1{TC.GEN_SUFFIX}").read_bytes()
    td = TC.read(raw)
    td.weight = 0.5
    td.kinds = ["Wishing_Well"]
    td.icon = (td.icon[0], "Ui", "MiniMap\\Icons\\Map_Icons_Crow_Mark.png")
    back = TC.read(TC.write(td))
    assert back.weight == pytest.approx(0.5)
    assert back.kinds == ["Wishing_Well"]
    assert back.icon[2] == "MiniMap\\Icons\\Map_Icons_Crow_Mark.png"
    assert back.entity_ref == td.entity_ref


def test_tiledef_rejects_unexpected_shape():
    # A tail whose kind block has the wrong prelude must raise, not guess.
    bad = bytes.fromhex("1111bbaa") + (99).to_bytes(4, "little") + b"\x00" * 32
    with pytest.raises(TC.TileCookError):
        TC.parse_tail(bad)


# --------------------------------------------------------------------------- #
# map_pool
# --------------------------------------------------------------------------- #

@needs_corpus
def test_every_shipped_mapdef_pool_round_trips_byte_exact():
    seen_pools = 0
    for p in _maps:
        raw = open(p, "rb").read()
        pool = MP.read_pool(raw)
        if pool is None:
            continue  # Baba Yaga: scripted arena, no tile generation
        seen_pools += 1
        assert MP.set_pool(raw, pool) == raw, f"{p} identity round-trip changed bytes"
    assert seen_pools == 3, f"expected 3 tile-generated maps, saw {seen_pools}"


@needs_corpus
def test_baba_yaga_has_no_pool():
    p = MAPS_DIR / f"Baba_Yaga_Map_Update3{MP.GEN_SUFFIX}"
    assert MP.read_pool(p.read_bytes()) is None
    with pytest.raises(MP.MapPoolError):
        MP.add_to_pool(p.read_bytes(), ["Tiles\\X\\Y.tiledef.ot"])


@needs_corpus
def test_add_to_pool_is_additive_and_dedupes():
    raw = (MAPS_DIR / f"Dark_Hills_LiveOps_Update5{MP.GEN_SUFFIX}").read_bytes()
    before = MP.read_pool(raw)
    dup = before[0]
    after = MP.read_pool(MP.add_to_pool(raw, [dup, "Tiles\\Mod\\New.tiledef.ot"]))
    assert after[: len(before)] == before, "vanilla entries must keep their order"
    assert after[len(before):] == ["Tiles\\Mod\\New.tiledef.ot"]


@needs_corpus
def test_retail_dark_hills_pool_references_a_storm_island_tile():
    """Cross-biome pooling is a vanilla pattern, not something rsmm invented."""
    raw = (MAPS_DIR / f"Dark_Hills_LiveOps_Update5{MP.GEN_SUFFIX}").read_bytes()
    pool = MP.read_pool(raw)
    assert any("Storm_Island" in p for p in pool)


# --------------------------------------------------------------------------- #
# poi kind
# --------------------------------------------------------------------------- #

@needs_corpus
def test_emit_writes_clone_plus_one_mapdef_per_chapter(tmp_path):
    defn = ContentDef(kind="poi", id="Cauldron", fields={
        "base": BASE, "chapters": ["Dark_Hills", "Storm_Island"], "weight": 0.4,
    })
    files = poi.emit("mymod", defn, tmp_path)
    rel = sorted(f.relative_to(tmp_path).as_posix() for f in files)
    assert rel == [
        "Definitions/Maps/Dark_Hills_LiveOps_Update5.mapdef.ot.DtMapDefinition.gen",
        "Definitions/Maps/Storm_Island_LiveOps_Update5.mapdef.ot.DtMapDefinition.gen",
        "Definitions/Tiles/Avalon/mymod_Cauldron.tiledef.ot.DtTileDefinition.gen",
    ]
    tile = tmp_path / rel[2]
    td = TC.read(tile.read_bytes())
    assert td.weight == pytest.approx(0.4)
    # The clone keeps the donor's prefab — that is what makes it a real structure.
    assert "Cauldron" in td.entity_ref[1]

    for stem in ("Dark_Hills_LiveOps_Update5", "Storm_Island_LiveOps_Update5"):
        pooled = MP.read_pool((tmp_path / f"Definitions/Maps/{stem}{MP.GEN_SUFFIX}").read_bytes())
        assert pooled[-1] == "Tiles\\Avalon\\mymod_Cauldron.tiledef.ot"


@needs_corpus
def test_clone_lands_in_the_donors_biome_dir_so_apply_can_resolve_it(tmp_path):
    """`synthesize_encoded` needs a same-directory sibling to derive the encoded
    path for a new asset. A fresh `Definitions/Tiles/<Mod>/` has none, so the
    tile would be silently skipped at apply — hence filing next to the donor."""
    from rsmm.cli.apply_mods import load_asset_map, synthesize_encoded

    defn = ContentDef(kind="poi", id="Cauldron", fields={
        "base": BASE, "chapters": ["Dark_Hills"],
    })
    files = poi.emit("mymod", defn, tmp_path)
    tile = next(f for f in files if f.name.endswith(TC.GEN_SUFFIX))
    decoded = tile.relative_to(tmp_path).as_posix()
    assert decoded.startswith("Definitions/Tiles/Avalon/")

    dec2enc = load_asset_map()
    assert synthesize_encoded(decoded, dec2enc) is not None


@needs_corpus
def test_several_pois_in_one_mod_all_reach_the_same_chapter(tmp_path):
    """Each def is emitted independently into one out_dir, so rebuilding the
    mapdef from vanilla every time made the last def win and silently drop the
    earlier ones' tiles — the mod looked fine and shipped one POI of three."""
    for pid, base in (("A", BASE),
                      ("B", "Avalon/6x6_Healing_01"),
                      ("C", "Storm_Island/40x40_Giant_Ruin_Crystal_Field")):
        poi.emit("m", ContentDef(kind="poi", id=pid, fields={
            "base": base, "chapters": ["Dark_Hills"]}), tmp_path)

    vanilla = MP.read_pool(
        (MAPS_DIR / f"Dark_Hills_LiveOps_Update5{MP.GEN_SUFFIX}").read_bytes())
    pool = MP.read_pool(
        (tmp_path / f"Definitions/Maps/Dark_Hills_LiveOps_Update5{MP.GEN_SUFFIX}").read_bytes())
    assert pool[: len(vanilla)] == vanilla
    assert [p.rsplit("\\", 1)[-1] for p in pool[len(vanilla):]] == [
        "m_A.tiledef.ot", "m_B.tiledef.ot", "m_C.tiledef.ot",
    ]


@needs_corpus
def test_emit_does_not_mutate_the_tracked_corpus(tmp_path):
    src = MAPS_DIR / f"Dark_Hills_LiveOps_Update5{MP.GEN_SUFFIX}"
    before = src.read_bytes()
    poi.emit("m", ContentDef(kind="poi", id="X", fields={
        "base": BASE, "chapters": ["Dark_Hills"]}), tmp_path)
    assert src.read_bytes() == before


@needs_corpus
@pytest.mark.parametrize("fields,exc,needle", [
    ({"chapters": ["Avalon"]}, ContentError, "base"),
    ({"base": "Avalon/Nope", "chapters": ["Avalon"]}, SchemaNotMined, "not found"),
    ({"base": BASE}, ContentError, "chapters"),
    ({"base": BASE, "chapters": ["Baba_Yaga"]}, ContentError, "boss arena"),
    ({"base": BASE, "chapters": ["Avalon"], "weight": 5}, ContentError, "out of range"),
    ({"base": BASE, "chapters": ["Dark_Hills"], "kinds": ["Nope"]},
     ContentError, "never be placed"),
    # JackQuest is Dark-Hills-only; Avalon can never place it.
    ({"base": BASE, "chapters": ["Avalon"], "kinds": ["JackQuest"]},
     ContentError, "never be placed"),
])
def test_emit_rejects_bad_defs(tmp_path, fields, exc, needle):
    with pytest.raises(exc, match=needle):
        poi.emit("m", ContentDef(kind="poi", id="X", fields=fields), tmp_path)


@needs_corpus
def test_chapter_kinds_are_nonempty_and_chapter_specific():
    """The validation vocabulary must be per-chapter, or the `kinds` check is
    meaningless: most kinds are shared (42 in all three maps), but each chapter
    keeps its own quest/boss kinds that no other map can place."""
    dh = poi.chapter_kinds("Dark_Hills")
    av = poi.chapter_kinds("Avalon")
    si = poi.chapter_kinds("Storm_Island")
    assert {"Altar_Of_Heroes", "Teleporter"} <= (dh & av & si), "shared kinds"
    assert "JackQuest" in dh and "JackQuest" not in av, "Dark-Hills-only kind"
    assert "Mordred" in av and "Mordred" not in dh, "Avalon-only kind"
    assert "Roc_Quest" in si and "Roc_Quest" not in dh, "Storm-Island-only kind"


@needs_corpus
def test_two_poi_mods_on_one_chapter_both_survive_the_merge(tmp_path):
    """Without the mapdef merge in apply, the second mod's override replaces the
    first and its POI is registered but never pooled — invisible in-game."""
    outs = []
    for mod, base, pid in (("modA", BASE, "Cauldron"),
                           ("modB", "Storm_Island/6x6_Teleporter_01", "Portal")):
        d = tmp_path / mod
        d.mkdir()
        poi.emit(mod, ContentDef(kind="poi", id=pid, fields={
            "base": base, "chapters": ["Dark_Hills"]}), d)
        outs.append(d / f"Definitions/Maps/Dark_Hills_LiveOps_Update5{MP.GEN_SUFFIX}")

    vanilla = (MAPS_DIR / f"Dark_Hills_LiveOps_Update5{MP.GEN_SUFFIX}").read_bytes()
    base_pool = MP.read_pool(vanilla)
    merged, have = list(base_pool), set(base_pool)
    for o in outs:
        for p in MP.read_pool(o.read_bytes()):
            if p not in have:
                merged.append(p)
                have.add(p)
    assert len(merged) == len(base_pool) + 2
    final = MP.read_pool(MP.set_pool(vanilla, merged))
    assert final[-2:] == ["Tiles\\Avalon\\modA_Cauldron.tiledef.ot",
                          "Tiles\\Storm_Island\\modB_Portal.tiledef.ot"]


def test_is_map_def_matches_only_mapdefs():
    from rsmm.cli.apply_mods import is_map_def
    assert is_map_def("Definitions/Maps/X.mapdef.ot.DtMapDefinition.gen")
    assert not is_map_def("Definitions/Tiles/Avalon/X.tiledef.ot.DtTileDefinition.gen")
    assert not is_map_def("Text/Common~GAM.xls.LocalText.gen")


# --------------------------------------------------------------------------- #
# prop_cook — the custom-art chain
# --------------------------------------------------------------------------- #

MAT_DONOR = "3D/Scenery/DarkHills/M_Walls_Ruins.mat.ot.Material.gen"
ENT_DONOR = ("EntitySettings/DarkHills/SceneryObjects_DarkHills/"
             "Wall_Ruins_Block_Small_A.entity.ot.EntitySettingsResource.gen")
LVL_DONOR = "Ot/DarkHills/Tiles/6x6_Bleeding_01.level.ot.GameStream.gen"
UNCOOKED = DATA_DIR / "uncooked"

needs_prop_corpus = pytest.mark.skipif(
    not (UNCOOKED / MAT_DONOR).is_file() or not (UNCOOKED / LVL_DONOR).is_file(),
    reason="uncooked corpus absent",
)


def test_art_cooked_path_maps_each_family():
    from rsmm.engine import prop_cook as PC
    assert PC.art_cooked_path("Scenery\\D\\T_X.tga") == "3D/Scenery/D/T_X.tga.Texture.dxt"
    assert PC.art_cooked_path("Scenery\\D\\X.fbx") == "3D/Scenery/D/X.fbx.Geometry.gen"
    assert PC.art_cooked_path("Scenery\\D\\M_X.mat.ot") == "3D/Scenery/D/M_X.mat.ot.Material.gen"
    with pytest.raises(PC.PropCookError):
        PC.art_cooked_path("Scenery\\D\\X.wav")


@needs_prop_corpus
def test_clone_material_repoints_only_named_textures():
    from rsmm.engine import prop_cook as PC
    raw = (UNCOOKED / MAT_DONOR).read_bytes()
    out = PC.clone_material(raw, {
        "Scenery\\DarkHills\\T_Walls_Ruins_ALB.tga": "Scenery\\DarkHills\\T_Mine_ALB.tga"})
    import json

    from rsmm.engine import cooked_schemas
    doc = json.loads(cooked_schemas.get("oCMaterial").decode_cooked(out))
    assert "Scenery\\DarkHills\\T_Mine_ALB.tga" in doc["asset_refs"]
    # The shader ref and the untouched maps must survive.
    assert "Dt_Textured_WorldSpaceDirt.px.ot" in doc["asset_refs"]
    assert "Scenery\\DarkHills\\T_Walls_Ruins_MRA.tga" in doc["asset_refs"]


@needs_prop_corpus
def test_clone_material_rejects_a_texture_the_donor_never_used():
    """A typo'd slot would otherwise ship a material still on the donor's art —
    which in-game looks like the custom texture silently not applying."""
    from rsmm.engine import prop_cook as PC
    with pytest.raises(PC.PropCookError, match="no reference"):
        PC.clone_material((UNCOOKED / MAT_DONOR).read_bytes(),
                          {"Scenery\\Nope\\T_Ghost.tga": "x"})


@needs_prop_corpus
def test_clone_prop_entity_repoints_every_lod_mesh():
    from rsmm.engine import entity_strings as ES
    from rsmm.engine import prop_cook as PC
    raw = (UNCOOKED / ENT_DONOR).read_bytes()
    meshes = {s for _a, _b, s in ES.list_strings(raw) if s.lower().endswith(".fbx")}
    assert len(meshes) >= 2, "donor should have a LOD chain to exercise"
    out = PC.clone_prop_entity(raw, {m: "Scenery\\DarkHills\\Mine.fbx" for m in meshes})
    after = {s for _a, _b, s in ES.list_strings(out) if s.lower().endswith(".fbx")}
    assert after == {"Scenery\\DarkHills\\Mine.fbx"}, \
        "a LOD left pointing at the donor pops back to the wall block at range"


@needs_prop_corpus
def test_clone_tile_level_renames_both_self_forms_and_swaps_the_object():
    import json

    from rsmm.engine import cooked_schemas
    from rsmm.engine import prop_cook as PC
    raw = (UNCOOKED / LVL_DONOR).read_bytes()
    old = "DarkHills\\Tiles\\6x6_Bleeding_01.level.ot"
    new = "DarkHills\\Tiles\\Mine.level.ot"
    out = PC.clone_tile_level(raw, old, new, {
        "DarkHills\\Objects_DarkHills\\Blood_Fountain_DarkHills.entity.ot":
            "DarkHills\\SceneryObjects_DarkHills\\Mine_Prop.entity.ot"})
    refs = json.loads(cooked_schemas.get("oCGameStream").decode_cooked(out))["asset_refs"]
    assert refs[0] == new
    # The bare identifier form must move too or the clone collides in the registry.
    assert "DarkHills\\Tiles\\Mine" in refs
    assert not any("6x6_Bleeding_01" in r for r in refs)
    assert "DarkHills\\SceneryObjects_DarkHills\\Mine_Prop.entity.ot" in refs
    # Everything else the tile dresses itself with is untouched.
    assert sum(1 for r in refs if "Grass" in r) > 0


@needs_prop_corpus
def test_clone_tile_level_rejects_an_object_the_tile_does_not_place():
    from rsmm.engine import prop_cook as PC
    with pytest.raises(PC.PropCookError, match="places no object"):
        PC.clone_tile_level((UNCOOKED / LVL_DONOR).read_bytes(),
                            "DarkHills\\Tiles\\6x6_Bleeding_01.level.ot",
                            "DarkHills\\Tiles\\Mine.level.ot",
                            {"Nope\\Ghost.entity.ot": "x"})


@needs_corpus
def test_prop_poi_requires_the_mod_to_ship_its_source_art(tmp_path):
    """The chain assembles fine with a dangling model ref; the failure only
    shows up in-game as an invisible structure. Catch it at emit."""
    defn = ContentDef(kind="poi", id="Ghost", fields={
        "base": "Dark_Hills/6x6_Bleeding_01", "chapters": ["Dark_Hills"],
        "prop": {
            "replaces": "DarkHills\\Objects_DarkHills\\Blood_Fountain_DarkHills.entity.ot",
            "entity_base":
                "DarkHills\\SceneryObjects_DarkHills\\Wall_Ruins_Block_Small_A.entity.ot",
            "material_base": "Scenery\\DarkHills\\M_Walls_Ruins.mat.ot",
            "model": "art/not_shipped.glb",
            "textures": {
                "Scenery\\DarkHills\\T_Walls_Ruins_ALB.tga": "art/nope.png"},
        }})
    with pytest.raises(ContentError, match="is not in this mod"):
        poi.emit("m", defn, tmp_path / "assets")


@needs_corpus
def test_prop_poi_cooks_the_mods_own_glb_and_pngs(tmp_path):
    """End to end on the source workflow: a mod ships a plain .glb and .png,
    and apply produces cooked engine assets carrying the MOD's geometry — not
    the donor's. The donor supplies only the graft template."""
    from rsmm.engine import cooked as CK
    from rsmm.engine import geometry_cook as GC
    from rsmm.engine import gltf
    from rsmm.engine import image as IMG
    from rsmm.engine.cooked_schemas import geometry as G

    art = tmp_path / "art"
    art.mkdir()
    # A 4-vertex tetrahedron: nothing like the 90-vert donor, so the vertex
    # count alone proves whose mesh survived.
    P = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
    b = gltf.GlbBuilder()
    pi = b.add_positions(P)
    ni = b.add_vec3([(0, 1, 0)] * 4)
    ui = b.add_vec2([(0, 0)] * 4)
    ii = b.add_indices([0, 1, 2, 0, 1, 3, 0, 2, 3, 1, 2, 3])
    m = b.add_mesh(gltf.Mesh(name="t", primitives=[gltf.Primitive(
        attributes={"POSITION": pi, "NORMAL": ni, "TEXCOORD_0": ui}, indices=ii)]))
    b.add_node(gltf.Node(name="t", mesh=m), is_root=True)
    (art / "mine.glb").write_bytes(b.build_glb())
    (art / "mine.png").write_bytes(IMG.encode_png(4, 4, bytes([200, 30, 30, 255] * 16)))

    defn = ContentDef(kind="poi", id="Tetra", fields={
        "base": "Dark_Hills/6x6_Bleeding_01", "chapters": ["Dark_Hills"],
        "kinds": ["Fountain"],
        "prop": {
            "replaces": "DarkHills\\Objects_DarkHills\\Blood_Fountain_DarkHills.entity.ot",
            "entity_base":
                "DarkHills\\SceneryObjects_DarkHills\\Wall_Ruins_Block_Small_A.entity.ot",
            "material_base": "Scenery\\DarkHills\\M_Walls_Ruins.mat.ot",
            "model": "art/mine.glb",
            "textures": {
                "Scenery\\DarkHills\\T_Walls_Ruins_ALB.tga": "art/mine.png"},
        }})
    files = poi.emit("mymod", defn, tmp_path / "assets")
    rel = {f.name for f in files}
    assert any(n.endswith(".Geometry.gen") for n in rel)
    assert any(n.endswith(".Texture.dxt") for n in rel)
    assert any(n.endswith(".Material.gen") for n in rel)
    assert any(n.endswith(".GameStream.gen") for n in rel)

    geo = next(f for f in files if f.name.endswith(".Geometry.gen"))
    subs = None
    for sec in CK.parse(geo.read_bytes()).sections:
        try:
            s = G._parse_meshbuffers(sec.payload)
        except Exception:  # noqa: BLE001 — not the meshbuffer section
            continue
        if s:
            subs = s
            break
    assert subs is not None
    donor_verts = sum(len(s.positions) for s in GC.glb_to_submeshes(
        (DATA_DIR / "uncooked/3D/Scenery/DarkHills"
         / "Wall_Ruins_Block_Small_A.fbx.glb").read_bytes()))
    assert sum(len(s.positions) for s in subs) == 4 != donor_verts

    # The raw .glb/.png must NOT land under assets/ — they are sources, and
    # copying them into the game install would ship uncooked bytes as overrides.
    assert not any(f.suffix in (".glb", ".png") for f in files)
