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

def _needs_fixtures(fn):
    """Gate on the Juliet template + custom mesh AND mark slow: each call cooks
    a real hero mesh (O(n*m) weight transfer), only present with the uncooked
    mirror. `-m 'not slow'` skips these for fast local iteration."""
    fn = pytest.mark.slow(fn)
    return pytest.mark.skipif(
        not (_JULIET.exists() and _CUSTOM.exists()),
        reason="needs the Juliet template + TestModels/LowPolyJuliet.glb",
    )(fn)


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


def test_rebuild_layer_preserves_header_and_replicates_vertex0():
    import struct
    name = b"tangent"
    v0 = struct.pack("<3f", 1.0, 0.0, 0.0)
    v1 = struct.pack("<3f", 0.0, 1.0, 0.0)
    payload = (struct.pack("<I", 9) + struct.pack("<I", len(name)) + name
               + b"\x00" + struct.pack("<II", 2, 24) + v0 + v1)
    assert geometry_cook._layer_vertex_count(payload) == 2
    grown = geometry_cook._rebuild_layer(payload, 5, None, None, None)
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



# The corpus mirrors geometry as uncooked GLB (the cooked template rides along
# in extras.rsmm.cooked_b64), not as a .Geometry.gen — see poi._donor_geometry.
_CARPET = (Path(__file__).resolve().parents[1] / "data" / "uncooked" / "3D"
           / "Scenery" / "DarkHills" / "Carpet_4x4.fbx.glb")


def _tall_glb(height: float) -> bytes:
    """A trivial closed mesh `height` units tall, taller than a floor rug."""
    from rsmm.engine import gltf

    h = height
    b = gltf.GlbBuilder()
    pi = b.add_positions([(0, 0, 0), (1, 0, 0), (0, 0, 1), (0, h, 0)])
    ni = b.add_vec3([(0, 1, 0)] * 4)
    ui = b.add_vec2([(0, 0)] * 4)
    ii = b.add_indices([0, 1, 2, 0, 1, 3, 0, 2, 3, 1, 2, 3])
    m = b.add_mesh(gltf.Mesh(name="t", primitives=[gltf.Primitive(
        attributes={"POSITION": pi, "NORMAL": ni, "TEXCOORD_0": ui},
        indices=ii)]))
    b.add_node(gltf.Node(name="t", mesh=m), is_root=True)
    return b.build_glb()


@pytest.mark.skipif(not _CARPET.is_file(), reason="uncooked corpus absent")
def test_swap_updates_the_bounding_box():
    """The cooked AABB has to follow the mesh that is now in the file.

    It did not, and that is what made the shrine invisible in-game. The donor
    was `Carpet_4x4` — a floor rug whose stored box is about 0.1 units tall —
    and the 2.9-unit obelisk swapped into it kept the rug's bounds, so the
    engine culled it. Every check upstream passed (correct geometry, applied
    bytes, resource cache listed) because the mesh really was right; only the
    box disagreed, which is why three playtests found nothing.

    Uses the real shipped rug rather than a synthetic template: the whole point
    is that a donor much flatter than the custom mesh is the dangerous case.
    """
    def mesh_bbox(cb):
        cf = cooked.parse(cb)
        pos = [p for s in cf.sections
               for r in G._parse_meshbuffers(s.payload) for p in r.positions]
        return geometry_cook._bbox6(pos)

    def find_box(cb, want):
        cf = cooked.parse(cb)
        for s in cf.sections:
            for off in range(0, len(s.payload) - 24 + 1, 4):
                got = struct.unpack_from("<6f", s.payload, off)
                if all(abs(a - b) <= 1e-3
                       for a, b in zip(got, want, strict=True)):
                    return off
        return None

    template = geometry_cook.template_from_uncooked_glb(_CARPET.read_bytes())
    old = mesh_bbox(template)
    assert old[4] - old[1] < 0.5, "donor should be the flat rug"
    assert find_box(template, old) is not None, "template stores its own bounds"

    out = geometry_cook.swap_geometry(template, _tall_glb(6.0),
                                      transform={"fit": "none"})
    new = mesh_bbox(out)
    assert new[4] - new[1] > 5.0, "swapped mesh should be the tall one"
    assert find_box(out, new) is not None, \
        "the AABB still describes the rug, so the mesh will be culled"
    assert find_box(out, old) is None, "stale donor bounds left behind"


