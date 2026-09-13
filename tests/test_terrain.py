"""Painted terrain reader: grid/box location, and the orientation proof."""

from __future__ import annotations

import base64
import json
import struct

import pytest

from rsmm.engine import map_editor as ME
from rsmm.engine import terrain as TR
from rsmm.engine.paths import DATA_DIR

needs_corpus = pytest.mark.skipif(
    not (DATA_DIR / "uncooked" / "Ot").is_dir(),
    reason="uncooked corpus absent (run scripts/extract_uncooked.py)")


def _layer_payload(name: bytes, header: bytes, size: int, cell: float) -> bytes:
    body = struct.pack(f"<{size * size}f", *([cell] * (size * size)))
    return (struct.pack("<II", 16, len(name)) + name + header
            + struct.pack("<III", size, size, len(body)) + body)


def test_grid_header_is_found_by_its_relations_not_an_offset():
    for header in (b"", b"\x01\x00\x00\x00\x39\x00\x00\x00", b"\x00" * 23):
        p = _layer_payload(b"Base Height", header, 8, 0.5)
        off = TR._grid_offset(p, 8 + len(b"Base Height"))
        assert off == 8 + len(b"Base Height") + len(header)


def test_a_grid_that_does_not_end_the_payload_is_refused():
    p = _layer_payload(b"LD Path", b"", 8, 0.0) + b"\x00\x00\x00\x00"
    with pytest.raises(TR.TerrainError):
        TR._grid_offset(p, 8 + len(b"LD Path"))


def test_world_box_is_the_single_ordered_square_window():
    # two stray bytes leave the box unaligned, as it is in the shipped oCTerrainGo
    lead = b"\x04\x00\x00\x00" + struct.pack("<4f", 1, 1, 1, 1) + b"\x00\x00"
    p = lead + struct.pack("<6f", -256, -50, -256, 256, 50, 256) + b"\x12\x00\x00\x00"
    assert TR._box(p) == ((-256.0, -50.0, -256.0), (256.0, 50.0, 256.0))
    with pytest.raises(TR.TerrainError):
        TR._box(p + struct.pack("<6f", -10, -1, -10, 10, 1, 10))   # a second box: ambiguous


def test_resample_samples_cell_centres():
    cells = __import__("array").array("f", [float(i) for i in range(16)])
    layer = TR.Layer("x", 4, "float", cells)
    assert TR.resample(layer, 2) == [5.0, 7.0, 13.0, 15.0]
    assert TR.resample(layer, 4) == list(cells)


@needs_corpus
@pytest.mark.parametrize("key", ["Avalon", "DarkHills", "Storm_Island"])
def test_height_under_every_slot_matches_the_slot_and_no_flip_does(key):
    """The orientation proof: the recipe's slot Y values are independent data."""
    ch = ME.find_chapter(key)
    tr = TR.read(ME._shipped(ME.terrain_decoded(ch)), names={TR.HEIGHT})
    assert tr.box_min == (-256.0, -50.0, -256.0) and tr.box_max == (256.0, 50.0, 256.0)
    slots = [s for s in ME.load(ch).slots.values() if s.kinds]
    err = sum(abs(tr.height_at(s.pos[0], s.pos[2]) - s.pos[1]) for s in slots) / len(slots)
    assert err < 0.01

    h, lo, span = tr.layers[TR.HEIGHT], tr.box_min, tr.box_max[0] - tr.box_min[0]

    def mean_err(transform):
        total = 0.0
        for s in slots:
            u, v = transform((s.pos[0] - lo[0]) / span, (s.pos[2] - lo[2]) / span)
            total += abs(lo[1] + h.at(u, v) * 100.0 - s.pos[1])
        return total / len(slots)

    for wrong in (lambda u, v: (v, u), lambda u, v: (1 - u, v), lambda u, v: (u, 1 - v)):
        assert mean_err(wrong) > 1.0


@needs_corpus
def test_terrain_endpoint_serves_quantised_layers(tmp_path, monkeypatch):
    import threading
    import urllib.request

    monkeypatch.setenv("RSMM_MODS_DIR", str(tmp_path / "mods"))
    from rsmm.cli import cmd_map_editor as CM

    srv = CM.serve(0, tmp_path / "mods")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/api/terrain?chapter=DarkHills"
        with urllib.request.urlopen(url, timeout=30) as r:
            t = json.loads(r.read())
    finally:
        srv.shutdown()
        srv.server_close()
    n = t["grid"]
    assert len(base64.b64decode(t["height"]["u16"])) == 2 * n * n
    assert len(base64.b64decode(t["path"])) == n * n
    assert len(base64.b64decode(t["block"])) == n * n
    assert t["height"]["min"] < t["height"]["max"]
