"""Tile / map-pool codecs and the `poi` content kind.

The corpus-wide round-trip tests are the load-bearing ones: a POI mod edits
defs the engine reads at map generation, so a codec that drops or reorders a
field does not fail loudly — it produces a map that generates wrong.
"""

from __future__ import annotations

import glob
from pathlib import Path

import pytest

from rsmm.engine import entity_strings
from rsmm.engine import map_pool as MP
from rsmm.engine import prop_cook as PC
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
        "Definitions/Maps/Dark_Hills_LiveOps_Update5.mapdef.UsedRscCache.ot",
        "Definitions/Maps/Dark_Hills_LiveOps_Update5.mapdef.ot.DtMapDefinition.gen",
        "Definitions/Maps/Storm_Island_LiveOps_Update5.mapdef.UsedRscCache.ot",
        "Definitions/Maps/Storm_Island_LiveOps_Update5.mapdef.ot.DtMapDefinition.gen",
        "Definitions/Tiles/Avalon/mymod_Cauldron.tiledef.UsedRscCache.ot",
        "Definitions/Tiles/Avalon/mymod_Cauldron.tiledef.ot.DtTileDefinition.gen",
    ]
    tile = tmp_path / rel[5]
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


# --------------------------------------------------------------------------- #
# UsedRscCache — the preload manifest without which a tile is never placed
# --------------------------------------------------------------------------- #

def _poi_art(art: Path) -> None:
    """A mod's own source art: a 4-vertex mesh and a 4x4 texture."""
    from rsmm.engine import gltf
    from rsmm.engine import image as IMG

    art.mkdir(parents=True, exist_ok=True)
    b = gltf.GlbBuilder()
    pi = b.add_positions([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)])
    ni = b.add_vec3([(0, 1, 0)] * 4)
    ui = b.add_vec2([(0, 0)] * 4)
    ii = b.add_indices([0, 1, 2, 0, 1, 3, 0, 2, 3, 1, 2, 3])
    m = b.add_mesh(gltf.Mesh(name="t", primitives=[gltf.Primitive(
        attributes={"POSITION": pi, "NORMAL": ni, "TEXCOORD_0": ui}, indices=ii)]))
    b.add_node(gltf.Node(name="t", mesh=m), is_root=True)
    (art / "mine.glb").write_bytes(b.build_glb())
    (art / "mine.png").write_bytes(
        IMG.encode_png(4, 4, bytes([200, 30, 30, 255] * 16)))


_PROP = {
    "replaces": "DarkHills\\Objects_DarkHills\\Blood_Fountain_DarkHills.entity.ot",
    "entity_base":
        "DarkHills\\SceneryObjects_DarkHills\\Wall_Ruins_Block_Small_A.entity.ot",
    "material_base": "Scenery\\DarkHills\\M_Walls_Ruins.mat.ot",
    "model": "art/mine.glb",
    "textures": {"Scenery\\DarkHills\\T_Walls_Ruins_ALB.tga": "art/mine.png"},
}

#: Override mode needs a different donor than additive mode, and the difference
#: is not cosmetic. `_PROP` names the blood fountain, which is fine to swap OUT
#: of a cloned level (additive) and wrong to override IN PLACE: it is a
#: composite that spawns eleven children, so the override would land on its
#: stone base and the model would render inside the fountain. This donor draws
#: one mesh and spawns nothing.
_OVERRIDE_BASE = "Dark_Hills/DarkHill_Thieves_Stashes_Magic_Mirror_Underground_01"
_OVERRIDE_PROP = {
    "replaces":
        "DarkHills\\SceneryObjects_DarkHills\\Thieve_Blood_Fountain.entity.ot",
    "entity_base":
        "DarkHills\\SceneryObjects_DarkHills\\Thieve_Blood_Fountain.entity.ot",
    "material_base":
        "Scenery\\DarkHills\\Blood_Fountain\\M_Blood_Foutain_DH_Thieve.mat.ot",
    "model": "art/mine.glb",
    "textures": {"Scenery\\DarkHills\\Blood_Fountain\\T_Blood_Fountain_DH_ALB.tga":
                 "art/mine.png"},
}


def test_cache_path_and_entry_match_the_shipped_grammar():
    from rsmm.engine import rsc_cache as RC

    assert RC.cache_path_for(
        "Definitions/Tiles/Dark_Hills/X.tiledef.ot.DtTileDefinition.gen"
    ) == "Definitions/Tiles/Dark_Hills/X.tiledef.UsedRscCache.ot"
    assert RC.entry_for("3D/Scenery/DarkHills/M_x.mat.ot.Material.gen") == (
        "3D|Scenery\\DarkHills\\M_x.mat.ot|oCMaterial")
    assert RC.entry_for("Ui/MiniMap/Icons/x.png.Texture.dxt") == (
        "Ui|MiniMap\\Icons\\x.png|oCTexture")
    with pytest.raises(RC.CacheError):
        RC.entry_for("3D/Scenery/DarkHills/x.unknown.suffix")


@needs_corpus
@pytest.mark.slow
def test_every_shipped_tiledef_has_a_cache_that_reparses():
    """237/237 — the invariant the whole feature rests on. If a game patch
    ever ships a tiledef without one, this is where we find out."""
    from rsmm.engine import rsc_cache as RC

    missing, bad = [], []
    for p in _tiles:
        rel = Path(p).relative_to(DATA_DIR / "uncooked").as_posix()
        cache = DATA_DIR / "uncooked" / RC.cache_path_for(rel)
        if not cache.is_file():
            missing.append(rel)
            continue
        lines = RC.parse(cache.read_bytes())
        if not lines or any(ln.count("|") != 2 for ln in lines):
            bad.append(rel)
    assert not missing, f"{len(missing)}/{len(_tiles)} tiledefs have no cache: {missing[:5]}"
    assert not bad, f"malformed caches: {bad[:5]}"


@needs_corpus
def test_emitted_tile_cache_lists_every_asset_the_tile_reaches(tmp_path):
    """The 2026-08-10 regression: a POI shipped a prop chain the tile's cache
    never mentioned. The engine preloads only what the cache lists, so the
    level's reference resolved to null and the teardown loop destroyed it."""
    from rsmm.engine import rsc_cache as RC

    _poi_art(tmp_path / "art")
    defn = ContentDef(kind="poi", id="Tetra", fields={
        "base": "Dark_Hills/6x6_Bleeding_01", "chapters": ["Dark_Hills"],
        "kinds": ["Fountain"], "prop": dict(_PROP)})
    out = tmp_path / "assets"
    files = poi.emit("mymod", defn, out)

    caches = [f for f in files if f.name.endswith(RC.CACHE_SUFFIX)
              and "/Tiles/" in f.as_posix()]
    assert len(caches) == 1
    listed = set(RC.parse(caches[0].read_bytes()))

    # Every cooked asset this def emitted must be preloadable, including the
    # tiledef itself. Mapdefs belong to the chapter, not the tile.
    for f in files:
        rel = f.relative_to(out).as_posix()
        if rel.endswith(RC.CACHE_SUFFIX) or rel.startswith("Definitions/Maps/"):
            continue
        assert RC.entry_for(rel) in listed, f"{rel} is not preloaded by the tile cache"

    # And it is still the donor's closure underneath, not a bare 6-line file.
    donor = (DATA_DIR / "uncooked" / RC.cache_path_for(
        f"Definitions/Tiles/Dark_Hills/6x6_Bleeding_01{TC.GEN_SUFFIX}")).read_bytes()
    assert set(RC.parse(donor)) <= listed