def test_auto_upright_believes_a_plausible_y_over_the_longest_axis():
    """A T-posed character is WIDER than it is tall, and "longest axis is up"
    lays it on its side.

    Measured on a real character swap: extents X/Y/Z = 2.5/1.72/0.67 (arms
    out) guessed a 90 deg roll, so every hero stood sideways. A genuinely Z-up
    model has Y as its shallow depth axis and sits far below the ratio, so the
    two cases stay separable — this pins that boundary.
    """
    def box(sx, sy, sz):
        return [(x, y, z) for x in (0, sx) for y in (0, sy) for z in (0, sz)]

    # T-pose: X is longest, but Y is still a believable height -> leave it.
    assert geometry_cook._auto_upright_euler(box(2.5, 1.72, 0.67)) == (0, 0, 0)
    # Ordinary Y-up.
    assert geometry_cook._auto_upright_euler(box(1, 2, 0.5)) == (0, 0, 0)
    # Real Z-up: Y is the shallow depth axis -> stand it up.
    assert geometry_cook._auto_upright_euler(box(1, 0.3, 2)) == (-90, 0, 0)
    # Real X-up.
    assert geometry_cook._auto_upright_euler(box(2, 0.3, 1)) == (0, 0, 90)


def test_bind_pose_gap_separates_an_aligned_mesh_from_one_in_its_own_pose():
    """Skin weights are copied from the NEAREST template vertices, so a donor
    standing in its own pose gets limbs weighted to whatever bone happens to be
    close and tears apart the moment it animates (the `skin="rigid"` note in
    `swap_geometry` describes it).

    The gap is what lets the cooker say so instead of shipping a torn model, so
    the two cases have to stay clearly on either side of the threshold.
    """
    src = {"positions": [(0, 0, 0), (0, 0, 10), (0, 10, 0), (10, 0, 0), (10, 10, 10)]}
    # k_nearest returns SQUARED distances; these are 0.2-0.3 units out on a
    # ~17-unit diagonal — a mesh modelled over the original.
    aligned = [[(0, 0.04)], [(1, 0.09)], [(2, 0.01)]]
    # 5-7 units out: whole limbs where the template has nothing.
    off_pose = [[(0, 25.0)], [(1, 36.0)], [(2, 49.0)]]

    assert geometry_cook.bind_pose_gap(aligned, src) < geometry_cook._BIND_POSE_GAP
    assert geometry_cook.bind_pose_gap(off_pose, src) > geometry_cook._BIND_POSE_GAP
    # Nothing to measure is not a warning.
    assert geometry_cook.bind_pose_gap([], src) is None
    assert geometry_cook.bind_pose_gap(aligned, {"positions": []}) is None


# --- bone-name palettes -------------------------------------------------
#
# The template's `u8` skinning indices address a per-submesh palette of bone
# NAMES, not the file's skeleton. Verified on the shipped assets: every
# submesh's maximum referenced index is exactly `len(palette) - 1`.

_BEOWULF = (Path(__file__).resolve().parents[1] / "data" / "uncooked" / "3D"
            / "Characters" / "Heroes" / "Beowulf" / "Beowulf_GEO.fbx.glb")
_HOG = (Path(__file__).resolve().parents[1] / "data" / "uncooked" / "3D"
        / "Characters" / "Enemies" / "UndeadHogs"
        / "UDHogs_Captain_GEO.fbx.glb")

_needs_beowulf = pytest.mark.skipif(
    not _BEOWULF.is_file(), reason="uncooked corpus absent")


def _palette_audit(cooked_bytes: bytes) -> list[tuple[int, int, int]]:
    """(vertex count, palette size, max referenced bone index) per submesh."""
    cf = cooked.parse(cooked_bytes)
    tgt = next(si for si, s in enumerate(cf.sections)
               if geometry_cook._find_records(s.payload))
    main = cf.sections[tgt].payload
    palettes = geometry_cook._record_palettes(main)
    assert palettes is not None, "template palettes must be readable"
    counts = [len(s.positions) for s in G._parse_meshbuffers(main)]
    rec_of_count: dict[int, int] = {}
    for ri, c in enumerate(counts):
        rec_of_count.setdefault(c, ri)

    out = []
    for si, sec in enumerate(cf.sections):
        if si == tgt:
            continue
        vc = geometry_cook._layer_vertex_count(sec.payload)
        if vc is None or geometry_cook._layer_name(sec.payload) != "skinning":
            continue
        if vc not in rec_of_count:
            continue
        pal = palettes[rec_of_count[vc]]
        _h, blocks = geometry_cook._layer_blocks(sec.payload)
        top = -1
        for _stride, recs in blocks:
            for rec in recs:
                idx, weights = geometry_cook._decode_skin(rec)
                for b, wt in zip(idx, weights, strict=True):
                    if wt > 0.0:
                        top = max(top, b)
        out.append((vc, len(pal), top))
    return out


