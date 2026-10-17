"""`map` kind: clone a shipped mapdef and point a chapter at it by resref."""

from __future__ import annotations

from pathlib import Path

import pytest

from rsmm.engine import cooked
from rsmm.engine import map_cook as MC
from rsmm.engine import rsc_cache as RC
from rsmm.engine.paths import DATA_DIR
from rsmm.sdk.content import ContentDef, ContentError
from rsmm.sdk.kinds import maps

U = DATA_DIR / "uncooked" / "Definitions"
MODE = U / "GameModes" / f"All_Chapters{MC.MODE_GEN_SUFFIX}"
DH = U / "Maps" / f"Dark_Hills_LiveOps_Update5{MC.MAP_GEN_SUFFIX}"

needs_corpus = pytest.mark.skipif(not (MODE.is_file() and DH.is_file()),
                                  reason="uncooked corpus absent")


@needs_corpus
def test_shipped_chapters_decode_as_the_enum_branch():
    chapters = MC.read_chapters(MODE.read_bytes())
    assert [c["biome"] for c in chapters] == [0, 1, 2, 3]
    assert [c["more"] for c in chapters] == [1, 1, 1, 0]


@needs_corpus
def test_resref_chapter_round_trips_and_leaves_the_rest_alone():
    mode = MODE.read_bytes()
    new = MC.set_chapter_map(mode, 0, "Twilight_Hills")
    chapters = MC.read_chapters(new)
    assert chapters[0] == {"more": 1, "map": ("Definitions", "Maps\\Twilight_Hills.mapdef.ot")}
    assert chapters[1:] == MC.read_chapters(mode)[1:]
    assert cooked.emit(cooked.parse(new)) == new
    # The last chapter keeps "no more chapters follow".
    assert MC.read_chapters(MC.set_chapter_map(mode, 3, "X"))[3]["more"] == 0


@needs_corpus
def test_unknown_chapter_is_refused():
    with pytest.raises(MC.MapCookError):
        MC.set_chapter_map(MODE.read_bytes(), 4, "X")


@needs_corpus
def test_clone_is_the_base_unless_the_tribe_moves():
    base = DH.read_bytes()
    assert MC.clone_mapdef(base) == base
    body = MC.read_mapdef(MC.clone_mapdef(base, tribe="Gnolls"))
    assert body["tribe_ref"] == ["Definitions", "EnemyTribes\\Gnolls.enemytribedef.ot"]
    assert body["level_ref"] == MC.read_mapdef(base)["level_ref"]


@needs_corpus
def test_emit_writes_clone_cache_and_chapter(tmp_path):
    files = maps.emit("m", ContentDef(kind="map", id="Twilight_Hills", fields={
        "base": "Dark_Hills", "tribe": "Gnolls", "chapter": 0}), tmp_path)
    rel = sorted(f.relative_to(tmp_path).as_posix() for f in files)
    assert rel == [
        "Definitions/GameModes/All_Chapters.gamemodedefaultdef.UsedRscCache.ot",
        f"Definitions/GameModes/All_Chapters{MC.MODE_GEN_SUFFIX}",
        "Definitions/Maps/Twilight_Hills.mapdef.UsedRscCache.ot",
        f"Definitions/Maps/Twilight_Hills{MC.MAP_GEN_SUFFIX}",
        "Ot/DarkHills/Map_Twilight_Hills.level.ot.GameStream.gen",
        "Ot/DarkHills/Map_Twilight_Hills_TileGeneration.level.ot.GameStream.gen",
    ]
    cache = RC.parse((tmp_path / rel[2]).read_bytes())
    assert "Ot|DarkHills\\Map_Twilight_Hills_TileGeneration.level.ot|oCGameStream" in cache
    assert not any("Map_Dark_Hills_LiveOps_Update5" in ln for ln in cache)
    assert cache == sorted(cache), "the engine looks lines up; the cache must stay sorted"
    assert "Definitions|Maps\\Twilight_Hills.mapdef.ot|oCDtMapDefinition" in cache
    assert "Definitions|Maps\\Dark_Hills_LiveOps_Update5.mapdef.ot|oCDtMapDefinition" not in cache
    assert any("EnemyTribes\\Gnolls.enemytribedef.ot" in ln for ln in cache)
    mode_cache = RC.parse((tmp_path / rel[0]).read_bytes())
    assert "Definitions|Maps\\Twilight_Hills.mapdef.ot|oCDtMapDefinition" in mode_cache


@needs_corpus
def test_emit_without_chapter_leaves_the_game_mode_alone(tmp_path):
    files = maps.emit("m", ContentDef(kind="map", id="Plain_Hills",
                                      fields={"base": "Dark_Hills"}), tmp_path)
    assert all("GameModes" not in f.as_posix() for f in files)