@needs_corpus
def test_shipped_map_caches_list_their_whole_pool():
    """The invariant the emitter has to preserve: a chapter preloads exactly its
    pool. 77 entries, 77 `oCDtTileDefinition` lines, no slack."""
    from rsmm.engine import rsc_cache as RC

    for stem in poi.CHAPTERS.values():
        pool = MP.read_pool((MAPS_DIR / f"{stem}{MP.GEN_SUFFIX}").read_bytes())
        cache = MAPS_DIR / RC.cache_path_for(f"x/{stem}{MP.GEN_SUFFIX}").rsplit("/", 1)[-1]
        listed = {ln.split("|")[1] for ln in RC.parse(cache.read_bytes())
                  if ln.endswith("|oCDtTileDefinition")}
        assert set(pool) == listed, f"{stem}: pool and map cache disagree"


@needs_corpus
@pytest.mark.slow
def test_shipped_map_cache_is_a_superset_of_every_tile_it_pools():
    """Measured on the shipped data: the Dark Hills start tile's 784 cache
    lines all appear in the chapter's 5636. That is what makes a chapter's
    cache the thing to extend whenever a tile reaches new art — including in
    `replace_base`, where no tile is pooled at all."""
    from rsmm.engine import rsc_cache as RC

    for chapter, stem in poi.CHAPTERS.items():
        mapc = set(RC.parse((MAPS_DIR / f"{stem}.mapdef{RC.CACHE_SUFFIX}").read_bytes()))
        pool = MP.read_pool((MAPS_DIR / f"{stem}{MP.GEN_SUFFIX}").read_bytes())
        for ref in pool:
            parts = ref.replace("\\", "/").split("/")
            stem_name = parts[-1].removesuffix(".tiledef.ot")
            tc = TILES_DIR / parts[-2] / f"{stem_name}.tiledef{RC.CACHE_SUFFIX}"
            if not tc.is_file():
                continue
            extra = set(RC.parse(tc.read_bytes())) - mapc
            assert not extra, f"{chapter}: {tc.name} has {len(extra)} lines the map cache lacks"


@needs_corpus
def test_replace_base_still_extends_the_chapter_cache(tmp_path):
    """No tile is pooled in override mode, but the overridden tile now reaches
    the mod's art — and the chapter preloads a superset of its tiles, so that
    art has to be listed there too."""
    from rsmm.engine import rsc_cache as RC

    _poi_art(tmp_path / "art")
    out = tmp_path / "assets"
    files = poi.emit("mymod", ContentDef(kind="poi", id="Over", fields={
        "base": _OVERRIDE_BASE, "chapters": ["Dark_Hills"],
        "replace_base": True, "prop": dict(_OVERRIDE_PROP)}), out)

    stem = poi.CHAPTERS["Dark_Hills"]
    mapc = set(RC.parse((out / f"Definitions/Maps/{stem}.mapdef{RC.CACHE_SUFFIX}").read_bytes()))
    tile_rel = f"Definitions/Tiles/{_OVERRIDE_BASE}.tiledef{RC.CACHE_SUFFIX}"
    tilec = set(RC.parse((out / tile_rel).read_bytes()))
    assert tilec <= mapc, "chapter cache must stay a superset of the tile's"
    # The overridden art is written on a SHIPPED path, which both caches
    # already list — the superset invariant is what this guards, not a new line.
    mesh = next(f for f in files if f.name.endswith(".Geometry.gen"))
    assert RC.entry_for(mesh.relative_to(out).as_posix()) in mapc


@needs_corpus
def test_swaps_redresses_a_tile_with_zero_new_assets(tmp_path):
    """`swaps` puts a different SHIPPED prop at an object's transform. Its
    whole point is that nothing is cooked, registered or cached — the only
    bytes that change are object references inside one level."""
    from rsmm.engine import prop_cook as PC

    files = poi.emit("m", ContentDef(kind="poi", id="Trees", fields={
        "base": "Dark_Hills/40x40_Dark_Hills_Start_Update3",
        "chapters": ["Dark_Hills"], "replace_base": True,
        "swaps": {
            "DarkHills\\SceneryObjects_DarkHills\\Wall_Ruins_Block_Small_A.entity.ot":
                "Enemies\\RavensTree\\RavensTree.entity.ot"},
    }), tmp_path)

    rel = sorted(f.relative_to(tmp_path).as_posix() for f in files)
    assert rel == [
        "Definitions/Maps/Dark_Hills_LiveOps_Update5.mapdef.UsedRscCache.ot",
        "Definitions/Tiles/Dark_Hills/40x40_Dark_Hills_Start_Update3.tiledef.UsedRscCache.ot",
        "Ot/DarkHills/Tiles/40x40_DarkHills_Starting_Tile_Update3.level.ot.GameStream.gen",
    ]
    lvl = next(f for f in files if f.name.endswith(".GameStream.gen")).read_bytes()
    assert b"Wall_Ruins_Block_Small_A.entity.ot" not in lvl
    assert lvl.count(b"RavensTree.entity.ot") >= 22 + 8

    vanilla = (DATA_DIR / "uncooked" / PC.level_cooked_path(
        "DarkHills\\Tiles\\40x40_DarkHills_Starting_Tile_Update3.level.ot")).read_bytes()
    assert PC.level_guid(lvl) == PC.level_guid(vanilla)


@needs_corpus
def test_swaps_rejects_a_target_the_tile_never_preloads(tmp_path):
    """The guard that makes the whole cache bug class unreachable here: a tile
    only loads what its cache lists, and this SDK cannot compute an arbitrary
    vanilla entity's closure."""
    with pytest.raises(ContentError, match="resource cache"):
        poi.emit("m", ContentDef(kind="poi", id="Bad", fields={
            "base": "Dark_Hills/40x40_Dark_Hills_Start_Update3",
            "chapters": ["Dark_Hills"], "replace_base": True,
            "swaps": {
                "DarkHills\\SceneryObjects_DarkHills\\Wall_Ruins_Block_Small_A.entity.ot":
                    "Avalon\\SceneryObjects_Avalon\\Round_Table.entity.ot"},
        }), tmp_path)


