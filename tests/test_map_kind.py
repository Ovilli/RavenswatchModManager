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