@pytest.mark.parametrize("fields", [
    {"base": "Nowhere"},
    {"base": "Dark_Hills", "tribe": "Ogres"},        # ships no resource cache
    {"base": "Dark_Hills", "chapter": "0"},
])
@needs_corpus
def test_bad_fields_are_refused(tmp_path, fields):
    with pytest.raises(ContentError):
        maps.emit("m", ContentDef(kind="map", id="Bad_Map", fields=fields), tmp_path)


def test_shipped_names_cannot_be_reused(tmp_path):
    with pytest.raises(ContentError):
        maps.emit("m", ContentDef(kind="map", id="Dark_Hills_LiveOps_Update5",
                                  fields={"base": "Dark_Hills"}), tmp_path)


@needs_corpus
def test_clone_generates_from_its_own_pool(tmp_path):
    """mapdef -> own root level -> own tilegen level -> backref to the CLONE.
    Reusing the base's tilegen level made the clone place the base's pool."""
    from rsmm.engine import prop_cook as PC

    maps.emit("m", ContentDef(kind="map", id="Twilight_Hills",
                              fields={"base": "Dark_Hills"}), tmp_path)

    def refs(rel):
        return PC._refs_doc("oCGameStream", (tmp_path / rel).read_bytes())[1]["asset_refs"]

    mapdef = MC.read_mapdef((tmp_path / "Definitions/Maps" /
                             f"Twilight_Hills{MC.MAP_GEN_SUFFIX}").read_bytes())
    root_ref = "DarkHills\\Map_Twilight_Hills.level.ot"
    tg_ref = "DarkHills\\Map_Twilight_Hills_TileGeneration.level.ot"
    assert mapdef["level_ref"] == ["Ot", root_ref]
    root = refs(PC.level_cooked_path(root_ref))
    assert root[0] == root_ref and tg_ref in root
    assert "DarkHills\\Map_Dark_Hills_Terrain.level.ot" not in root  # via tilegen
    tg = refs(PC.level_cooked_path(tg_ref))
    assert "Maps\\Twilight_Hills.mapdef.ot" in tg
    assert "Maps\\Dark_Hills_LiveOps_Update5.mapdef.ot" not in tg
    assert "DarkHills\\Map_Dark_Hills_Terrain.level.ot" in tg        # terrain shared
    # Own identity: a level keeping its donor's GUID never registers.
    for ref in (root_ref, tg_ref):
        assert PC.level_guid((tmp_path / PC.level_cooked_path(ref)).read_bytes()) \
            not in {PC.level_guid(b) for b in (
                DATA_DIR.joinpath("uncooked", PC.level_cooked_path(
                    "DarkHills\\Map_Dark_Hills_LiveOps_Update5.level.ot")).read_bytes(),
                DATA_DIR.joinpath("uncooked", PC.level_cooked_path(
                    "DarkHills\\Map_Dark_Hills_LiveOps_Update5_TileGeneration.level.ot"
                )).read_bytes())}


@needs_corpus
def test_a_map_without_tile_generation_reuses_its_levels(tmp_path):
    files = maps.emit("m", ContentDef(kind="map", id="Other_Hut",
                                      fields={"base": "Baba_Yaga"}), tmp_path)
    assert not any(f.name.endswith(".level.ot.GameStream.gen") for f in files)


# ---- pool + tilegen on the clone ------------------------------------------

def _emit(tmp_path, **fields):
    maps.emit("m", ContentDef(kind="map", id="Twilight_Hills",
                              fields={"base": "Dark_Hills", **fields}), tmp_path)
    mapdef = (tmp_path / "Definitions/Maps" / f"Twilight_Hills{MC.MAP_GEN_SUFFIX}").read_bytes()
    cache = RC.parse((tmp_path / "Definitions/Maps/Twilight_Hills.mapdef.UsedRscCache.ot")
                     .read_bytes())
    return mapdef, cache


def _tiledef_lines(cache):
    return sorted(ln.split("|")[1] for ln in cache if ln.endswith("|oCDtTileDefinition"))


@needs_corpus
def test_pool_edit_keeps_pool_and_cache_one_for_one(tmp_path):
    from rsmm.engine import map_pool as MP

    dh = MP.read_pool(DH.read_bytes())
    av = MP.read_pool((U / "Maps" / f"Avalon_LiveOps_Update5{MC.MAP_GEN_SUFFIX}").read_bytes())
    extra = next(t for t in av if t not in dh)
    gone = "Tiles\\Dark_Hills\\3x3_Blocker_Props_01.tiledef.ot"
    assert gone in dh
    mapdef, cache = _emit(tmp_path, pool={
        "add": ["Avalon/" + extra.rsplit("\\", 1)[-1].removesuffix(".tiledef.ot")],
        "remove": ["3x3_Blocker_Props_01"]})
    pool = MP.read_pool(mapdef)
    assert extra in pool and gone not in pool and len(pool) == len(dh)
    # A pooled tile with no cache line is never loaded, so never placed.
    assert _tiledef_lines(cache) == sorted(pool)
    assert cache == sorted(cache)
    # The base map is not touched.
    assert MP.read_pool(DH.read_bytes()) == dh