@_needs_beowulf
def test_shipped_geometry_indexes_its_own_bone_palette():
    """Ground truth for the whole fix: indices are palette-relative.

    If they addressed the skeleton, a 13-name submesh would reference indices
    far above 12. It references exactly 0..12 — three submeshes, three
    independent index spaces.
    """
    rows = _palette_audit(
        geometry_cook.template_from_uncooked_glb(_BEOWULF.read_bytes()))
    assert len(rows) == 3, "Beowulf ships three skinned submeshes"
    for verts, palette, top in rows:
        assert top == palette - 1, (
            f"submesh of {verts} verts references up to {top} of a "
            f"{palette}-entry palette")


@_needs_beowulf
@pytest.mark.slow
@pytest.mark.parametrize("transform", [
    None,
    {"skin": "rigid"},
    {"submeshes": "map"},
])
def test_swap_never_writes_a_bone_index_past_its_palette(transform):
    """The bug: weights pooled across submeshes, written under one palette.

    `_gather_source` concatenates the template's per-vertex skinning records
    across every submesh, and the swap writes the result into record 0 — which
    used to keep record 0's 13-entry palette while carrying indices up to 62
    borrowed from the 63-entry submesh next door. Out of range, silently, on
    any multi-submesh (i.e. any character) template.
    """
    out = geometry_cook.swap_geometry(
        geometry_cook.template_from_uncooked_glb(_BEOWULF.read_bytes()),
        _tall_glb(3.0), transform=transform)
    rows = _palette_audit(out)
    assert rows
    for verts, palette, top in rows:
        assert top < palette, (
            f"submesh of {verts} verts references bone {top} of a "
            f"{palette}-entry palette")


@_needs_beowulf
@pytest.mark.slow
def test_map_mode_keeps_the_templates_submesh_split():
    """`submeshes="map"` is what preserves a multi-material character.

    Merging every donor submesh into record 0 leaves records 1+ as one-vertex
    stubs, so the template's other materials have nothing to draw.
    """
    template = geometry_cook.template_from_uncooked_glb(_BEOWULF.read_bytes())
    custom = _two_part_glb()

    def counts(cb):
        cf = cooked.parse(cb)
        return [len(r.positions) for s in cf.sections
                for r in G._parse_meshbuffers(s.payload)]

    merged = counts(geometry_cook.swap_geometry(template, custom))
    mapped = counts(geometry_cook.swap_geometry(
        template, custom, transform={"submeshes": "map"}))
    assert merged[0] == 8 and merged[1:] == [1, 1], \
        "merge puts everything in record 0"
    assert mapped[0] == 4 and mapped[1] == 4, "map spreads them 1:1"


def _two_part_glb() -> bytes:
    """Two separate 4-vertex primitives, so submesh placement is observable."""
    from rsmm.engine import gltf

    b = gltf.GlbBuilder()
    prims = []
    for dz in (0.0, 2.0):
        pi = b.add_positions([(0, 0, dz), (1, 0, dz), (0, 0, dz + 1), (0, 2, dz)])
        ni = b.add_vec3([(0, 1, 0)] * 4)
        ui = b.add_vec2([(0, 0)] * 4)
        ii = b.add_indices([0, 1, 2, 0, 1, 3, 0, 2, 3, 1, 2, 3])
        prims.append(gltf.Primitive(
            attributes={"POSITION": pi, "NORMAL": ni, "TEXCOORD_0": ui},
            indices=ii))
    for k, prim in enumerate(prims):
        m = b.add_mesh(gltf.Mesh(name=f"part{k}", primitives=[prim]))
        b.add_node(gltf.Node(name=f"part{k}", mesh=m), is_root=True)
    return b.build_glb()


def _rigged_glb(bone_names: list[str]) -> bytes:
    """A 4-vertex mesh with a real glTF skin, every vertex on `bone_names[0]`."""
    from rsmm.engine import gltf

    b = gltf.GlbBuilder()
    pi = b.add_positions([(0, 0, 0), (1, 0, 0), (0, 0, 1), (0, 2, 0)])
    ni = b.add_vec3([(0, 1, 0)] * 4)
    ui = b.add_vec2([(0, 0)] * 4)
    ji = b.add_joints([(0, 0, 0, 0)] * 4)
    wi = b.add_weights([(1.0, 0.0, 0.0, 0.0)] * 4)
    ii = b.add_indices([0, 1, 2, 0, 1, 3, 0, 2, 3, 1, 2, 3])
    mesh = b.add_mesh(gltf.Mesh(name="rig", primitives=[gltf.Primitive(
        attributes={"POSITION": pi, "NORMAL": ni, "TEXCOORD_0": ui,
                    "JOINTS_0": ji, "WEIGHTS_0": wi}, indices=ii)]))
    joints = [b.add_node(gltf.Node(name=n)) for n in bone_names]
    ibm = b.add_mat4_array([[1.0 if i % 5 == 0 else 0.0 for i in range(16)]
                            for _ in bone_names])
    skin = b.add_skin(gltf.Skin(name="s", joints=joints,
                                inverse_bind_matrices=ibm))
    b.add_node(gltf.Node(name="rig", mesh=mesh, skin=skin), is_root=True)
    return b.build_glb()


