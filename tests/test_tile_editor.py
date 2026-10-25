"""The Map tab's 3D tile mode (`engine/tile_editor` + `cli/editor/tiles`).

Pure checks run anywhere; the end-to-end ones need game data (the uncooked
mirror or an install) and skip without it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rsmm.engine import corpus
from rsmm.engine import tile_editor as TE

TILE = "Tiles\\Dark_Hills\\6x6_Crystal_01.tiledef.ot"
PROP = "DarkHills\\SceneryObjects_DarkHills\\Wall_Ruins_Block_Small_A.entity.ot"

_TILEDEF = "Definitions/Tiles/Dark_Hills/6x6_Crystal_01.tiledef.ot.DtTileDefinition.gen"
needs_game = pytest.mark.skipif(
    corpus.read(_TILEDEF) is None,
    reason="no game data (uncooked mirror or install)")


def test_base_of_and_poi_id():
    assert TE.base_of(TILE) == "Dark_Hills/6x6_Crystal_01"
    assert TE.poi_id(TILE) == "6x6_crystal_01"
    with pytest.raises(TE.TileEditError):
        TE.base_of("Tiles\\..\\x.tiledef.ot")


@pytest.mark.parametrize("bad, msg", [
    ([], "at least one"),
    ([{"entity": "x", "pos": [0, 0, 0]}], "not an entity"),
    ([{"entity": PROP, "pos": [0, 0]}], "three numbers"),
    ([{"entity": PROP, "pos": [0, 9999, 0]}], "outside"),
    ([{"entity": PROP, "pos": [0, 0, 0], "scale": 0}], "outside"),
    ([{"entity": PROP, "pos": [0, 0, True]}], "expected a number"),
])
def test_clean_places_refuses_bad_input(bad, msg):
    with pytest.raises(TE.TileEditError, match=msg):
        TE.clean_places(bad)


@needs_game
def test_poi_toml_round_trips():
    places = [{"entity": PROP, "pos": [1.5, 0, -2], "yaw": 45, "scale": 1.2}]
    assert TE.read_places(TE.poi_toml(TILE, places)) == (TILE, TE.clean_places(places))


@needs_game
def test_objects_and_check_use_the_real_poi_emit():
    data = TE.objects_json(TILE)
    assert data["chapters"] == ["Dark_Hills"] and data["objects"]
    assert all(len(o["pos"]) == 3 and len(o["quat"]) == 4 for o in data["objects"])
    files = TE.check(TILE, [{"entity": PROP, "pos": [2, 0, 1], "yaw": 30, "scale": 1}])
    assert any(f.endswith(".level.ot.GameStream.gen") for f in files)
    assert any(f.endswith(".tiledef.UsedRscCache.ot") for f in files)


@needs_game
def test_save_list_reopen_and_lint(tmp_path):
    from rsmm.cli.editor.bridge import Bridge
    from rsmm.cli.lint import lint_one

    b = Bridge(mods=tmp_path, tab="map")
    hdr = {"X-RSMM-Token": b.token, "Content-Type": "application/json"}

    def post(path, body):
        return b.request("POST", path, json.dumps(body).encode(), hdr)
    places = [{"entity": PROP, "pos": [2, 0, 1], "yaw": 30, "scale": 1}]
    st, _h, out = post("/map/api/t3/save", {"tile": TILE, "places": places, "mod_id": "my-tile"})
    assert st == 200, out
    assert json.loads(out)["path"] == "mods/my-tile/manifest.toml"
    mod = tmp_path / "my-tile"
    assert (mod / "manifest.toml").read_text().startswith(TE.TILE_MARK)

    st, _h, out = b.request("GET", "/map/api/t3/mods")
    assert json.loads(out)["mods"] == [{"id": "my-tile", "tiles": [TILE]}]
    st, _h, out = b.request("GET", "/map/api/t3/mod?id=my-tile")
    assert json.loads(out)["tiles"] == {TILE: TE.clean_places(places)}

    errors, _warnings = lint_one(mod)
    assert errors == 0

    # Saving the tile with nothing added takes its poi back out.
    st, _h, _ = post("/map/api/t3/save", {"tile": TILE, "places": [], "mod_id": "my-tile"})
    assert st == 200 and not (mod / "pois" / TE.poi_id(TILE)).exists()


def test_save_refuses_a_mod_the_editor_did_not_make(tmp_path):
    from rsmm.cli.editor.bridge import Bridge

    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "manifest.toml").write_text('[mod]\nid = "other"\n')
    b = Bridge(mods=tmp_path)
    st, _h, out = b.request("POST", "/map/api/t3/save", json.dumps(
        {"tile": TILE, "places": [], "mod_id": "other"}).encode(),
        {"X-RSMM-Token": b.token, "Content-Type": "application/json"})
    assert st == 409, out
    assert Path(tmp_path / "other" / "manifest.toml").read_text() == '[mod]\nid = "other"\n'
