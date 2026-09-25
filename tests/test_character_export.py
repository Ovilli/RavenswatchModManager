"""Rigged character export: skeleton decode, matrix decomposition, glTF shape.

The Blender round trip itself (45 Piper clips within 0.3 deg at 60 fps) was
measured by hand with headless Blender; these keep the pieces it rests on."""

from __future__ import annotations

import json
import math
import struct

import pytest

from rsmm.engine import anim_cook as AC
from rsmm.engine import character_export as CE
from rsmm.engine import cooked, corpus

GEO = "3D/Characters/Heroes/Piper/Piper_GEO.fbx.Geometry.gen"
DASH = "3D/Characters/Heroes/Piper/Animations/Piper_Dash_Default.fbx.Animation.gen"
needs = pytest.mark.skipif(corpus.read(GEO) is None, reason="no Piper geometry")


def _mm(a, b):
    return [sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4)) for r in range(4) for c in range(4)]


@needs
def test_skeleton_composes_local_times_parent_world_into_world():
    bones = CE.read_skeleton(cooked.parse(corpus.read(GEO)))
    assert len(bones) == 100 and bones[0]["name"] == "DEF.RootMotion" and bones[0]["parent"] == -1
    for b in bones:
        world = b["local_bind"] if b["parent"] < 0 else \
            _mm(b["local_bind"], bones[b["parent"]]["world_bind"])
        assert max(abs(x - y) for x, y in zip(world, b["world_bind"], strict=True)) < 1e-4
        ident = _mm(b["inverse_bind"], b["world_bind"])
        assert all(abs(v - (1.0 if i % 5 == 0 else 0.0)) < 1e-3 for i, v in enumerate(ident))


def test_decompose_recovers_trs():
    ang = math.radians(40)
    c, s = math.cos(ang), math.sin(ang)
    # Row-vector convention: rotation about Z, then translate.
    m = [c, s, 0, 0, -s, c, 0, 0, 0, 0, 1, 0, 1.5, -2.0, 3.0, 1]
    t, q, sc = CE.decompose(m)
    assert t == [1.5, -2.0, 3.0] and sc == pytest.approx([1, 1, 1])
    assert abs(abs(q[3]) - math.cos(ang / 2)) < 1e-6 and abs(abs(q[2]) - math.sin(ang / 2)) < 1e-6


@needs
def test_export_is_a_rigged_skinned_animated_gltf_whose_clip_cooks_back():
    clip = corpus.read(DASH)
    glb = CE.export(corpus.read(GEO), {"Piper_Dash_Default": clip}, name="Piper")
    doc, _ = AC._read_glb(glb)
    skin = doc["skins"][0]
    assert len(skin["joints"]) == 100
    assert sum("children" in n for n in doc["nodes"]) > 10          # a hierarchy, not flat
    prims = doc["meshes"][0]["primitives"]
    assert len(prims) == 2 and all("JOINTS_0" in p["attributes"] for p in prims)
    assert len({p["material"] for p in prims}) == 2                 # Blender keeps the split
    # Each material wears its submesh's own albedo (T_Piper_ALB), embedded as PNG.
    assert [i["name"] for i in doc["images"]] == ["T_Piper_ALB.tga"]
    assert all(m["pbrMetallicRoughness"].get("baseColorTexture") == {"index": 0}
               for m in doc["materials"])
    payload = b"".join(s.payload for s in cooked.parse(clip).sections)
    out, notes = AC.cook(glb, payload, name="Piper_Dash_Default")
    assert out == payload and notes == []


def test_quaternion_keys_are_sign_continuous():
    from rsmm.engine.cooked_schemas.animation import continuous_quats
    q = continuous_quats([(0, 0, 0, 1), (0, 0, 0, -1), (0.1, 0, 0, -0.99)])
    assert all(sum(a * b for a, b in zip(x, y, strict=True)) >= 0
               for x, y in zip(q, q[1:], strict=False))


def test_clip_names_and_targets():
    assert CE.clip_name(DASH) == "Piper_Dash_Default"
    assert CE.clip_target(DASH) == "Characters\\Heroes\\Piper\\Animations\\Piper_Dash_Default.fbx"