@pytest.mark.parametrize("pool", [
    {"remove": ["40x40_Dark_Hills_Start_Update3"]},   # Start still has count 1
    {"remove": ["6x6_Teleporter_01"]},                 # the only Teleporter tile
    {"add": ["3x3_Crystal_01_Nope"]},                  # not a tile
    {"add": ["Nowhere/3x3_Crystal_01"]},
    {"remove": ["Avalon/6x6_Teleporter_01"]},          # not in this pool
    {"add": []},                                        # changes nothing
    {"swap": []},
])
@needs_corpus
def test_bad_pool_edits_are_refused(tmp_path, pool):
    with pytest.raises(ContentError):
        _emit(tmp_path, pool=pool)


@needs_corpus
def test_tilegen_edit_lands_on_the_clone_not_the_base(tmp_path):
    from rsmm.engine import map_editor as ME
    from rsmm.engine import prop_cook as PC
    from rsmm.engine import tilegen as TG

    _emit(tmp_path, tilegen={"kinds": {"Camp": {"count": 2}},
                             "fill": {"40x40": [], "64x64": []}})
    tg_ref = "DarkHills\\Map_Twilight_Hills_TileGeneration.level.ot"
    tg = TG.read((tmp_path / PC.level_cooked_path(tg_ref)).read_bytes())
    assert {k.name: k.count for k in tg.kinds.values()}["Camp"] == 2
    base = ME.load(ME.find_chapter("DarkHills"))
    assert {k.name: k.count for k in base.kinds.values()}["Camp"] == 5
    # Still the clone's own level: the backref names the clone.
    refs = PC._refs_doc("oCGameStream", (tmp_path / PC.level_cooked_path(tg_ref))
                        .read_bytes())[1]["asset_refs"]
    assert "Maps\\Twilight_Hills.mapdef.ot" in refs


@pytest.mark.parametrize("fields", [
    {"tilegen": {"kinds": {"Nope": {"count": 1}}}},
    {"tilegen": {"kinds": {"Camp": {"count": 5}}}},   # already vanilla
    {"tilegen": "Camp=2"},
])
@needs_corpus
def test_bad_tilegen_edits_are_refused(tmp_path, fields):
    with pytest.raises(ContentError):
        _emit(tmp_path, **fields)


@needs_corpus
def test_a_map_without_tile_generation_refuses_pool_and_tilegen(tmp_path):
    for fields in ({"pool": {"add": ["Dark_Hills/6x6_Teleporter_01"]}},
                   {"tilegen": {"kinds": {"Camp": {"count": 1}}}}):
        with pytest.raises(ContentError):
            maps.emit("m", ContentDef(kind="map", id="Other_Hut",
                                      fields={"base": "Baba_Yaga", **fields}), tmp_path)


# ---- hand-placed tiles ------------------------------------------------------