def test_swaps_requires_replace_base(tmp_path):
    with pytest.raises(ContentError, match="replace_base"):
        poi.emit("m", ContentDef(kind="poi", id="Bad", fields={
            "base": BASE, "chapters": ["Dark_Hills"],
            "swaps": {"a.entity.ot": "b.entity.ot"},
        }), tmp_path)


@needs_corpus
def test_pool_additions_are_mirrored_into_the_map_cache(tmp_path):
    """A tile appended to the pool but missing from the chapter's own cache is
    never loaded, so it is never placed — the gate that survived the per-tile
    cache fix and hid the POI for one more playtest."""
    from rsmm.engine import rsc_cache as RC

    files = poi.emit("m", ContentDef(kind="poi", id="C", fields={
        "base": BASE, "chapters": ["Dark_Hills"], "copies": 3}), tmp_path)
    stem = poi.CHAPTERS["Dark_Hills"]
    pool = MP.read_pool((tmp_path / f"Definitions/Maps/{stem}{MP.GEN_SUFFIX}").read_bytes())
    cache = next(f for f in files
                 if f.name == f"{stem}.mapdef{RC.CACHE_SUFFIX}")
    listed = {ln.split("|")[1] for ln in RC.parse(cache.read_bytes())
              if ln.endswith("|oCDtTileDefinition")}
    assert set(pool) == listed
    assert sum("m_C" in p for p in pool) == 3


@needs_corpus
def test_two_poi_mods_both_survive_the_map_cache_merge(tmp_path, monkeypatch):
    """Same destructive shape as the pool merge: dropping a mod's preload lines
    makes its POI pooled-but-unloadable rather than visibly conflicting."""
    # The merge writes its output under MODS_DIR; never let that be the real one.
    monkeypatch.setenv("RSMM_MODS_DIR", str(tmp_path / "mods"))
    from rsmm.cli.apply_mods import _merge_rsc_cache
    from rsmm.engine import rsc_cache as RC

    stem = poi.CHAPTERS["Dark_Hills"]
    vanilla = MAPS_DIR / f"{stem}.mapdef{RC.CACHE_SUFFIX}"
    srcs = []
    for mod in ("aaa", "zzz"):
        out = tmp_path / mod
        poi.emit(mod, ContentDef(kind="poi", id="P", fields={
            "base": BASE, "chapters": ["Dark_Hills"]}), out)
        srcs.append(out / f"Definitions/Maps/{stem}.mapdef{RC.CACHE_SUFFIX}")

    merged = _merge_rsc_cache("enc\\x", srcs, vanilla)
    lines = set(RC.parse(merged.read_bytes()))
    assert set(RC.parse(vanilla.read_bytes())) <= lines
    for mod in ("aaa", "zzz"):
        assert f"Definitions|Tiles\\Avalon\\{mod}_P.tiledef.ot|oCDtTileDefinition" in lines


@needs_corpus
def test_every_copy_gets_its_own_cache_naming_its_own_tiledef(tmp_path):
    from rsmm.engine import rsc_cache as RC

    files = poi.emit("m", ContentDef(kind="poi", id="C", fields={
        "base": BASE, "chapters": ["Dark_Hills"], "copies": 3}), tmp_path)
    caches = sorted(f for f in files if f.name.endswith(RC.CACHE_SUFFIX)
                    and "/Tiles/" in f.as_posix())
    assert len(caches) == 3
    for c in caches:
        stem = c.name[: -len(RC.CACHE_SUFFIX)]
        assert RC.entry_for(
            f"Definitions/Tiles/Avalon/{stem}.ot.DtTileDefinition.gen"
        ) in set(RC.parse(c.read_bytes()))


@needs_corpus
def test_replace_base_overrides_the_shipped_cache_not_a_new_one(tmp_path):
    """Override mode edits the shipped tile in place, so its cache must be
    overridden at the SHIPPED path — writing a new one leaves the stale
    original in charge and the tile still can't reach the new prop."""
    from rsmm.engine import rsc_cache as RC

    _poi_art(tmp_path / "art")
    defn = ContentDef(kind="poi", id="Over", fields={
        "base": _OVERRIDE_BASE, "chapters": ["Dark_Hills"],
        "replace_base": True, "prop": dict(_OVERRIDE_PROP)})
    out = tmp_path / "assets"
    files = poi.emit("mymod", defn, out)
    caches = [f.relative_to(out).as_posix()
              for f in files if f.name.endswith(RC.CACHE_SUFFIX)]
    tile_cache = f"Definitions/Tiles/{_OVERRIDE_BASE}.tiledef{RC.CACHE_SUFFIX}"
    assert sorted(caches) == [
        "Definitions/Maps/Dark_Hills_LiveOps_Update5.mapdef.UsedRscCache.ot",
        tile_cache,
    ]

    listed = set(RC.parse((out / tile_cache).read_bytes()))
    mesh = next(f for f in files if f.name.endswith(".Geometry.gen"))
    assert RC.entry_for(mesh.relative_to(out).as_posix()) in listed


def test_apply_does_not_register_a_cache_in_usedrsclist(tmp_path):
    """Caches are convention-loaded; none of the 575 shipped ones has a
    UsedRscList record, so appending one would clone a 3-line group from a
    sibling that isn't in the manifest either."""
    from rsmm.cli import apply_mods

    src = tmp_path / "x"
    src.write_bytes(b"")

    class _M:
        id, enabled = "m", True

        def files(self):
            return [
                (src, "Definitions/Tiles/Dark_Hills/New.tiledef.UsedRscCache.ot"),
                (src, "Definitions/Tiles/Dark_Hills/New.tiledef.ot.DtTileDefinition.gen"),
            ]

    dec2enc = apply_mods.load_asset_map()
    _adds, _rms, regs = apply_mods.plan_apply(
        [_M()], dec2enc, tmp_path, tmp_path, apply_mods.State(tmp_path), True)
    decoded = set(regs.values())
    assert "Definitions/Tiles/Dark_Hills/New.tiledef.ot.DtTileDefinition.gen" in decoded
    assert not any(d.endswith(".UsedRscCache.ot") for d in decoded)


# --------------------------------------------------------------------------- #
# Convention discovery — a POI is a folder, not a wall of manifest keys
# --------------------------------------------------------------------------- #

def _poi_folder(root, name="my_shrine", cfg='chapters = ["Dark_Hills"]\n',
                with_art=True):
    from rsmm.engine import gltf
    from rsmm.engine import image as IMG
    d = root / poi.POIS_DIRNAME / name
    d.mkdir(parents=True)
    (d / "poi.toml").write_text(cfg)
    if with_art:
        b = gltf.GlbBuilder()
        pi = b.add_positions([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)])
        ni = b.add_vec3([(0, 1, 0)] * 4)
        ui = b.add_vec2([(0, 0)] * 4)
        ii = b.add_indices([0, 1, 2, 0, 1, 3, 0, 2, 3, 1, 2, 3])
        m = b.add_mesh(gltf.Mesh(name="t", primitives=[gltf.Primitive(
            attributes={"POSITION": pi, "NORMAL": ni, "TEXCOORD_0": ui}, indices=ii)]))
        b.add_node(gltf.Node(name="t", mesh=m), is_root=True)
        (d / "model.glb").write_bytes(b.build_glb())
        px = bytes([200, 30, 30, 255] * 16)
        for role in ("albedo", "mra", "normal"):
            (d / f"{role}.png").write_bytes(IMG.encode_png(4, 4, px))
    return d


