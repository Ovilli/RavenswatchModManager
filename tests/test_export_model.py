"""`rsmm export-model`: any of the game's 3D models as glTF, not only heroes."""

from __future__ import annotations

import json
import struct

import pytest

from rsmm.cli import cmd_export_model as EM
from rsmm.engine import character_export as CE
from rsmm.engine import corpus

STATIC = "3D/Scenery/DarkHills/Barrel_Cloth.fbx.Geometry.gen"
RIGGED = "3D/Mechas/Chest/BasicChest_GEO.fbx.Geometry.gen"


def _doc(glb: bytes) -> dict:
    n = struct.unpack_from("<I", glb, 12)[0]
    return json.loads(glb[20:20 + n])


def test_match_prefers_an_exact_name_over_a_glob():
    geos = ["3D/Mechas/Chest/Chest.fbx.Geometry.gen",
            "3D/Mechas/Chest/BasicChest_GEO.fbx.Geometry.gen",
            "3D/Scenery/DarkHills/Barrel_Cloth.fbx.Geometry.gen"]
    assert EM.match("chest", geos) == [geos[0]], "an exact name must not pull in *Chest*"
    assert EM.match("*chest*", geos) == geos[:2]
    assert EM.match("3D/Scenery/*", geos) == [geos[2]], "a path glob works too"
    assert EM.stem(geos[1]) == "BasicChest_GEO"


def test_rig_folder_is_the_character_folder():
    assert EM._rig_folder("3D/Characters/Enemies/Ogres/OgreHuman_GEO.fbx.Geometry.gen") \
        == "3D/Characters/Enemies/Ogres/"
    assert EM._rig_folder(RIGGED) == "3D/Mechas/Chest/"


@pytest.mark.skipif(corpus.read(STATIC) is None, reason="no game data")
def test_a_model_without_a_skeleton_exports_as_a_plain_mesh():
    # Before export-model, CE.export refused any geometry without a skeleton,
    # so 2800 of the game's 3001 models could not be exported at all.
    from rsmm.cli.cmd_export_character import _asset_paths
    glb, summary = EM.export_one(STATIC, _asset_paths(), textures=False)
    doc = _doc(glb)
    assert "skins" not in doc and "animations" not in doc, "a static model got a rig"
    assert doc["extras"]["rsmm"]["kind"] == "model"
    assert sum(len(m["primitives"]) for m in doc["meshes"]) == len(doc["materials"]) > 0
    assert summary.startswith("static")
    with pytest.raises(CE.CharacterExportError):
        CE.export(corpus.read(STATIC), {"clip": b""})


@pytest.mark.slow
@pytest.mark.skipif(corpus.read(RIGGED) is None, reason="no game data")
def test_a_rigged_prop_brings_its_clips_and_full_materials():
    from rsmm.cli.cmd_export_character import _asset_paths
    glb, _ = EM.export_one(RIGGED, _asset_paths())
    doc = _doc(glb)
    assert doc["skins"] and len(doc["animations"]) >= 1, "the chest lost its rig or clips"
    mat = doc["materials"][0]
    assert "baseColorTexture" in mat["pbrMetallicRoughness"]
    assert "normalTexture" in mat, "the material search found only the bare albedo"