@needs_corpus
def test_a_placed_tile_is_pinned_to_its_slot_and_nowhere_else(tmp_path):
    from rsmm.engine import map_pool as MP
    from rsmm.engine import prop_cook as PC
    from rsmm.engine import tile_cook as TC
    from rsmm.engine import tilegen as TG

    base_tg = TG.read((U.parent / "Ot/DarkHills/Map_Dark_Hills_LiveOps_Update5_TileGeneration"
                       ".level.ot.GameStream.gen").read_bytes())
    sid = next(i for i in base_tg.sizes[base_tg.spawner.size_ids[
        base_tg.size_names.index("40x40")]].slots)
    shipped_pos = base_tg.slots[sid].pos
    maps.emit("m", ContentDef(kind="map", id="Hills_P", fields={
        "base": "Dark_Hills",
        "tilegen": {"add_slots": [{"group": "64x64", "pos": [30.0, 0.0, 40.0]}]},
        "place": {"new0": "Avalon/64x64_Ponds_And_Fountains_Camp",
                  str(sid): "Dark_Hills/40x40_Dark_Hills_Start_Update3"}}), tmp_path)
    tg = TG.read((tmp_path / PC.level_cooked_path(
        "DarkHills\\Map_Hills_P_TileGeneration.level.ot")).read_bytes())
    flags = ["RSMM_Hills_P_P1", "RSMM_Hills_P_P2"]
    assert tg.kind_names[-2:] == flags
    for flag, pos in zip(flags, [(30.0, 0.0, 40.0), shipped_pos], strict=True):
        ki = tg.kind_names.index(flag)
        assert tg.kinds[tg.spawner.kind_ids[ki]].count == 1
        [slot] = [s for s in tg.slots.values() if s.kinds and s.kinds[ki]]
        assert slot.pos == pos and sum(slot.kinds) == 1
        assert all(row[ki] == 1 for row in slot.compat)
        # Every shipped kind; another placement's kind requires its own flag,
        # which this copy does not carry.
        others = [tg.kinds[k] for k in tg.spawner.kind_ids if tg.kinds[k].name not in flags]
        assert all(flag in k.filter.excluded for k in others)
        assert all(flag in tg.sizes[g].filter.excluded for g in tg.spawner.size_ids)

    pool = MP.read_pool((tmp_path / "Definitions/Maps" /
                         f"Hills_P{MC.MAP_GEN_SUFFIX}").read_bytes())
    copy = "Tiles\\Avalon\\Hills_P_P1_64x64_Ponds_And_Fountains_Camp.tiledef.ot"
    assert copy in pool
    cache = RC.parse((tmp_path / "Definitions/Maps/Hills_P.mapdef.UsedRscCache.ot").read_bytes())
    assert _tiledef_lines(cache) == sorted(pool)
    td = TC.read((tmp_path / "Definitions/Tiles/Avalon" /
                  "Hills_P_P1_64x64_Ponds_And_Fountains_Camp.tiledef.ot.DtTileDefinition.gen")
                 .read_bytes())
    assert td.kinds == ["Camp", "RSMM_Hills_P_P1"]


@pytest.mark.parametrize("place", [
    {"9999": "Dark_Hills/6x6_Teleporter_01"},                  # no such slot
    {"new0": "Dark_Hills/6x6_Teleporter_01"},                  # no added slot
    {"25": "Dark_Hills/6x6_Teleporter_01"},                    # 64x64 slot, 6x6 tile
    {"25": "Nowhere/X"},
    {},
])
@needs_corpus
def test_bad_placements_are_refused(tmp_path, place):
    with pytest.raises(ContentError):
        maps.emit("m", ContentDef(kind="map", id="Hills_P", fields={
            "base": "Dark_Hills", "place": place}), tmp_path)


# ---- painted terrain -------------------------------------------------------

@needs_corpus
def test_terrain_strokes_give_the_clone_its_own_ground(tmp_path):
    from rsmm.engine import prop_cook as PC
    from rsmm.engine import terrain as TR
    from rsmm.engine import tilegen as TG

    maps.emit("m", ContentDef(kind="map", id="Hills_T", fields={
        "base": "Dark_Hills", "terrain": [
            {"op": "raise", "x": -56, "z": 147, "radius": 40, "amount": 6}]}), tmp_path)

    def refs(ref):
        return PC._refs_doc("oCGameStream", (tmp_path / PC.level_cooked_path(ref))
                            .read_bytes())[1]["asset_refs"]

    own = "DarkHills\\Map_Hills_T_Terrain.level.ot"
    assert "DarkHills\\Map_Hills_T_Scenery.level.ot" in refs("DarkHills\\Map_Hills_T.level.ot")
    for lvl in ("DarkHills\\Map_Hills_T_TileGeneration.level.ot",
                "DarkHills\\Map_Hills_T_Scenery.level.ot"):
        assert own in refs(lvl)
        assert "DarkHills\\Map_Dark_Hills_Terrain.level.ot" not in refs(lvl)
    t = TR.read((tmp_path / PC.level_cooked_path(own)).read_bytes(), {TR.HEIGHT})
    tg = TG.read((tmp_path / PC.level_cooked_path(
        "DarkHills\\Map_Hills_T_TileGeneration.level.ot")).read_bytes())
    # every slot sits on the painted ground
    for s in tg.slots.values():
        if s.kinds:
            assert s.pos[1] == pytest.approx(t.height_at(s.pos[0], s.pos[2]), abs=0.02)
    cache = RC.parse((tmp_path / "Definitions/Maps/Hills_T.mapdef.UsedRscCache.ot").read_bytes())
    assert f"Ot|{own}|oCGameStream" in cache


@needs_corpus
def test_a_map_without_terrain_refuses_strokes(tmp_path):
    with pytest.raises(ContentError):
        maps.emit("m", ContentDef(kind="map", id="Other_Hut", fields={
            "base": "Baba_Yaga", "terrain": [{"op": "raise", "x": 0, "z": 0,
                                               "radius": 5, "amount": 1}]}), tmp_path)