def test_discover_returns_nothing_without_a_pois_dir(tmp_path):
    assert poi.discover(tmp_path) == []


def test_discover_fills_everything_from_the_preset(tmp_path):
    """The point of the folder convention: six lines of config, no engine paths."""
    _poi_folder(tmp_path)
    blocks = poi.discover(tmp_path)
    assert len(blocks) == 1
    b = blocks[0]
    assert b["kind"] == "poi" and b["id"] == "my_shrine"
    preset = poi.PRESETS[poi.DEFAULT_PRESET]
    assert b["base"] == preset["base"]
    assert b["kinds"] == preset["kinds"]
    assert b["weight"] == preset["weight"]
    # Art is wired by filename convention through the preset's slot map.
    assert b["prop"]["model"] == "pois/my_shrine/model.glb"
    assert set(b["prop"]["textures"].values()) == {
        "pois/my_shrine/albedo.png", "pois/my_shrine/mra.png",
        "pois/my_shrine/normal.png"}
    assert set(b["prop"]["textures"]) == set(preset["slots"].values())
    assert b["prop"]["entity_base"] == preset["entity_base"]


def test_discover_lets_poi_toml_override_the_preset(tmp_path):
    _poi_folder(tmp_path, cfg='chapters = ["Avalon"]\nweight = 0.5\n'
                              'kinds = ["Camp"]\nid = "renamed"\n')
    b = poi.discover(tmp_path)[0]
    assert (b["id"], b["weight"], b["kinds"], b["chapters"]) == (
        "renamed", 0.5, ["Camp"], ["Avalon"])


def test_discover_a_poi_with_no_art_is_a_plain_tile_clone(tmp_path):
    _poi_folder(tmp_path, with_art=False)
    b = poi.discover(tmp_path)[0]
    assert "prop" not in b, "no model means clone the shipped prefab"


def test_discover_is_deterministic(tmp_path):
    for n in ("zeta", "alpha", "mid"):
        _poi_folder(tmp_path, name=n, with_art=False)
    assert [b["id"] for b in poi.discover(tmp_path)] == ["alpha", "mid", "zeta"]


@pytest.mark.parametrize("cfg,needle", [
    ('chapters = ["Dark_Hills"]\npreset = "nope"\n', "unknown preset"),
    ('chapters = ["Dark_Hills"]\nwieght = 0.5\n', "unknown key"),
    ('weight = 0.5\n', "must set `chapters`"),
])
def test_discover_rejects_bad_poi_toml(tmp_path, cfg, needle):
    _poi_folder(tmp_path, cfg=cfg, with_art=False)
    with pytest.raises(ContentError, match=needle):
        poi.discover(tmp_path)


def test_a_model_with_no_textures_wears_the_donor_material(tmp_path):
    """Shipping a shape but no maps is a real choice, not a mistake: the prop
    keeps `material_base`. It is also the only configuration that exercises the
    geometry cook WITHOUT the texture and material cooks, which is what makes
    it usable as a bisect."""
    d = _poi_folder(tmp_path)
    for role in ("albedo", "mra", "normal"):
        (d / f"{role}.png").unlink()
    block = poi.discover(tmp_path)[0]
    assert block["prop"]["textures"] == {}
    assert block["prop"]["model"].endswith("model.glb")


@needs_corpus
def test_prop_without_textures_cooks_no_material_or_texture(tmp_path):
    _poi_art(tmp_path / "art")
    out = tmp_path / "assets"
    prop = dict(_PROP)
    prop.pop("textures")
    files = poi.emit("mymod", ContentDef(kind="poi", id="Shape", fields={
        "base": "Dark_Hills/6x6_Bleeding_01", "chapters": ["Dark_Hills"],
        "kinds": ["Fountain"], "prop": prop}), out)

    names = {f.name for f in files}
    assert any(n.endswith(".Geometry.gen") for n in names), "the mesh is still ours"
    assert not any(n.endswith(".Material.gen") for n in names)
    assert not any(n.endswith(".Texture.dxt") for n in names)

    # The prop entity must point at the DONOR material, untouched.
    from rsmm.engine import entity_strings as ES
    ent = next(f for f in files if f.name.endswith(".EntitySettingsResource.gen"))
    refs = {s for _a, _b, s in ES.list_strings(ent.read_bytes())}
    assert "Scenery\\DarkHills\\M_Walls_Ruins.mat.ot" in refs


@needs_corpus
def test_every_preset_is_wired_to_real_donors():
    """A preset is a promise to every mod that uses it, so a stale path breaks
    all of them at once. `replaces` in particular is not guessable from a tile's
    name — a "Giant_Ruin_Crystal_Field" tile places bone props, not a ruin —
    which is exactly how a made-up value shipped once."""
    import json

    from rsmm.engine import cooked_schemas
    from rsmm.engine import prop_cook as PC

    for name, preset in poi.PRESETS.items():
        assert poi._tile_path(preset["base"]).is_file(), f"{name}: bad base tile"
        for key in ("entity_base", "material_base"):
            rel = (PC.entity_cooked_path(preset[key]) if key.startswith("entity")
                   else PC.art_cooked_path(preset[key]))
            assert (DATA_DIR / "uncooked" / rel).is_file(), f"{name}: bad {key}"
        # A preset may deliberately carry NO slots: its donor's material is
        # shared with other props, so overriding the textures behind it would
        # re-skin them too, and the honest offer is "your geometry, the shipped
        # material". Only exactly one upright pooled prop in the corpus has a
        # material of its own, so this is the common case, not a gap. What a
        # preset may not do is offer a partial set of roles.
        assert set(preset["slots"]) in ({}.keys(), set(poi.TEXTURE_ROLES)), \
            f"{name}: slot roles"

        # Slots name textures of `replaces` ITSELF, because that is where the
        # mod's art is written — in place, on the shipped prop's own paths.
        # So they must be textures that prop's own material really uses.
        from rsmm.engine import entity_strings as ES
        ent = (DATA_DIR / "uncooked"
               / PC.entity_cooked_path(preset["replaces"])).read_bytes()
        mats = sorted({s for _s, _o, s in ES.list_strings(ent)
                       if s.lower().endswith(".mat.ot")})
        refs: set[str] = set()
        for m in mats:
            raw = (DATA_DIR / "uncooked" / PC.art_cooked_path(m)).read_bytes()
            refs |= set(json.loads(
                cooked_schemas.get("oCMaterial").decode_cooked(raw))["asset_refs"])
        assert set(preset["slots"].values()) <= refs, f"{name}: slot not in material"

        # And the base tile's level must really place the object to replace.
        lvl_ref = poi._level_ref_of(poi._prefab_ref_of(preset["base"], name), name)
        lvl = (DATA_DIR / "uncooked" / PC.level_cooked_path(lvl_ref)).read_bytes()
        placed = set(json.loads(
            cooked_schemas.get("oCGameStream").decode_cooked(lvl))["asset_refs"])
        assert preset["replaces"] in placed, (
            f"{name}: replaces {preset['replaces']!r} is not placed by {lvl_ref}")


