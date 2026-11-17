"""The VFX codec (engine/vfx_codec.py): every shipped effect decodes and
re-encodes byte for byte, and the classes the codec knows are decoded into
fields (not kept raw) everywhere they appear."""

from __future__ import annotations

import collections

import pytest

from rsmm.engine import vfx_codec as V


def _effects() -> list[str]:
    from rsmm.engine import corpus
    try:
        return sorted(r for r in corpus.rels("FX/") if r.endswith(".ScheduledVfxSettings.gen"))
    except Exception:  # noqa: BLE001 — no corpus
        return []


needs_corpus = pytest.mark.skipif(not _effects(), reason="no effect corpus")

#: Classes that must decode into fields wherever they appear (the writer's set).
CORE = {"oCVisualEffectParticleSetting", "oCVfxControlCineBloc", "oC3dParticleEmitterSettings",
        "oC3dParticleEffectorSizeRampSettings", "oC3dParticleEffectorColorRampSettings",
        "oC3dParticleEffectorAlphaRampSettings", "oC3dParticleEffectorSubImageIndexSettings",
        "oC3dParticleEffectorDampingSettings", "oC3dParticleEffectorCameraOffsetSettings",
        "oI3dBillboardParticleRendererSettings"}


@needs_corpus
def test_every_shipped_effect_round_trips_and_core_classes_decode():
    from rsmm.engine import corpus
    raw_core: collections.Counter = collections.Counter()
    for rel in _effects():
        b = corpus.read(rel)
        v = V.decode(b)
        assert V.encode(v) == b, rel
        for o in v.objects:
            if o.cls in CORE and o.raw is not None:
                raw_core[o.cls] += 1
        assert v.root.fields["settings"].raw is None
        assert v.root.fields["cinematic"].raw is None
    assert not raw_core


@needs_corpus
def test_a_decoded_effect_reads_as_values():
    """The debug gizmo effect: one particle system played for a second."""
    from rsmm.engine import corpus
    v = V.decode(corpus.read("FX/Settings/FX/Common_FX/DEBUG_XYZ.vfx.ot.ScheduledVfxSettings.gen"))
    cine = v.root.fields["cinematic"].fields
    bloc = v.objects[cine["blocs"][0]].fields
    setting = v.objects[v.root.fields["settings"].fields["items"][0]]
    assert setting.cls == "oCVisualEffectParticleSetting"
    assert bloc["target"] == setting.fields["name"] and bloc["duration"] == 1.0
    eff = setting.fields["effect"].fields
    emitter = v.objects[eff["emitters"].fields["items"][0]]
    assert emitter.cls == "oC3dParticleEmitterSettings"
    assert 0 <= emitter.fields["shape"] <= 6


@needs_corpus
def test_a_written_effect_falls_drags_spins_and_glows():
    """vfx_writer: gravity / drag / spin / light land as the engine's classes
    with the values given, and a light-only layer draws no sprite."""
    import math

    from rsmm.engine import vfx_writer as VW
    blob = VW.build([
        {"material": "Materials\\Dot_Blurred_Square_01.mat.ot", "burst": 8, "gravity": 9.8,
         "drag": [4, 1], "spin": 90},
        {"light": 12, "size": 3, "colors": [[1, 0.6, 0.2, 1], [1, 0.6, 0.2, 0]]},
    ])
    v = V.decode(blob)
    assert V.encode(v) == blob
    by = collections.defaultdict(list)
    for o in v.objects:
        assert o.raw is None, o.cls
        by[o.cls].append(o.fields)
    assert by["oC3dParticleEffectorForceFieldSettings"] == [
        {"enabled": 1, "force": [0.0, pytest.approx(-9.8), 0.0], "local": 0}]
    keys = by["oC3dParticleEffectorDampingSettings"][0]["damping"]["keys"]
    assert [k[1] for k in keys] == [4.0, 1.0]
    assert by["oC3dParticleEffectorSelfRotateSettings"][0]["speed_max"] == \
        pytest.approx(math.pi / 2)
    assert len(by["oI3dBillboardParticleRendererSettings"]) == 1
    light = by["oC3dLightParticleRendererSettings"][0]
    assert light["intensity"] == 12.0 and light["material"] == "OmniLightToon.mat.ot"
    with pytest.raises(VW.EffectError):
        VW.build([{"burst": 1}])                       # neither a sprite nor a light


def _flat(d, pre=""):
    """(path, value) leaves of a decoded object's fields (lists of numbers kept
    whole by position, nested dicts and objects walked)."""
    for k, v in d.items():
        p = f"{pre}{k}"
        if isinstance(v, V.Obj):
            if v.raw is None:
                yield from _flat(v.fields, p + ".")
        elif isinstance(v, dict):
            yield from _flat(v, p + ".")
        elif isinstance(v, list) and v and all(isinstance(x, list) for x in v):
            continue                                   # keys / ramps: free data
        elif isinstance(v, list):
            for i, x in enumerate(v):
                yield f"{p}[{i}]", x
        else:
            yield p, v


