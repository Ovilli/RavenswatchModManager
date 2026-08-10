"""The `mesh` kind: override a shipped model in place.

The point of this kind is that it introduces NO new resource name — so these
tests are mostly about proving it stays that small, because the moment it emits
a second file it stops being usable as the isolation test it exists to be.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rsmm.engine import geometry_cook as GC
from rsmm.engine.paths import DATA_DIR
from rsmm.sdk.content import ContentDef, ContentError

TARGET = "Scenery\\DarkHills\\Wall_Ruins_Block_Small_A.fbx"
DONOR_GLB = DATA_DIR / "uncooked/3D/Scenery/DarkHills/Wall_Ruins_Block_Small_A.fbx.glb"

needs_corpus = pytest.mark.skipif(
    not DONOR_GLB.is_file(),
    reason="uncooked corpus absent (run scripts/extract_uncooked.py)",
)


def _mod(tmp_path: Path) -> Path:
    """A mod root shipping a 4-vertex tetrahedron as its model."""
    from rsmm.engine import gltf

    art = tmp_path / "meshes" / "m"
    art.mkdir(parents=True)
    b = gltf.GlbBuilder()
    pi = b.add_positions([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)])
    ni = b.add_vec3([(0, 1, 0)] * 4)
    ui = b.add_vec2([(0, 0)] * 4)
    ii = b.add_indices([0, 1, 2, 0, 1, 3, 0, 2, 3, 1, 2, 3])
    m = b.add_mesh(gltf.Mesh(name="t", primitives=[gltf.Primitive(
        attributes={"POSITION": pi, "NORMAL": ni, "TEXCOORD_0": ui}, indices=ii)]))
    b.add_node(gltf.Node(name="t", mesh=m), is_root=True)
    (art / "model.glb").write_bytes(b.build_glb())
    return art


@needs_corpus
def test_emits_exactly_one_file_at_the_targets_own_path(tmp_path):
    from rsmm.sdk.kinds import meshes

    _mod(tmp_path)
    out = tmp_path / "assets"
    files = meshes.emit("m", ContentDef(kind="mesh", id="swap", fields={
        "target": TARGET, "model": "meshes/m/model.glb"}), out)

    assert [f.relative_to(out).as_posix() for f in files] == [
        "3D/Scenery/DarkHills/Wall_Ruins_Block_Small_A.fbx.Geometry.gen"
    ], "an in-place override must not introduce a second resource name"


@needs_corpus
def test_the_override_carries_the_mods_geometry(tmp_path):
    from rsmm.sdk.kinds import meshes

    _mod(tmp_path)
    out = tmp_path / "assets"
    files = meshes.emit("m", ContentDef(kind="mesh", id="swap", fields={
        "target": TARGET, "model": "meshes/m/model.glb"}), out)

    donor_verts = sum(len(s.positions) for s in GC.glb_to_submeshes(DONOR_GLB.read_bytes()))
    assert donor_verts != 4
    from rsmm.engine import cooked as CK
    from rsmm.engine.cooked_schemas import geometry as G
    subs = None
    for sec in CK.parse(files[0].read_bytes()).sections:
        try:
            s = G._parse_meshbuffers(sec.payload)
        except Exception:  # noqa: BLE001 — not the meshbuffer section
            continue
        if s:
            subs = s
            break
    assert subs is not None
    assert sum(len(s.positions) for s in subs) == 4


@pytest.mark.parametrize("fields,needle", [
    ({"model": "meshes/m/model.glb"}, "'target' is required"),
    ({"target": TARGET}, "'model' is required"),
    ({"target": "Scenery\\X.mat.ot", "model": "meshes/m/model.glb"}, "ending in .fbx"),
])
def test_rejects_bad_defs(tmp_path, fields, needle):
    from rsmm.sdk.kinds import meshes

    _mod(tmp_path)
    with pytest.raises(ContentError, match=needle):
        meshes.emit("m", ContentDef(kind="mesh", id="swap", fields=fields),
                    tmp_path / "assets")


def test_source_art_must_ship_with_the_mod(tmp_path):
    from rsmm.sdk.kinds import meshes

    with pytest.raises(ContentError, match="not in this mod"):
        meshes.emit("m", ContentDef(kind="mesh", id="swap", fields={
            "target": TARGET, "model": "nowhere/model.glb"}), tmp_path / "assets")


def test_mesh_is_a_registered_kind():
    from rsmm.sdk import content as C

    assert "mesh" in C.KINDS
    assert C.KIND_CONFIDENCE["mesh"] == "experimental"
    assert C._load_kind("mesh").__name__.endswith("meshes")


def test_meshes_folder_is_discovered(tmp_path):
    from rsmm.sdk import discovery

    d = tmp_path / "meshes" / "shrine"
    d.mkdir(parents=True)
    (d / "mesh.toml").write_text(
        'target = "Scenery\\\\DarkHills\\\\X.fbx"\nmodel = "meshes/shrine/model.glb"\n')
    blocks = discovery.discover(tmp_path)
    assert blocks == [{
        "kind": "mesh", "id": "shrine",
        "target": "Scenery\\DarkHills\\X.fbx",
        "model": "meshes/shrine/model.glb",
    }]
