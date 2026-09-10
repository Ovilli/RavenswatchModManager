"""Per-vertex side layers must be resized with the mesh, at every version.

A layer the rewrite loop skips keeps the TEMPLATE's vertex count while the mesh
gets a new one. Nothing errors: the file cooks, applies, and the prop renders —
wrong. For `skinning` (ver 12) that shredded animated characters; for
`tangentSign` (ver 9) it left props BLACK, because a short tangent-sign buffer
is a broken tangent basis.
"""

from __future__ import annotations

import struct

import pytest

from rsmm.engine import geometry_cook as GC


def _layer(ver: int, name: str, count: int, stride: int = 4,
           comp: bool = True) -> bytes:
    """A per-vertex layer. `comp` writes the comp_mode byte versions 11/12
    carry and version 9 does not."""
    raw = name.encode()
    out = struct.pack("<I", ver) + struct.pack("<I", len(raw)) + raw
    if comp:
        out += b"\x00"
    out += struct.pack("<II", count, count * stride) + b"\xab" * (count * stride)
    return out


def test_version_9_has_no_comp_mode_byte():
    """The bug: with a comp_mode byte assumed, the vertex count is read as the
    comp_mode, fails the "uncompressed" test, and the layer is silently
    classified as "not per-vertex"."""
    payload = _layer(9, "tangentSign", 188, comp=False)
    assert GC._layer_vertex_count(payload) == 188


@pytest.mark.parametrize("ver", (11, 12))
def test_versions_with_a_comp_mode_byte_still_parse(ver):
    assert GC._layer_vertex_count(_layer(ver, "tangent", 188, stride=12)) == 188


def test_a_compressed_layer_is_refused_not_guessed():
    payload = bytearray(_layer(11, "tangent", 188, stride=12))
    payload[8 + len("tangent")] = 1          # comp_mode = compressed
    assert GC._layer_vertex_count(bytes(payload)) is None


@pytest.mark.parametrize("ver", (9, 11, 12))
@pytest.mark.parametrize(("name", "comp"),
                         (("tangentSign", False), ("tangent", True)))
def test_both_header_forms_round_trip_at_every_version(ver, name, comp):
    """`_layer_blocks` + `_assemble_layer` must be identity on an untouched
    layer, or every swap rewrites bytes it did not mean to.

    Both forms are parametrised against every version on purpose: the comp_mode
    byte tracks the LAYER, not the version — `tangentSign` never carries one and
    `tangent`/`binormal` always do, at versions 9, 11 and 12 alike.
    """
    payload = _layer(ver, name, 12, stride=12 if comp else 4, comp=comp)
    assert GC._layer_vertex_count(payload) == 12
    header, blocks = GC._layer_blocks(payload)
    assert GC._assemble_layer(header, blocks) == payload


def test_rebuilding_resizes_the_layer_to_the_new_vertex_count():
    payload = _layer(9, "tangentSign", 188, comp=False)
    rebuilt = GC._rebuild_layer(payload, 296, None, None, None)
    assert GC._layer_vertex_count(rebuilt) == 296