@_needs_beowulf
@pytest.mark.slow
def test_gltf_skin_binds_by_bone_name():
    """A hand-rigged mesh brings its OWN weights, bound by name.

    Without this the cooker can only guess weights from the nearest original
    vertices, which is why a differently-posed body tears: proximity has no
    way to know an arm vertex is an arm.
    """
    template = geometry_cook.template_from_uncooked_glb(_BEOWULF.read_bytes())
    palettes = geometry_cook._record_palettes(
        cooked.parse(template).sections[
            next(si for si, s in enumerate(cooked.parse(template).sections)
                 if geometry_cook._find_records(s.payload))].payload)
    want = palettes[1][7]  # a real bone from the body submesh's palette

    out = geometry_cook.swap_geometry(
        template, _rigged_glb([want]), transform={"skin": "gltf"})
    cf = cooked.parse(out)
    tgt = next(si for si, s in enumerate(cf.sections)
               if geometry_cook._find_records(s.payload))
    merged = geometry_cook._record_palettes(cf.sections[tgt].payload)[0]
    rows = _palette_audit(out)
    verts, palette, top = rows[0]
    assert verts == 4
    assert merged[top] == want, "every vertex should land on the named bone"
    assert top < palette


@_needs_beowulf
@pytest.mark.slow
def test_gltf_skin_rejects_bones_the_template_does_not_have():
    """Silent mis-binding is the failure mode this whole area suffers from."""
    template = geometry_cook.template_from_uncooked_glb(_BEOWULF.read_bytes())
    with pytest.raises(NotReversedError):
        geometry_cook.swap_geometry(
            template, _rigged_glb(["NotABeowulfBone"]),
            transform={"skin": "gltf"})


@_needs_beowulf
@pytest.mark.slow
def test_bones_alias_rescues_a_renamed_rig():
    template = geometry_cook.template_from_uncooked_glb(_BEOWULF.read_bytes())
    cf = cooked.parse(template)
    tgt = next(si for si, s in enumerate(cf.sections)
               if geometry_cook._find_records(s.payload))
    want = geometry_cook._record_palettes(cf.sections[tgt].payload)[1][7]
    out = geometry_cook.swap_geometry(
        template, _rigged_glb(["mixamo:Spine"]),
        transform={"skin": "gltf", "bones": {"mixamo:Spine": want}})
    assert _palette_audit(out)[0][0] == 4


@_needs_beowulf
@pytest.mark.slow
def test_drop_bones_removes_the_geometry_that_bone_drives():
    """The hog captain's anchor-and-chain is 1340 verts on bones the hero has
    no equivalent for; dropping by bone is the only handle on it, since the
    chain is a region of a submesh rather than a submesh of its own."""
    template = geometry_cook.template_from_uncooked_glb(_BEOWULF.read_bytes())
    cf = cooked.parse(template)
    tgt = next(si for si, s in enumerate(cf.sections)
               if geometry_cook._find_records(s.payload))
    want = geometry_cook._record_palettes(cf.sections[tgt].payload)[1][7]
    with pytest.raises(ValueError, match="removed the entire mesh"):
        geometry_cook.swap_geometry(
            template, _rigged_glb([want]),
            transform={"skin": "gltf", "drop_bones": [want]})


def test_drop_bones_without_gltf_weights_is_refused():
    with pytest.raises(ValueError, match="drop_bones"):
        geometry_cook.swap_geometry(b"", _tall_glb(1.0),
                                    transform={"drop_bones": ["DEF.Head"]})


@_needs_beowulf
def test_fit_centres_a_skinned_template_on_its_body_not_its_accessories():
    """Beowulf carries a back-mounted wyrm that sprawls to z = -2.544.

    Centring on the combined bounding box put a replacement body 0.85 units
    behind the hero — measured, and exactly the "model stands behind the
    character" report. The centroid is where the body is.
    """
    template = geometry_cook.template_from_uncooked_glb(_BEOWULF.read_bytes())
    cf = cooked.parse(template)
    pts = [p for s in cf.sections
           for r in G._parse_meshbuffers(s.payload) for p in r.positions]
    bbox_c = geometry_cook._centre_of(pts, use_centroid=False)
    centroid = geometry_cook._centre_of(pts, use_centroid=True)
    assert bbox_c[2] < -0.7, "the wyrm drags the bounding box backwards"
    assert abs(centroid[2]) < 0.2, "the centroid stays on the body"