@needs_corpus
def test_declared_manifest_block_wins_over_a_same_id_folder(tmp_path):
    """A hand-written block must stay authoritative, or an author cannot
    override what discovery guessed."""
    from rsmm.cli.apply_mods import Mod
    _poi_folder(tmp_path, name="dup", with_art=False)
    (tmp_path / "manifest.toml").write_text(
        '[mod]\nid = "m"\n\n[[content]]\nkind = "poi"\nid = "dup"\n'
        'base = "Avalon/6x6_Healing_01"\nchapters = ["Avalon"]\n')
    blocks = [b for b in Mod(tmp_path).content_blocks if b.get("id") == "dup"]
    assert len(blocks) == 1
    assert blocks[0]["base"] == "Avalon/6x6_Healing_01"


# --------------------------------------------------------------------------- #
# Custom minimap icon
# --------------------------------------------------------------------------- #

def test_ui_cooked_path_uses_the_ui_root_not_3d():
    """UI art cooks under `Ui/`, art under `3D/` — same texture class, different
    namespace, which is why one helper cannot serve both."""
    from rsmm.engine import prop_cook as PC
    assert PC.ui_cooked_path("MiniMap\\Icons\\X.png") == \
        "Ui/MiniMap/Icons/X.png.Texture.dxt"
    with pytest.raises(PC.PropCookError):
        PC.ui_cooked_path("MiniMap\\Icons\\X.glb")


def test_discover_picks_up_icon_png_and_drops_a_vanilla_icon_ref(tmp_path):
    d = _poi_folder(tmp_path, cfg='chapters = ["Dark_Hills"]\n'
                                  'icon = "MiniMap\\\\Icons\\\\Map_Icon_Key.png"\n',
                    with_art=False)
    from rsmm.engine import image as IMG
    (d / "icon.png").write_bytes(IMG.encode_png(2, 2, bytes([9, 9, 9, 255] * 4)))
    b = poi.discover(tmp_path)[0]
    assert b["icon_source"] == "pois/my_shrine/icon.png"
    assert "icon" not in b, "a shipped icon.png must win over a vanilla ref"


@needs_corpus
def test_emit_cooks_a_custom_icon_and_points_the_tiledef_at_it(tmp_path):
    from rsmm.engine import cooked as CK
    from rsmm.engine import image as IMG
    from rsmm.engine import prop_cook as PC
    from rsmm.engine.cooked_schemas.texture import TextureHandler

    art = tmp_path / "art"
    art.mkdir()
    (art / "icon.png").write_bytes(IMG.encode_png(48, 48, bytes([9, 200, 240, 255] * 48 * 48)))
    files = poi.emit("mymod", ContentDef(kind="poi", id="Shrine", fields={
        "base": BASE, "chapters": ["Dark_Hills"],
        "icon_source": "art/icon.png"}), tmp_path / "assets")

    tile = next(f for f in files if f.name.endswith(TC.GEN_SUFFIX))
    td = TC.read(tile.read_bytes())
    assert td.icon[1] == "Ui"
    assert td.icon[2] == "MiniMap\\Icons\\mymod_Shrine.png"

    cooked_icon = (tmp_path / "assets" / Path(*PC.ui_cooked_path(td.icon[2]).split("/")))
    assert cooked_icon.is_file(), "tiledef points at an icon the mod does not ship"
    sch = TextureHandler().parse_payload(
        CK.parse(cooked_icon.read_bytes()).sections[-1].payload)
    assert (sch.width, sch.height) == (48, 48)


@needs_corpus
def test_a_custom_icon_asset_can_be_registered_at_apply(tmp_path):
    """`MiniMap\\Icons` is chosen because the game already ships into it — a new
    directory has no sibling for synthesize_encoded to anchor on."""
    from rsmm.cli.apply_mods import load_asset_map, synthesize_encoded
    from rsmm.engine import prop_cook as PC

    decoded = PC.ui_cooked_path(f"{poi.ICON_DIR}\\mymod_Shrine.png")
    assert synthesize_encoded(decoded, load_asset_map()) is not None


# --------------------------------------------------------------------------- #
# Frequency: `copies`, and what `weight` actually is
# --------------------------------------------------------------------------- #

@needs_corpus
@pytest.mark.slow
def test_weight_is_a_tier_field_not_a_spawn_rate():
    """Pins the fact that made `weight` the wrong dial to reach for. Every
    tier-suffixed family carries exactly T1/T2/T3 values, so a mod raising
    `weight` to get more spawns is marking itself a higher-tier variant."""
    import re
    seen = 0
    for p in _tiles:
        m = re.search(r"_T(\d)\.tiledef", Path(p).name)
        if not m:
            continue
        tier = int(m.group(1))
        w = TC.read(open(p, "rb").read()).weight
        assert w == pytest.approx(poi.TIER_WEIGHTS[tier], abs=0.01), (p, w)
        seen += 1
    assert seen >= 20, f"expected the tier families, only matched {seen}"


@needs_corpus
def test_copies_adds_that_many_distinct_pool_entries(tmp_path):
    """The pool is a list of refs and `add_to_pool` de-duplicates, so repeating
    one ref cannot raise a POI's share — each copy must be its own tiledef."""
    files = poi.emit("m", ContentDef(kind="poi", id="Shrine", fields={
        "base": "Dark_Hills/6x6_Bleeding_01", "chapters": ["Dark_Hills"],
        "copies": 4}), tmp_path)
    tiles = [f for f in files if f.name.endswith(TC.GEN_SUFFIX)]
    assert len(tiles) == 4
    assert len({f.name for f in tiles}) == 4, "copies must be distinct assets"

    pool = MP.read_pool(
        (tmp_path / f"Definitions/Maps/Dark_Hills_LiveOps_Update5{MP.GEN_SUFFIX}").read_bytes())
    mine = [p for p in pool if "m_Shrine" in p]
    assert len(mine) == 4 and len(set(mine)) == 4

    # Every copy is the same tile, so they are interchangeable in a slot.
    bodies = {f.read_bytes() for f in tiles}
    assert len(bodies) == 1


@needs_corpus
def test_copies_defaults_to_one(tmp_path):
    files = poi.emit("m", ContentDef(kind="poi", id="S", fields={
        "base": BASE, "chapters": ["Dark_Hills"]}), tmp_path)
    assert sum(1 for f in files if f.name.endswith(TC.GEN_SUFFIX)) == 1


