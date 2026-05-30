"""Tests for rsmm.engine.unify — GLB read/write, albedo embed, anim merge."""

from __future__ import annotations

import struct

from rsmm.engine import unify


def _png_stub() -> bytes:
    # Not a real PNG; embed_base_color only stores the bytes verbatim.
    return b"\x89PNG\r\n\x1a\n" + b"stub-pixels"


def _base_mesh_glb() -> bytes:
    """A minimal mesh GLB: one position accessor, one mesh, one grey material."""
    pos = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    binary = b"".join(struct.pack("<fff", *p) for p in pos)
    gltf = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(binary)}],
        "accessors": [{
            "bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3",
            "min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 0.0],
        }],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "material": 0}]}],
        "materials": [{
            "name": "rsmm_default",
            "pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.8, 0.8, 1.0]},
        }],
        "nodes": [{"name": "submesh_0", "mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    return unify.write_glb(gltf, binary)


def _anim_clip_glb(name: str, root_translation_t: float) -> bytes:
    """A skeleton-only clip: 2 bone nodes + one translation animation channel."""
    # times accessor (1 keyframe) + translation accessor (1 vec3).
    times = struct.pack("<f", 0.0)
    trans = struct.pack("<fff", 0.0, root_translation_t, 0.0)
    binary = times + trans
    gltf = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 4},
            {"buffer": 0, "byteOffset": 4, "byteLength": 12},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 1, "type": "SCALAR",
             "min": [0.0], "max": [0.0]},
            {"bufferView": 1, "componentType": 5126, "count": 1, "type": "VEC3"},
        ],
        "nodes": [
            {"name": "DEF.Root", "children": [1]},
            {"name": "DEF.Pelvis"},
        ],
        "animations": [{
            "name": name,
            "samplers": [{"input": 0, "output": 1, "interpolation": "LINEAR"}],
            "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}],
        }],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    return unify.write_glb(gltf, binary)


def _validate_refs(gltf: dict, binary: bytes) -> None:
    nbv, nacc, nnode = (len(gltf.get(k, []))
                        for k in ("bufferViews", "accessors", "nodes"))
    for v in gltf.get("bufferViews", []):
        assert v["buffer"] == 0
        assert v["byteOffset"] + v["byteLength"] <= len(binary)
    for a in gltf.get("accessors", []):
        if "bufferView" in a:
            assert 0 <= a["bufferView"] < nbv
    for an in gltf.get("animations", []):
        for c in an["channels"]:
            assert 0 <= c["target"]["node"] < nnode
            assert 0 <= c["sampler"] < len(an["samplers"])
        for s in an["samplers"]:
            assert 0 <= s["input"] < nacc
            assert 0 <= s["output"] < nacc
    for r in gltf["scenes"][gltf["scene"]]["nodes"]:
        assert 0 <= r < nnode


def test_read_write_roundtrip():
    blob = _base_mesh_glb()
    gltf, binary = unify.read_glb(blob)
    blob2 = unify.write_glb(gltf, binary)
    gltf2, binary2 = unify.read_glb(blob2)
    assert binary2[:len(binary)] == binary
    assert gltf2["meshes"] == gltf["meshes"]


def test_read_glb_rejects_bad_magic():
    try:
        unify.read_glb(b"NOPE" + b"\0" * 20)
    except ValueError:
        return
    raise AssertionError("expected ValueError on bad magic")


def test_embed_base_color_wires_texture():
    gltf, binary = unify.read_glb(_base_mesh_glb())
    png = _png_stub()
    new_bin = unify.embed_base_color(gltf, bytearray(binary), png)
    # Texture infra added.
    assert len(gltf["images"]) == 1
    assert len(gltf["textures"]) == 1
    assert len(gltf["samplers"]) == 1
    pbr = gltf["materials"][0]["pbrMetallicRoughness"]
    assert pbr["baseColorTexture"]["index"] == 0
    assert pbr["baseColorFactor"] == [1.0, 1.0, 1.0, 1.0]
    # PNG bytes survive verbatim in the bin chunk at the image's bufferView.
    bv = gltf["bufferViews"][gltf["images"][0]["bufferView"]]
    assert new_bin[bv["byteOffset"]:bv["byteOffset"] + bv["byteLength"]] == png


def test_merge_dedups_identical_rig():
    base, base_bin = unify.read_glb(_base_mesh_glb())
    clips = [
        ("clipA", *unify.read_glb(_anim_clip_glb("clipA", 1.0))),
        ("clipB", *unify.read_glb(_anim_clip_glb("clipB", 2.0))),
    ]
    merged, mbin = unify.merge_animations(base, base_bin, clips)
    # Skeleton imported once: 1 mesh node + 2 bone nodes = 3 total.
    assert len(merged["nodes"]) == 3
    # Both animations present, both retargeted onto the shared skeleton.
    assert len(merged["animations"]) == 2
    bone_nodes = {1, 2}
    for an in merged["animations"]:
        for c in an["channels"]:
            assert c["target"]["node"] in bone_nodes
    _validate_refs(merged, mbin)


def test_merge_alternating_rigs_import_each_once():
    # A,B,A,B alternating must yield exactly two skeletons, not four.
    base, base_bin = unify.read_glb(_base_mesh_glb())
    a1 = unify.read_glb(_anim_clip_glb("A1", 1.0))
    b1 = unify.read_glb(_anim_clip_glb("B1", 1.0))
    b1[0]["nodes"][1]["name"] = "DEF.OtherBone"  # distinct rig
    a2 = unify.read_glb(_anim_clip_glb("A2", 3.0))
    b2 = unify.read_glb(_anim_clip_glb("B2", 4.0))
    b2[0]["nodes"][1]["name"] = "DEF.OtherBone"
    merged, mbin = unify.merge_animations(
        base, base_bin,
        [("A1", *a1), ("B1", *b1), ("A2", *a2), ("B2", *b2)])
    # 1 mesh + 2 (rig A) + 2 (rig B) = 5 nodes; 4 animations.
    assert len(merged["nodes"]) == 5
    assert len(merged["animations"]) == 4
    _validate_refs(merged, mbin)


def test_merge_distinct_rig_gets_own_skeleton():
    base, base_bin = unify.read_glb(_base_mesh_glb())
    a = unify.read_glb(_anim_clip_glb("clipA", 1.0))
    # Second clip with a renamed bone -> different rig signature.
    diff = unify.read_glb(_anim_clip_glb("clipB", 2.0))
    diff[0]["nodes"][1]["name"] = "DEF.OtherBone"
    merged, mbin = unify.merge_animations(
        base, base_bin, [("clipA", *a), ("clipB", *diff)])
    # 1 mesh + 2 (clipA skeleton) + 2 (clipB own skeleton) = 5 nodes.
    assert len(merged["nodes"]) == 5
    assert len(merged["animations"]) == 2
    _validate_refs(merged, mbin)
