"""Tests for custom-mesh cooking via template vertex/index swap."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from rsmm.engine import cook_cache, cooked, geometry_cook
from rsmm.engine.cooked_schemas import NotReversedError
from rsmm.engine.cooked_schemas import geometry as G

_JULIET = Path("data/uncooked/3D/Characters/Heroes/Juliet/Juliet_GEO.fbx.glb")
_CUSTOM = Path("TestModels/CubeHeadJuliet.glb")

_needs_fixtures = pytest.mark.skipif(
    not (_JULIET.exists() and _CUSTOM.exists()),
    reason="needs the Juliet template + TestModels/LowPolyJuliet.glb",
)


def _template() -> bytes:
    return geometry_cook.template_from_uncooked_glb(_JULIET.read_bytes())


@_needs_fixtures
def test_swap_produces_valid_cooked_geometry():
    out = geometry_cook.swap_geometry(_template(), _CUSTOM.read_bytes())
    cf = cooked.parse(out)
    assert cf.classes[0].name == "oCGeometry"
    # The first meshbuffer now carries the custom mesh; extras degenerate.
    recs = [r for s in cf.sections for r in G._parse_meshbuffers(s.payload)]
    assert recs
    custom = geometry_cook.glb_to_submeshes(_CUSTOM.read_bytes())
    want_v = sum(len(s.positions) for s in custom)
    assert recs[0].positions and len(recs[0].positions) == want_v


@_needs_fixtures
def test_swap_resizes_skin_layers_to_match_meshbuffers():
    # After a swap, every per-vertex side layer (binormal/tangent/skinning)
    # must match the new meshbuffer vertex count, or the engine reads garbage
    # bone weights and the mesh explodes in-game.
    out = geometry_cook.swap_geometry(_template(), _CUSTOM.read_bytes())
    cf = cooked.parse(out)
    mb_counts = [len(r.positions) for s in cf.sections
                 for r in G._parse_meshbuffers(s.payload)]
    layer_counts = [geometry_cook._layer_vertex_count(s.payload)
                    for s in cf.sections]
    layer_counts = [c for c in layer_counts if c is not None]
    assert layer_counts, "expected per-vertex side layers in template"
    assert set(layer_counts) <= set(mb_counts)
    assert max(layer_counts) == max(mb_counts)


@_needs_fixtures
def test_swap_aligns_mesh_and_transfers_real_weights():
    # The custom mesh is in a different space (Blender Z-up, own scale); the
    # cook must fit it into the template's space AND give it varied, real bone
    # weights borrowed from the nearest original vertices (not one uniform
    # binding), so it deforms with the skeleton instead of lying on the floor.
    out = geometry_cook.swap_geometry(_template(), _CUSTOM.read_bytes())
    cf = cooked.parse(out)

    # Aligned: the swapped mesh fills the template's vertical extent.
    big = max((r for s in cf.sections for r in G._parse_meshbuffers(s.payload)),
              key=lambda r: len(r.positions))
    ys = [p[1] for p in big.positions]
    assert max(ys) - min(ys) > 1.0  # standing height, not collapsed flat

    # Transferred: the skinning layer has many distinct bindings.
    skin = next(s.payload for s in cf.sections
                if geometry_cook._layer_vertex_count(s.payload)
                and geometry_cook._layer_name(s.payload) == 'skinning'
                and geometry_cook._layer_vertex_count(s.payload) > 10)
    _hdr, blocks = geometry_cook._layer_blocks(skin)
    assert len(set(blocks[0][1])) > 1  # not one uniform binding


def test_fit_transform_is_rigid_no_shear():
    # A rigid rotation + one uniform scale must preserve all pairwise distance
    # ratios exactly (no shear / distortion that caused the "glorp").
    import random
    custom = [(random.uniform(-1, 1), random.uniform(-2, 2), random.uniform(-1, 1))
              for _ in range(200)]
    template = [(0, 0, 0), (1.8, 0, 0), (0, 2.5, 0), (0, 0, 1.0)]
    ap, _an = geometry_cook._fit_transform(custom, template, (90.0, 0.0, 0.0))
    out = [ap(p) for p in custom]

    def dist(a, b):
        return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5

    ratios = []
    for _ in range(300):
        i, j = random.randrange(200), random.randrange(200)
        d0 = dist(custom[i], custom[j])
        if d0 > 1e-6:
            ratios.append(dist(out[i], out[j]) / d0)
    assert max(ratios) - min(ratios) < 1e-9  # constant ratio == rigid+uniform


@_needs_fixtures
def test_explicit_rotation_flows_through_swap():
    out = geometry_cook.swap_geometry(
        _template(), _CUSTOM.read_bytes(), transform={"rotate_deg": [90, 0, 0]})
    assert cooked.parse(out).classes[0].name == "oCGeometry"


def test_rewrite_layer_preserves_header_and_replicates_vertex0():
    import struct
    name = b"tangent"
    v0 = struct.pack("<3f", 1.0, 0.0, 0.0)
    v1 = struct.pack("<3f", 0.0, 1.0, 0.0)
    payload = (struct.pack("<I", 9) + struct.pack("<I", len(name)) + name
               + b"\x00" + struct.pack("<II", 2, 24) + v0 + v1)
    assert geometry_cook._layer_vertex_count(payload) == 2
    grown = geometry_cook._rewrite_layer(payload, 5)
    assert geometry_cook._layer_vertex_count(grown) == 5
    head = 8 + len(name) + 1  # ver(4)+namelen(4)+name + comp(1)
    assert grown[:head] == payload[:head]
    assert grown[head + 8:] == v0 * 5


@_needs_fixtures
def test_swapped_geometry_still_previews():
    out = geometry_cook.swap_geometry(_template(), _CUSTOM.read_bytes())
    glb = G.decode_cooked_to_glb(out)  # must not raise
    assert glb[:4] == b"glTF"


@_needs_fixtures
def test_maybe_cook_custom_glb_needs_template(tmp_path):
    from rsmm.engine import unify

    # Strip the embedded original so it's a *fresh* custom mesh (no template
    # of its own) — then cooking it requires a destination template.
    gltf, binb = unify.read_glb(_CUSTOM.read_bytes())
    gltf.get("extras", {}).pop("rsmm", None)
    src = tmp_path / "Custom_GEO.fbx.Geometry.gen"  # cooked-style name, glb body
    src.write_bytes(unify.write_glb(gltf, binb))

    # magic beats the .gen extension -> recognised as a source to cook.
    assert cook_cache.is_source(src)
    with pytest.raises(NotReversedError):
        cook_cache.maybe_cook(src)  # no template, no embedded original
    tpl = tmp_path / "tpl.yqz"
    tpl.write_bytes(_template())
    out = cook_cache.maybe_cook(src, template=tpl)
    assert cooked.parse(out.read_bytes()).classes[0].name == "oCGeometry"


def test_encode_record_layout():
    sm = G.SubMesh(positions=[(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)],
                   normals=[(0.0, 0.0, 1.0), (0.0, 1.0, 0.0)],
                   uvs=[(0.1, 0.2), (0.3, 0.4)], indices=[0, 1, 0])
    blob = geometry_cook._encode_record(sm, flag=0)
    vcount = struct.unpack_from("<I", blob, 0)[0]
    assert vcount == 2
    n_idx, idx_bytes = struct.unpack_from("<II", blob, 4)
    assert (n_idx, idx_bytes) == (3, 12)
    # 4 (count) + 8 (idx hdr) + 12 (idx) + 1 (flag) + 8 (vtx hdr) = 33
    vcount2, vbytes = struct.unpack_from("<II", blob, 25)
    assert vcount2 == 2 and vbytes == 2 * 48
    # first vertex position round-trips at offset 33.
    assert struct.unpack_from("<3f", blob, 33) == (1.0, 2.0, 3.0)


def test_template_extract_rejects_plain_glb():
    # A custom glb with no rsmm extras is not a template.
    from rsmm.engine.unify import write_glb
    glb = write_glb({"asset": {"version": "2.0"}}, b"")
    with pytest.raises(ValueError):
        geometry_cook.template_from_uncooked_glb(glb)