@needs_corpus
@pytest.mark.parametrize("copies,needle", [
    (0, "positive integer"),
    (-1, "positive integer"),
    (2.5, "positive integer"),
    (999, "exceeds"),
])
def test_copies_is_validated(tmp_path, copies, needle):
    with pytest.raises(ContentError, match=needle):
        poi.emit("m", ContentDef(kind="poi", id="S", fields={
            "base": BASE, "chapters": ["Dark_Hills"], "copies": copies}), tmp_path)


def test_discover_passes_copies_through(tmp_path):
    _poi_folder(tmp_path, cfg='chapters = ["Dark_Hills"]\ncopies = 6\n',
                with_art=False)
    assert poi.discover(tmp_path)[0]["copies"] == 6


# --------------------------------------------------------------------------- #
# Identity: a clone must not inherit its donor's level GUID
# --------------------------------------------------------------------------- #

@needs_prop_corpus
def test_every_shipped_tile_level_has_a_distinct_guid():
    """The fact the whole fix rests on. If this ever stops holding, the field
    is not an identity and re-stamping it is wrong."""
    import glob

    from rsmm.engine import prop_cook as PC
    seen = {}
    for p in glob.glob(str(UNCOOKED / "Ot" / "**" / "Tiles" / "*.level.ot.GameStream.gen"),
                       recursive=True):
        g = PC.level_guid(Path(p).read_bytes())
        assert g, p
        assert g not in seen, f"{p} shares a GUID with {seen.get(g)}"
        seen[g] = p
    assert len(seen) > 200


@needs_prop_corpus
def test_cloned_level_gets_its_own_guid():
    """A clone keeping the donor's GUID collides in the level registry and the
    tile silently never appears — no error anywhere, every static check green."""
    from rsmm.engine import prop_cook as PC
    donor = (UNCOOKED / LVL_DONOR).read_bytes()
    out = PC.clone_tile_level(
        donor, "DarkHills\\Tiles\\6x6_Bleeding_01.level.ot",
        "DarkHills\\Tiles\\Mine.level.ot",
        {"DarkHills\\Objects_DarkHills\\Blood_Fountain_DarkHills.entity.ot":
            "DarkHills\\SceneryObjects_DarkHills\\Mine_Prop.entity.ot"})
    assert PC.level_guid(out) != PC.level_guid(donor)


@needs_prop_corpus
def test_cloned_level_guid_is_deterministic_and_unique_per_name():
    """Map generation is seeded run state, so every peer must derive the same
    bytes — a random GUID would desync multiplayer."""
    from rsmm.engine import prop_cook as PC
    donor = (UNCOOKED / LVL_DONOR).read_bytes()
    old = "DarkHills\\Tiles\\6x6_Bleeding_01.level.ot"
    swap = {"DarkHills\\Objects_DarkHills\\Blood_Fountain_DarkHills.entity.ot":
            "DarkHills\\SceneryObjects_DarkHills\\P.entity.ot"}
    a1 = PC.level_guid(PC.clone_tile_level(donor, old, "DarkHills\\Tiles\\A.level.ot", swap))
    a2 = PC.level_guid(PC.clone_tile_level(donor, old, "DarkHills\\Tiles\\A.level.ot", swap))
    b = PC.level_guid(PC.clone_tile_level(donor, old, "DarkHills\\Tiles\\B.level.ot", swap))
    assert a1 == a2, "same content must give the same GUID"
    assert a1 != b, "different levels must not collide with each other"


@needs_prop_corpus
def test_cloned_level_guid_does_not_collide_with_any_shipped_level():
    import glob

    from rsmm.engine import prop_cook as PC
    van = {PC.level_guid(Path(p).read_bytes())
           for p in glob.glob(str(UNCOOKED / "Ot" / "**" / "*.level.ot.GameStream.gen"),
                              recursive=True)}
    out = PC.clone_tile_level(
        (UNCOOKED / LVL_DONOR).read_bytes(),
        "DarkHills\\Tiles\\6x6_Bleeding_01.level.ot", "DarkHills\\Tiles\\Mine.level.ot",
        {"DarkHills\\Objects_DarkHills\\Blood_Fountain_DarkHills.entity.ot":
            "DarkHills\\SceneryObjects_DarkHills\\Mine_Prop.entity.ot"})
    assert PC.level_guid(out) not in van


@needs_corpus
def test_kind_must_match_the_tile_footprint(tmp_path):
    """Every shipped Wishing_Well is 40x40, so a 6x6 tile claiming that kind is
    dead weight — it looks like free extra slots and can never fill one."""
    assert poi.kind_footprints("Wishing_Well") == {(40, 40)}
    assert (6, 6) in poi.kind_footprints("Fountain")
    with pytest.raises(ContentError, match="could never fill"):
        poi.emit("m", ContentDef(kind="poi", id="S", fields={
            "base": "Dark_Hills/6x6_Bleeding_01", "chapters": ["Dark_Hills"],
            "kinds": ["Wishing_Well"]}), tmp_path)


# --------------------------------------------------------------------------- #
# replace_base: override the shipped tile instead of adding one
# --------------------------------------------------------------------------- #

@needs_corpus
@needs_prop_corpus
def test_replace_base_overrides_the_shipped_props_own_art(tmp_path):
    """Override mode puts the mod's art on a shipped prop's own cooked paths.

    It mints no new asset name, because a level cannot reference one: a
    byte-for-byte copy of a shipped entity under a new name, correctly
    registered and cached, still fails to load the level that places it
    (confirmed in-game). So the tile, its level and its prefab are all left
    exactly as shipped, and only the art behind `replaces` changes."""
    from rsmm.engine import gltf
    from rsmm.engine import image as IMG

    art = tmp_path / "art"
    art.mkdir()
    b = gltf.GlbBuilder()
    pi = b.add_positions([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)])
    ni = b.add_vec3([(0, 1, 0)] * 4)
    ui = b.add_vec2([(0, 0)] * 4)
    ii = b.add_indices([0, 1, 2, 0, 1, 3, 0, 2, 3, 1, 2, 3])
    m = b.add_mesh(gltf.Mesh(name="t", primitives=[gltf.Primitive(
        attributes={"POSITION": pi, "NORMAL": ni, "TEXCOORD_0": ui}, indices=ii)]))
    b.add_node(gltf.Node(name="t", mesh=m), is_root=True)
    (art / "m.glb").write_bytes(b.build_glb())
    (art / "m.png").write_bytes(IMG.encode_png(4, 4, bytes([1, 2, 3, 255] * 16)))

    prop = dict(_OVERRIDE_PROP, model="art/m.glb", textures={
        "Scenery\\DarkHills\\Blood_Fountain\\T_Blood_Fountain_DH_ALB.tga":
            "art/m.png"})
    files = poi.emit("mymod", ContentDef(kind="poi", id="S", fields={
        "base": _OVERRIDE_BASE, "chapters": ["Dark_Hills"],
        "replace_base": True, "prop": prop}), tmp_path / "assets")

    names = {f.name for f in files}
    # The POOL must be untouched. The chapter's resource CACHE is a different
    # file and legitimately changes: it is a superset of every tile's cache.
    assert not any(n.endswith(MP.GEN_SUFFIX) for n in names), \
        "override mode must not touch a pool"
    # The mod's art lands on the SHIPPED prop's own cooked paths.
    assert "Thieve_Blood_Fountain.fbx.Geometry.gen" in names
    assert "T_Blood_Fountain_DH_ALB.tga.Texture.dxt" in names
    # Nothing that would introduce a new name, and nothing that edits the tile:
    # no cloned entity, no cloned level, no level override at all.
    assert not any(n.endswith(".entity.ot.EntitySettingsResource.gen") for n in names), \
        "override mode must mint no entity resource — a level cannot reference one"
    assert not any(n.endswith(".level.ot.GameStream.gen") for n in names), \
        "override mode leaves the tile's level exactly as shipped"
    assert not any(n.startswith("mymod_S") for n in names), \
        "override mode introduces no mod-named asset at all"