@needs
def test_skins_resolve_from_the_hero_entities():
    from rsmm.cli import cmd_export_character as X
    paths = X._asset_paths()
    base = X.resolve_setup("Piper", None, paths)
    assert {"Albino", "Combat", "Poison"} <= set(base["skins"])
    assert not any("Pet" in s or s == "FX" for s in base["skins"])        # other objects
    assert base["body"].endswith("Piper_GEO.fbx")
    assert base["attachments"]["Weapon In Left Hand Mesh"] == {
        "bone": "DEF.Weapon.R", "mesh": "Characters\\Heroes\\Piper\\Piper_Flute.fbx"}
    assert base["mats"]["Character Mesh"].endswith("M_Piper.mat.ot")
    albino = X.resolve_setup("Piper", "Albino", paths)
    assert albino["mats"]["Character Mesh"].endswith("M_PiperAlbino.mat.ot")
    combat = X.resolve_setup("Piper", "Combat", paths)
    assert combat["body"].endswith("Piper_Combat_GEO.fbx")
    assert combat["attachments"]["Weapon In Left Hand Mesh"]["mesh"].endswith(
        "Piper_Flute_Combat_GEO.fbx")


@needs
def test_full_materials_and_the_weapon_on_its_bone():
    slots = CE.material_slots("Characters\\Heroes\\Piper\\Textures\\M_Piper.mat.ot")
    assert set(slots) == {"ALB", "MRA", "NRM"}
    flute = corpus.read("3D/Characters/Heroes/Piper/Piper_Flute.fbx.Geometry.gen")
    glb = CE.export(corpus.read(GEO), {}, name="Piper", materials=[slots, slots],
                    attachments=[{"name": "Flute", "bone": "DEF.Weapon.R", "geometry": flute,
                                  "slots": {}}])
    doc, _ = AC._read_glb(glb)
    body = doc["materials"][0]
    assert "normalTexture" in body and "occlusionTexture" in body
    assert "metallicRoughnessTexture" in body["pbrMetallicRoughness"]
    weapon_joint = next(n for n in doc["nodes"] if n["name"] == "DEF.Weapon.R")
    assert any(doc["nodes"][c]["name"] == "Flute" for c in weapon_joint["children"])


def test_skinning_layer_versions_10_and_13_are_read():
    from rsmm.engine import geometry_cook as GC
    assert {10, 13} <= set(GC._LAYER_VERS)


@pytest.mark.skipif(corpus.read("3D/Characters/Heroes/Juliet/Juliet_GEO.fbx.Geometry.gen") is None,
                    reason="no Juliet/Geppetto geometry")
def test_other_heroes_get_their_own_materials_per_submesh(tmp_path):
    from rsmm.cli.cmd_export_character import main
    # Juliet's gun and flask name no texture; the entity pairs them with a .mat inline.
    # Geppetto's body has two materials (body + Acc) that one "Character Mesh" key hid.
    for hero in ("Juliet", "Geppetto"):
        out = tmp_path / f"{hero}.glb"
        assert main([hero, "--clips", "", "-o", str(out)]) == 0
        doc, _ = AC._read_glb(out.read_bytes())
        mats = doc["materials"]
        for m in doc["meshes"]:
            for p in m["primitives"]:
                assert "baseColorTexture" in mats[p["material"]]["pbrMetallicRoughness"], \
                    (hero, m["name"])
        if hero == "Geppetto":
            body = doc["meshes"][0]["primitives"]
            assert len({mats[p["material"]]["pbrMetallicRoughness"]["baseColorTexture"]["index"]
                        for p in body}) == 2


def test_material_by_name_needs_every_distinctive_word_in_the_mesh_name():
    from rsmm.cli.cmd_export_character import material_by_name
    t = "Characters\\Heroes\\X\\Textures\\"
    merlin = [t + "M_Merlin_Crystal.mat.ot", t + "M_Merlin_Staff_Crystal.mat.ot"]
    assert material_by_name("X\\Merlin_Staff_Crystal_GEO.fbx", merlin, "Merlin") == merlin[1]
    red = [t + "M_Red_WolfCult.mat.ot", t + "M_Red_Wolf_WolfCult.mat.ot"]
    assert material_by_name("X\\Wolf_WolfCult_Skin_GEO.fbx", red, "RED") in red
    # The Combat cloak's real material is an FX shader: no PBR candidate may claim it.
    piper = [t + "M_PiperCombatFlute.mat.ot", t + "M_PiperRat.mat.ot"]
    assert material_by_name("X\\PiperCombat_Cloak_GEO.fbx", piper, "Piper") is None
