"""`rsmm import-character`: keep only what an edit changed, and a piece with its own
skeleton exports as a second armature.

The Blender side was measured by hand: an untouched Blender round trip of all 45
Piper clips imports as "nothing changed"."""

from __future__ import annotations

import json
import math
import struct
import tomllib

import pytest

from rsmm.cli import cmd_import_character as IC
from rsmm.cli.cmd_export_character import _asset_paths
from rsmm.cli.cmd_export_character import main as export_main
from rsmm.engine import anim_cook as AC
from rsmm.engine import character_export as CE
from rsmm.engine import cooked, corpus

GEO = "3D/Characters/Heroes/Piper/Piper_GEO.fbx.Geometry.gen"
ANIM = "3D/Characters/Heroes/Piper/Animations/"
CLIPS = ("Piper_Dash_Default", "Piper_Spawning")
needs = pytest.mark.skipif(corpus.read(GEO) is None, reason="no Piper geometry")


def _glb(doc: dict, binc: bytes) -> bytes:
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    return (struct.pack("<III", 0x46546C67, 2, 28 + len(js) + len(binc))
            + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(binc), 0x004E4942) + binc)


def _span(doc: dict, i: int) -> tuple[int, int]:
    a = doc["accessors"][i]
    return doc["bufferViews"][a["bufferView"]].get("byteOffset", 0) + a.get("byteOffset", 0), \
        a["count"]


def _export() -> bytes:
    return CE.export(corpus.read(GEO), {c: corpus.read(ANIM + c + ".fbx.Animation.gen")
                                        for c in CLIPS}, name="Piper")


def _edited(glb: bytes) -> bytes:
    """Turn one bone of the dash 90 degrees about X and grow the body 10%."""
    doc, binc = AC._read_glb(glb)
    binc = bytearray(binc)
    anim = next(a for a in doc["animations"] if a["name"] == "Piper_Dash_Default")
    ch = next(c for c in anim["channels"] if c["target"]["path"] == "rotation")
    off, n = _span(doc, anim["samplers"][ch["sampler"]]["output"])
    h = math.sqrt(0.5)
    for k in range(n):
        x, y, z, w = struct.unpack_from("<4f", binc, off + 16 * k)
        struct.pack_into("<4f", binc, off + 16 * k,
                         h * (x + w), h * (y + z), h * (z - y), h * (w - x))
    for p in doc["meshes"][0]["primitives"]:
        off, n = _span(doc, p["attributes"]["POSITION"])
        vals = struct.unpack_from(f"<{3 * n}f", binc, off)
        struct.pack_into(f"<{3 * n}f", binc, off, *(v * 1.1 for v in vals))
    return _glb(doc, bytes(binc))


def test_pose_difference_of_a_clip_with_itself_is_zero():
    clip = corpus.read(ANIM + "Piper_Dash_Default.fbx.Animation.gen")
    if clip is None:
        pytest.skip("no Piper clips")
    tpl = b"".join(s.payload for s in cooked.parse(clip).sections)
    assert AC.pose_difference(tpl, tpl) == pytest.approx((0.0, 0.0), abs=1e-4)


@needs
def test_an_unedited_export_imports_as_nothing_changed():
    glb = _export()
    assert IC.changed_clips(glb, _asset_paths(), 1.0) == []
    assert not IC.body_changed(glb, "Characters\\Heroes\\Piper\\Piper_GEO.fbx")


@needs
def test_an_edit_writes_a_mod_with_only_the_changed_clip_and_the_body(tmp_path, monkeypatch):
    monkeypatch.setenv("RSMM_MODS_DIR", str(tmp_path / "mods"))
    src = tmp_path / "edit.glb"
    src.write_bytes(_edited(_export()))
    assert IC.main([str(src), "--mod", "piper-edit"]) == 0
    mod = tmp_path / "mods" / "piper-edit"
    man = tomllib.loads((mod / "manifest.toml").read_text())
    assert [(c["kind"], c.get("clip")) for c in man["content"]] == \
        [("animation", "Piper_Dash_Default"), ("mesh", None)]
    assert man["content"][0]["target"] == \
        CE.clip_target(ANIM + "Piper_Dash_Default.fbx.Animation.gen")
    assert (mod / "art" / "edit.glb").read_bytes() == src.read_bytes()
    assert IC.main([str(src), "--mod", "piper-edit"]) == 1          # no silent overwrite


@needs
def test_a_piece_with_its_own_skeleton_exports_as_a_second_armature(tmp_path):
    out = tmp_path / "combat.glb"
    assert export_main(["Piper", "--skin", "Combat", "--clips", "", "-o", str(out)]) == 0
    doc, binc = AC._read_glb(out.read_bytes())
    assert len(doc["skins"]) == 2                                   # body + cloak
    for node in (n for n in doc["nodes"] if "skin" in n):
        joints = len(doc["skins"][node["skin"]]["joints"])
        for p in doc["meshes"][node["mesh"]]["primitives"]:
            # JOINTS_0 indexes the skin's own joint list, never the node table.
            assert max(max(j) for j in AC._accessor(doc, binc, p["attributes"]["JOINTS_0"])) \
                < joints
