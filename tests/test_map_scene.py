"""Map editor scene: resource refs, transforms, the file route, and corpus coverage."""

from __future__ import annotations

import collections
import json
import math
import struct
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from rsmm.engine import map_scene as MS
from rsmm.engine.paths import DATA_DIR

needs_corpus = pytest.mark.skipif(
    not (DATA_DIR / "uncooked" / "Ot").is_dir() or not (DATA_DIR / "uncooked" / "3D").is_dir(),
    reason="uncooked corpus absent (run scripts/extract_uncooked.py)")


def _lstr(s: bytes) -> bytes:
    return struct.pack("<I", len(s)) + s


def test_resource_refs_reads_root_path_pairs_in_order(monkeypatch):
    monkeypatch.setattr(MS, "_index", lambda: ({}, frozenset({"3D", "EntitySettings"})))
    blob = (b"\x00\x01junk" + _lstr(b"3D") + _lstr(b"Scenery\\A.fbx")
            + b"\xff\xff" + _lstr(b"3D") + _lstr(b"Scenery\\M_A.mat.ot")
            + _lstr(b"Other") + _lstr(b"ignored\\path.ot")          # unknown root
            + _lstr(b"EntitySettings") + _lstr(b"X\\Parent.entity.ot") + b"\x00" * 8)
    assert MS.resource_refs(blob) == [
        ("3D", "Scenery\\A.fbx"), ("3D", "Scenery\\M_A.mat.ot"),
        ("EntitySettings", "X\\Parent.entity.ot")]


def test_trs_and_mul_are_column_major():
    t = MS.trs((1, 2, 3), (0, 0, 0, 1), (2, 2, 2))
    assert t[12:15] == (1.0, 2.0, 3.0) and t[0] == t[5] == t[10] == 2.0
    s = math.sqrt(0.5)
    r = MS.trs((0, 0, 0), (0, s, 0, s), (1, 1, 1))              # +90 degrees about Y
    x_axis = r[0:3]                                              # where +X goes
    assert all(abs(a - b) < 1e-9 for a, b in zip(x_axis, (0, 0, -1), strict=True))
    assert MS.mul(MS.IDENTITY, t) == t and MS.mul(t, MS.IDENTITY) == t
    moved = MS.mul(MS.trs((10, 0, 0), (0, 0, 0, 1), (1, 1, 1)), t)
    assert moved[12:15] == (11.0, 2.0, 3.0)


def test_flat_colour_materials():
    assert MS.material_color("LD_Basic\\Common\\Dt_Color_Black.mat.ot") == "#0b0b0c"
    assert MS.material_color("LD_Basic\\Common\\Dt_Color_Black_SKINNED.mat.ot") == "#0b0b0c"
    assert MS.material_color("Scenery\\DarkHills\\M_Bush.mat.ot") is None


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("RSMM_MODS_DIR", str(tmp_path / "mods"))
    from rsmm.cli import cmd_map_editor as CM

    srv = CM.serve(0, tmp_path / "mods")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]

    def get(path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=60) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    yield get
    srv.shutdown()
    srv.server_close()


def test_file_route_serves_only_extracted_meshes_and_textures(server):
    for bad in ("3D/../../asset_map.json", "3D/..%2F..%2Fasset_map.json", "Ot/DarkHills/x.glb",
                "3D/Scenery/x.json", "/etc/passwd", "3D//x.glb", "3D\\Scenery\\x.glb", ""):
        assert server("/api/file?path=" + bad)[0] == 404, bad


def test_three_js_is_vendored_and_served(server):
    code, headers, body = server("/static/three.module.min.js")
    assert code == 200 and headers["Content-Type"].startswith("text/javascript")
    assert b"SPDX-License-Identifier: MIT" in body[:400]
    assert server("/static/../cmd_map_editor.py")[0] == 404
    assert server("/static/other.js")[0] == 404


@needs_corpus
def test_dark_hills_scenery_resolves_to_textured_meshes():
    from rsmm.engine import map_editor as ME

    ch = ME.find_chapter("DarkHills")
    parts = []
    for dec in ME.scenery_levels(ch):
        parts.extend(MS.placed_parts(ME._shipped(dec)))
    assert len(parts) > 10_000
    drawn = collections.Counter(bool(p.texture or p.color) for p, _ in parts)
    assert drawn[True] / len(parts) > 0.98
    assert not any(p.mesh.startswith("3D/LD_Basic/") for p, _ in parts)
    assert all(p.texture for p, _ in parts if p.decal)


@needs_corpus
def test_scene_and_tile_endpoints(server):
    code, _h, body = server("/api/scene?chapter=DarkHills")
    scene = json.loads(body)
    assert code == 200 and scene["instances"] > 10_000
    assert len(scene["parts"]) == len(scene["matrices"])
    code, _h, body = server("/api/tiles?chapter=DarkHills")
    tiles = json.loads(body)["tiles"]
    assert code == 200 and len(tiles) > 50
    camp = next(t for t in tiles if "Camp" in t["flags"] and t["width"] == 40)
    code, _h, body = server("/api/tile?chapter=DarkHills&path=" + urllib.parse.quote(camp["path"]))
    assert code == 200 and json.loads(body)["instances"] > 0
    assert server("/api/tile?chapter=DarkHills&path=Tiles%5CNope.tiledef.ot")[0] == 404
    mesh = scene["parts"][0]["mesh"]
    code, headers, body = server("/api/file?path=" + urllib.parse.quote(mesh))
    assert code == 200 and body[:4] == b"glTF"