@needs_corpus
@needs_prop_corpus
def test_override_refuses_a_prop_whose_art_is_shared(tmp_path):
    """In-place override is global, so its whole safety rests on the prop's art
    being its own. A prop many tiles place would silently re-skin all of them."""
    with pytest.raises(ContentError, match="tiles|entities"):
        poi.emit("mymod", ContentDef(kind="poi", id="S", fields={
            "base": "Dark_Hills/40x40_Dark_Hills_Start_Update3",
            "chapters": ["Dark_Hills"], "replace_base": True,
            "prop": {
                "replaces":
                    "DarkHills\\SceneryObjects_DarkHills\\"
                    "Wall_Ruins_Block_Small_A.entity.ot",
                "entity_base":
                    "DarkHills\\SceneryObjects_DarkHills\\"
                    "Wall_Ruins_Block_Small_A.entity.ot",
                "material_base": "Scenery\\DarkHills\\M_Walls_Ruins.mat.ot",
            }}), tmp_path / "assets")


@needs_corpus
@needs_prop_corpus
def test_allow_shared_art_waives_exclusivity_but_never_compositeness(tmp_path):
    """The two guards protect against different things, so only one is
    waivable.

    Sharing means the override reaches further than the author's own tile —
    broad, but exactly what someone re-skinning the start tile is asking for
    (every prop there fails exclusivity, so without the waiver a POI can never
    be guaranteed visible). A COMPOSITE donor is not broad, it is broken: its
    children keep their shipped art and render on top, burying the model.
    """
    _poi_art(tmp_path / "art")
    shared = {
        "replaces":
            "DarkHills\\SceneryObjects_DarkHills\\Carpet_4x4.entity.ot",
        "entity_base":
            "DarkHills\\SceneryObjects_DarkHills\\Carpet_4x4.entity.ot",
        "material_base": "Scenery\\DarkHills\\M_Carpet_Red.mat.ot",
        "model": "art/mine.glb",
    }
    fields = {"base": "Dark_Hills/40x40_Dark_Hills_Start_Update3",
              "chapters": ["Dark_Hills"], "replace_base": True}

    with pytest.raises(ContentError, match="tiles|entities"):
        poi.emit("mymod", ContentDef(kind="poi", id="S", fields=dict(
            fields, prop=dict(shared))), tmp_path / "no")

    files = poi.emit("mymod", ContentDef(kind="poi", id="S", fields=dict(
        fields, prop=dict(shared, allow_shared_art=True))), tmp_path / "yes")
    assert any(f.name == "Carpet_4x4.fbx.Geometry.gen" for f in files), \
        "the waiver must still write the mod's mesh over the donor's own path"

    # The composite check is not opt-outable, so the same waiver must NOT get a
    # composite donor through.
    with pytest.raises(ContentError, match="composite"):
        poi.emit("mymod", ContentDef(kind="poi", id="C", fields={
            "base": "Dark_Hills/6x6_Bleeding_01", "chapters": ["Dark_Hills"],
            "replace_base": True,
            "prop": {
                "replaces":
                    "DarkHills\\Objects_DarkHills\\Blood_Fountain_DarkHills.entity.ot",
                "entity_base":
                    "DarkHills\\Objects_DarkHills\\Blood_Fountain_DarkHills.entity.ot",
                "material_base":
                    "Scenery\\DarkHills\\Blood_Fountain\\M_Blood_Foutain_base_DH.mat.ot",
                "allow_shared_art": True,
            }}), tmp_path / "composite")


def test_texture_slots_must_belong_to_the_prop_being_replaced():
    """An inherited `slots` must not re-skin a different prop.

    `slots` comes from the preset when a def does not set one, and each preset
    names ITS OWN donor's textures — `clearing`'s are the blood fountain's. A
    def that points `replaces` at another prop, ships images and says nothing
    about `slots` therefore re-skins that prop's mesh while writing its images
    over the FOUNTAIN's textures, changing every tile that draws one.

    Nothing else catches it: `_shipped_path` only asks whether the target is a
    shipped asset, and `_assert_art_is_exclusive` looks at the donor's meshes
    and materials, never at the texture refs actually written.

    Checked directly rather than through `emit`, so the assertion is about this
    rule alone and does not depend on a donor that also passes exclusivity.
    """
    donor = "DarkHills\\SceneryObjects_DarkHills\\Menhir_Big_A.entity.ot"
    mats = ["Scenery\\DarkHills\\M_Menhirs_Moss.mat.ot"]
    fountain_tex = ("Scenery\\DarkHills\\Blood_Fountain\\"
                    "T_Blood_Fountain_base_DH_ALB.tga")

    with pytest.raises(ContentError, match="not used by"):
        poi._assert_textures_belong_to("S", donor, mats,
                                       {fountain_tex: "art/albedo.png"})

    # A texture the donor's own material really references is accepted.
    poi._assert_textures_belong_to(
        "S", donor, mats,
        {"Scenery\\DarkHills\\T_Menhirs_ALB.tga": "art/albedo.png"})

    # A material this codec cannot read must not turn into a refusal of a
    # legitimate override — absence of evidence is not evidence of absence.
    poi._assert_textures_belong_to("S", donor, ["No\\Such\\M_Nothing.mat.ot"],
                                   {fountain_tex: "art/albedo.png"})


