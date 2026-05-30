"""Smoke tests for the DDS + glTF format helpers.

These are pure format encoders — no Ravenswatch dependency — so they're
testable without the game install. Each test produces a valid file by spec
that downstream tools (image readers / glTF viewers) accept.
"""

from __future__ import annotations

import json
import struct

from rsmm.engine import dds, gltf


def test_dds_bc3_header() -> None:
    """BC3/DXT5 uses legacy DDS_HEADER (no DX10 extension)."""
    pixels = b"\xff" * (8 * 8 * 16)  # one mip of 32x32 BC3 (8x8 blocks of 16 B)
    out = dds.write(pixels, 32, 32, dds.by_name("BC3"))
    assert out.startswith(b"DDS ")
    # Header is at offset 4, fourCC at offset 4+0x54 = 0x58
    assert out[0x54:0x58] == b"DXT5"
    # Width / height
    height, width = struct.unpack_from("<II", out, 0x0C)
    assert (width, height) == (32, 32)
    # Linear size
    linear = struct.unpack_from("<I", out, 0x14)[0]
    assert linear == dds.linear_size(32, 32, dds.by_name("BC3"))


def test_dds_bc7_uses_dx10() -> None:
    """BC7 lacks a legacy fourCC — must emit DX10 extension."""
    pixels = b"\xff" * (8 * 8 * 16)
    out = dds.write(pixels, 32, 32, dds.by_name("BC7"))
    assert out[0x54:0x58] == b"DX10"
    # DX10 header starts at offset 4 + 124 = 0x80
    dxgi = struct.unpack_from("<I", out, 0x80)[0]
    assert dxgi == int(dds.DXGI.BC7_UNORM)


def test_dds_linear_size_bc1_min_block() -> None:
    """1x1 BC1 still requires one full block (8 bytes)."""
    assert dds.linear_size(1, 1, dds.by_name("BC1")) == 8


def test_dds_linear_size_rgba8() -> None:
    """64x64 RGBA8 = 64*64*4 = 16384 bytes."""
    assert dds.linear_size(64, 64, dds.by_name("RGBA8")) == 64 * 64 * 4


def test_glb_minimal_mesh_round_trips_json() -> None:
    """One-triangle mesh with positions only. Verify GLB parses and
    JSON chunk references a valid bufferView/accessor pair."""
    b = gltf.GlbBuilder()
    pos = b.add_positions([(0, 0, 0), (1, 0, 0), (0, 1, 0)])
    mat = b.add_material("flat")
    mesh = b.add_mesh(gltf.Mesh(
        name="tri",
        primitives=[gltf.Primitive(attributes={"POSITION": pos}, material=mat)],
    ))
    b.add_node(gltf.Node(name="root", mesh=mesh), is_root=True)
    blob = b.build_glb()

    # Header
    magic, version, length = struct.unpack_from("<III", blob, 0)
    assert magic == 0x46546C67
    assert version == 2
    assert length == len(blob)

    # JSON chunk
    json_len, json_type = struct.unpack_from("<II", blob, 12)
    assert json_type == 0x4E4F534A
    j = json.loads(blob[20:20 + json_len].decode("utf-8"))
    assert j["asset"]["version"] == "2.0"
    assert j["meshes"][0]["name"] == "tri"
    assert j["meshes"][0]["primitives"][0]["attributes"]["POSITION"] == pos
    assert j["accessors"][pos]["type"] == "VEC3"
    assert j["accessors"][pos]["count"] == 3

    # BIN chunk follows immediately
    bin_off = 20 + json_len
    bin_len, bin_type = struct.unpack_from("<II", blob, bin_off)
    assert bin_type == 0x004E4942
    # 3 positions x 12 bytes = 36, padded to 4 = 36
    assert bin_len == 36


def test_glb_indexed_mesh_min_max() -> None:
    """Indexed mesh: positions accessor should carry min/max bounding box."""
    b = gltf.GlbBuilder()
    pos = b.add_positions([
        (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
    ])
    idx = b.add_indices([0, 1, 2, 0, 2, 3])
    mesh = b.add_mesh(gltf.Mesh(
        name="quad",
        primitives=[gltf.Primitive(attributes={"POSITION": pos}, indices=idx)],
    ))
    b.add_node(gltf.Node(name="root", mesh=mesh), is_root=True)
    blob = b.build_glb()

    json_len = struct.unpack_from("<I", blob, 12)[0]
    j = json.loads(blob[20:20 + json_len].decode("utf-8"))
    a = j["accessors"][pos]
    assert a["min"] == [-1.0, -1.0, -1.0]
    assert a["max"] == [1.0, 1.0, -1.0]