@needs_corpus
def test_written_effects_match_the_games_own_layouts_and_values():
    """Every object the writer emits looks like the game's own: the same fields
    as a shipped object of its class, each flag/int a value the game ships, each
    float inside the shipped range (author-chosen numbers excepted)."""
    from rsmm.engine import corpus
    from rsmm.engine import vfx_writer as VW
    keys: dict[str, set] = collections.defaultdict(set)
    seen: dict[tuple, set] = collections.defaultdict(set)
    span: dict[tuple, list] = {}
    for rel in _effects():
        for o in V.decode(corpus.read(rel)).objects:
            if o.raw is not None:
                continue
            keys[o.cls].add(frozenset(o.fields))
            for p, x in _flat(o.fields):
                if isinstance(x, float):
                    lo_hi = span.setdefault((o.cls, p), [x, x])
                    lo_hi[0], lo_hi[1] = min(lo_hi[0], x), max(lo_hi[1], x)
                else:
                    seen[(o.cls, p)].add(x)
    blob = VW.build([
        {"material": "Materials\\Dot_Blurred_Square_01.mat.ot", "burst": 8, "speed": 6,
         "radius": 0.5, "gravity": 9.8, "drag": [4, 1], "spin": 90, "rotation": 180},
        {"light": 12, "size": 3},
        {"material": "Materials\\Slash_Rim_01.mat.ot", "mesh": "Fan_Flat_Medium_180",
         "angle": 100, "size": 4},
        {"material": "Materials\\Explosion_Ground_Impact_01.mat.ot", "mesh": "decal"},
    ])
    # what an author sets freely (names, paths, timings, sizes, colours, forces)
    free = ("name", "target", "material", "start", "duration", "length", "value_18",
            "value_14", "range_8", "range_80", "range_88", "value_cc", "value_d0",
            "vec_d8", "value_100", "value_11c", "force", "speed_max", "intensity",
            "damping", "alpha", "size", "ramp", "items", "blocs", "settings",
            "modifiers", "emitters", "renderers", "effect", "cinematic", "keys", "mesh")
    bad = []
    for o in V.decode(blob).objects:
        if frozenset(o.fields) not in keys[o.cls]:
            bad.append(f"{o.cls}: fields {sorted(o.fields)} unlike any shipped one")
        for p, x in _flat(o.fields):
            if any(part.split("[")[0] in free for part in p.split(".")):
                continue
            if isinstance(x, float):
                lo, hi = span.get((o.cls, p), (None, None))
                if lo is None or not lo <= x <= hi:
                    bad.append(f"{o.cls}.{p} = {x} outside shipped [{lo}, {hi}]")
            elif x not in seen[(o.cls, p)]:
                bad.append(f"{o.cls}.{p} = {x!r} never shipped")
    assert not bad, "\n".join(bad)


@needs_corpus
def test_a_mesh_layer_draws_a_shipped_shape_turned_as_asked():
    """vfx_writer: ``mesh`` swaps the sprite for the mesh renderer naming the
    shipped FX shape (or the decal cube), ``angle`` sets a fixed yaw the way
    shipped slashes do, and a mesh layer carries no camera-offset effector."""
    import math
    import struct

    from rsmm.engine import vfx_writer as VW
    v = V.decode(VW.build([
        {"material": "Materials\\Slash_Rim_01.mat.ot", "mesh": "Fan_Flat_Medium_180",
         "angle": 100, "size": 4},
        {"material": "Materials\\Explosion_Ground_Impact_01.mat.ot", "mesh": "decal", "size": 6},
    ]))
    cls = [o.cls for o in v.objects]
    assert "oI3dBillboardParticleRendererSettings" not in cls
    assert "oC3dParticleEffectorCameraOffsetSettings" not in cls
    meshes = [o.fields for o in v.objects if o.cls == "oI3dMeshParticleRendererSettings"]
    assert [(m["mesh_root"], m["mesh"]) for m in meshes] == [
        ("FX", "Meshes\\Fan_Flat_Medium_180.fbx"), ("3D", "DecalCube_1x1.fbx")]
    rate = next(o for o in v.objects if o.cls == "oC3dParticleEmitterSettings").fields["rate_90"]
    yaw = struct.unpack("<f", struct.pack("<I", rate[2]))[0]
    assert rate[0] == 1 and rate[2] == rate[5] and yaw == pytest.approx(math.radians(100))


@needs_corpus
def test_an_angle_is_written_with_the_games_own_bits():
    """vfx_writer._rad_bits reproduces every whole-degree emitter orientation
    the game ships, bit for bit (its tools round some through a truncated pi)."""
    import math
    import struct

    from rsmm.engine import corpus
    from rsmm.engine import vfx_writer as VW
    by: dict[int, set] = collections.defaultdict(set)
    for rel in _effects():
        for o in V.decode(corpus.read(rel)).objects:
            if o.cls == "oC3dParticleEmitterSettings" and o.raw is None:
                for b in o.fields["rate_90"][1:]:
                    d = math.degrees(struct.unpack("<f", struct.pack("<I", b))[0])
                    if b and abs(d - round(d)) < 0.01:
                        by[round(d)].add(b)
    assert by
    assert {d for d, bits in by.items() if VW._rad_bits(d) not in bits} == set()