def test_own_level_clones_the_level_without_minting_entity_names(tmp_path):
    """`own_level` is the isolation rung between the two measured outcomes.

    A mod-owned tiledef loads; a mod-owned tiledef + prefab + level + prop
    entity crashes. Four names moved at once, so "a mod cannot own a level" and
    "a level cannot reference a mod-owned entity" are still entangled — and the
    answer decides whether an own-tile POI can ever carry a minimap icon, since
    icons need a marker-carrying ENTITY placed in the tile.

    So this path must mint exactly two names, a level and its prefab, and zero
    entity names.
    """
    files = poi.emit("mymod", ContentDef(kind="poi", id="L", fields={
        "base": "Dark_Hills/6x6_Bleeding_01", "chapters": ["Dark_Hills"],
        "own_level": True, "copies": 2,
    }), tmp_path / "own")
    rel = {str(f.relative_to(tmp_path / "own").as_posix()) for f in files
           if (tmp_path / "own") in f.parents}

    levels = {r for r in rel if r.startswith("Ot/")}
    assert len(levels) == 1, f"expected exactly one cloned level, got {levels}"
    ents = {r for r in rel if r.startswith("EntitySettings/")}
    assert len(ents) == 1 and "Tiles_Definition" in next(iter(ents)), \
        f"the only new entity may be the tile PREFAB, got {ents}"

    # Two copies means two tiledefs, each with its required cache sibling.
    tiles = {r for r in rel if r.startswith("Definitions/Tiles/")}
    assert len(tiles) == 4, tiles

    # Without `own_level` the same def keeps the donor's prefab and emits no
    # level at all — that is the layer-1 shape, and the two must stay distinct.
    plain = poi.emit("mymod", ContentDef(kind="poi", id="L", fields={
        "base": "Dark_Hills/6x6_Bleeding_01", "chapters": ["Dark_Hills"],
        "copies": 2,
    }), tmp_path / "plain")
    assert not any("Ot/" in str(f) for f in plain)


def test_in_place_override_with_no_art_is_refused(tmp_path):
    """A `replaces` that ships neither mesh nor texture must not "succeed".

    Both write branches in `_emit_prop_override` are guarded, so such a def
    emits its caches and tiledef, applies cleanly, prints a success line and
    changes nothing on screen. It cost a playtest on 2026-08-14: a canary POI
    whose folder happened to have no `model.glb` was indistinguishable from a
    canary that placed and failed to render — the exact question it existed to
    answer.

    Additive mode stays legal without a model (the clone is the donor's shape
    under a mod-owned name), so the refusal is specific to in-place override.
    """
    donor = "DarkHills\\SceneryObjects_DarkHills\\Menhir_Big_A.entity.ot"
    fields = {"base": "Dark_Hills/64x64_Dark_Hills_Menhir_Cultist_Camp",
              "chapters": ["Dark_Hills"], "replace_base": True,
              "prop": {"replaces": donor, "entity_base": donor,
                       "material_base": "Scenery\\DarkHills\\M_Menhirs_Moss.mat.ot"}}
    with pytest.raises(ContentError, match="nothing at all"):
        poi.emit("mymod", ContentDef(kind="poi", id="S", fields=fields), tmp_path / "bare")

    # The same def with a mesh is fine, and writes the donor's own cooked path.
    _poi_art(tmp_path / "art")
    fields["prop"]["model"] = "art/mine.glb"
    files = poi.emit("mymod", ContentDef(kind="poi", id="S", fields=fields),
                     tmp_path / "art_ok")
    assert any(f.name == "Menhir_Big_A.fbx.Geometry.gen" for f in files)


def test_composite_check_ignores_children_that_draw_nothing():
    """A settings-only child is not a composite child.

    Almost every scenery prop in the game attaches
    `Common_Settings\\Environment_Perf_Profile_Tester` — an entity with no
    geometry whatsoever. Counting child references rejected `Pebbles_*`,
    `Wall_Ruins_*`, `Skull`, `RibCage` and most of the rest of the scenery
    corpus, which is what made child-free donors look rare and pushed donor
    choice onto conditional props that never render (2026-08-14: the shrine's
    donor turned out to be the rug under the Sandman, who does not always
    spawn — four playtests were spent debugging the cook instead).

    What actually buried the shrine was children WITH meshes, so that is what
    the guard has to catch, and it still does.
    """
    def strings_of(ref):
        cooked = poi._corpus(PC.entity_cooked_path(ref), "t", "donor")
        return [s for _sec, _off, s in entity_strings.list_strings(cooked)]

    ok = "DarkHills\\SceneryObjects_DarkHills\\Pebbles_4x4.entity.ot"
    kids = [s for s in strings_of(ok) if s.lower().endswith(".entity.ot")]
    assert kids, "this donor is only interesting because it HAS a child"
    assert not any(poi._entity_draws(k) for k in kids)
    poi._assert_prop_is_not_composite("t", ok, strings_of(ok))   # must not raise

    bad = "Storm_Island\\Objects_Storm_Island\\Blood_Fountain_Storm_Island.entity.ot"
    with pytest.raises(ContentError, match="composite"):
        poi._assert_prop_is_not_composite("t", bad, strings_of(bad))

    # An unresolvable child counts as drawing, so the guard fails closed.
    assert poi._entity_draws("No\\Such\\Entity.entity.ot") is True


def test_discover_passes_allow_shared_art_through(tmp_path):
    _poi_folder(tmp_path, with_art=False, cfg=(
        'chapters = ["Dark_Hills"]\nreplace_base = true\n'
        'replaces = "A\\\\B.entity.ot"\nallow_shared_art = true\n'))
    assert poi.discover(tmp_path)[0]["prop"]["allow_shared_art"] is True


def test_discover_passes_replace_base_through(tmp_path):
    _poi_folder(tmp_path, cfg='chapters = ["Dark_Hills"]\nreplace_base = true\n',
                with_art=False)
    assert poi.discover(tmp_path)[0]["replace_base"] is True


@needs_corpus
def test_replace_base_does_not_inherit_preset_kinds_or_weight(tmp_path):
    """A preset describes a NEW tile. Applying its `kinds` to an override would
    rewrite a shipped tile's identity — pointing the default preset at the Start
    tile would have replaced its `Start` kind with `Fountain`, which is the tile
    every run spawns on."""
    _poi_folder(tmp_path, cfg='chapters = ["Dark_Hills"]\nreplace_base = true\n'
                              'base = "Dark_Hills/40x40_Dark_Hills_Start_Update3"\n',
                with_art=False)
    b = poi.discover(tmp_path)[0]
    assert "kinds" not in b and "weight" not in b
    assert b["base"] == "Dark_Hills/40x40_Dark_Hills_Start_Update3"

    # ...but an explicit value still wins.
    import shutil
    shutil.rmtree(tmp_path / poi.POIS_DIRNAME)
    _poi_folder(tmp_path, cfg='chapters = ["Dark_Hills"]\nreplace_base = true\n'
                              'weight = 0.5\n', with_art=False)
    assert poi.discover(tmp_path)[0]["weight"] == 0.5


@needs_corpus
def test_additive_mode_still_inherits_preset_kinds(tmp_path):
    _poi_folder(tmp_path, cfg='chapters = ["Dark_Hills"]\n', with_art=False)
    b = poi.discover(tmp_path)[0]
    assert b["kinds"] == poi.PRESETS[poi.DEFAULT_PRESET]["kinds"]
