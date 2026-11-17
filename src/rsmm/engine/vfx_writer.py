"""Write a visual effect from values: no shipped effect is copied.

An effect is one or more LAYERS, each a particle system the engine plays from
``delay`` for ``duration`` seconds (one ``oCVfxControlCineBloc`` each):

    {"name": "Leaves", "material": "Materials\\\\Hero_Jack_Leaf.mat.ot",
     "blend": 0, "burst": 12, "rate": 0, "lifetime": [0.4, 0.8],
     "size": [0.6, 1.0], "speed": 6, "up": 0, "radius": 0.5, "spread": 360,
     "rotation": 180, "colors": [[1, 1, 1, 1], [0.6, 1, 0.4, 0]],
     "grow": [0.4, 1.0], "gravity": 9.8, "drag": 2, "spin": 90,
     "delay": 0, "duration": 0.3}

* ``burst`` particles at once and/or ``rate`` per second while it plays;
* each lives ``lifetime`` seconds (a min, max range) at ``size`` metres;
* ``speed`` m/s outward from a sphere of ``radius`` (``spread`` degrees of
  it; 360 all round), plus ``up`` m/s straight up; each starts turned up to
  ``rotation`` degrees either way;
* over its life its colour (and opacity) runs through ``colors`` and its size
  through ``grow`` (multiples of ``size``), keys spaced evenly;
* drawn camera-facing with ``material`` (an FX-rooted ``.mat.ot``) and
  ``blend`` (the billboard's mode, 0 as most shipped particles);
* ``gravity`` m/s² pulls it down (a number; or an [x, y, z] force, Y up),
  ``drag`` slows it by that fraction per second (a number, or a list over its
  life), ``spin`` turns it that many degrees per second;
* ``light`` makes each particle a point light of that intensity (shipped 2 to
  50) in its colour, as wide as its size: a glow under a hit. A layer with
  ``light`` and no ``material`` is only a light, as shipped glows are;
* ``mesh`` draws a shipped FX shape at each particle instead of a camera-
  facing sprite, ``size`` metres across: ``"Fan_Flat_Medium_180"`` (a slash
  arc), ``"Ring_Flat_01_Medium"`` (a flat ring) ... any ``FX\\Meshes`` name,
  or ``"decal"`` (projected onto the ground: scorch marks, cracks). ``angle``
  turns it about the vertical that many degrees: in a hit's effect (played
  where the attack faces, Scarlet's slash layout) a fan sweeps straight ahead
  at 90, as her claw slashes set ``Fan_Flat_Large_180`` (size 1.5 for a 2.8 m
  hit).

Field meanings were read off the shipped effects (``vfx_codec`` names their
fields; the emitter's are: ``value_18`` burst, ``value_14`` rate, ``range_8``
lifetime, ``range_80`` size, ``range_88`` rotation, ``value_cc/d0/d4``
velocity with the sphere shape 3's ``value_100`` radius, ``value_11c``
spread). Everything an effect does not set takes the value most shipped
objects of its class hold (``DEFAULTS``). The file's class table is the
engine's: each class's id and version as the shipped effects declare them.
"""

from __future__ import annotations

import copy
import functools
import math
import struct

from . import cooked
from . import vfx_codec as V

#: The classes an effect written here is made of, root first (parents too:
#: the serializer looks their versions up in the table).
CLASSES = ("oCScheduledVfxSettings", "oIResource", "oISerializable", "oCVisualEffectSettings",
           "oIRsSettingsGroup", "oCVisualEffectParticleSetting", "oIVisualEffectSetting",
           "oIRsSettings", "oCCinematic", "oCVfxControlCineBloc", "oIDurationCineBloc",
           "oICineBloc", "oC3dParticleEffectSetting", "oCParticleModifiersSettings",
           "oCParticleEmittersSettings", "oC3dParticleEmitterSettings",
           "oI3dParticleEmitterSetting", "oCParticleRenderersSettings",
           "oI3dBillboardParticleRendererSettings", "oI3dParticleRendererSetting",
           "oI3dParticleEffectorSetting", "oC3dParticleEffectorSizeRampSettings",
           "oC3dParticleEffectorColorRampSettings", "oC3dParticleEffectorAlphaRampSettings",
           "oC3dParticleEffectorCameraOffsetSettings")

#: Whole-degree angles whose shipped bits are NOT f32(deg) * f32(pi/180):
#: authored from a truncated pi (0x40490FDA), read off every shipped emitter
#: orientation (2026-11-16, 11 of 75 whole-degree values).
_SHIPPED_RAD = {3: 0x3D56774F, 45: 0x3F490FDA, 90: 0x3FC90FDA, 180: 0x40490FDA, 360: 0x40C90FDA,
                -3: 0xBD56774F, -12: 0xBE56774F, -45: 0xBF490FDA, -90: 0xBFC90FDA,
                -122: 0xC008467A, -180: 0xC0490FDA}


def _f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


def _rad_bits(degrees: float) -> int:
    """An angle's float32 bits as the game's tools store them: the shipped
    value for the angles above, else float32(deg) * float32(pi/180) in
    float32 (64 of the other shipped whole-degree values; the product of two
    float32 is exact in a double, so one pack rounds it as float32 would)."""
    if float(degrees).is_integer() and int(degrees) in _SHIPPED_RAD:
        return _SHIPPED_RAD[int(degrees)]
    return struct.unpack("<I", struct.pack("<f", _f32(degrees) * _f32(math.pi / 180)))[0]


#: 2π as the game stores it.
_TWO_PI_BITS = _rad_bits(360.0)
_STEP = 1.0 / 60.0

#: What most shipped objects of each class hold (survey of all 2513 effects,
#: 2026-11-08); a written effect starts from these.
DEFAULTS: dict[str, dict] = {
    "emitter": {
        "value_14": 0.0, "flag_20": 1, "value_18": 1, "range_8": [0.5, 0.5], "max_1c": 0,
        "value_c0": 0.0, "flag_21": 1, "range_80": [1.0, 1.0], "range_88": [0.0, 0.0],
        "rate_90": [0, 0, 0, 0, _TWO_PI_BITS, 0, 0], "color_u32": 0, "color_kind": 0,
        "color_mode": 2, "color_start": [1.0, 1.0, 1.0, 1.0], "color_end": [1.0, 1.0, 1.0, 1.0],
        "color_ramp": {"head": 0, "t0": 0.0, "t1": 1.0,
                       "keys": [[0.0, 1.0, 1.0, 1.0, 1.0], [1.0, 1.0, 1.0, 1.0, 1.0]]},
        "flag_10": 0, "value_cc": 0.0, "value_d0": 0.0, "value_d4": 0.0,
        "vec_d8": [0.0, 0.0, 0.0], "shape": 4, "shape_104": [0.0] * 6,
        "value_11c": 2 * math.pi, "value_120": 1.0, "flag_124": 1, "vec_e4": [0.0, 0.0, 0.0],
        "flag_125": 0, "value_100": 0.0, "flag_126": 1, "color_f0": [0.0, 0.0, 0.0, 1.0]},
    "curve": {"mode": 2, "flag_8": 1, "flag_9": 0, "range": [0.0, 1.0], "step": _STEP},
    "size": {"enabled": 1, "scale": 1.0, "flag_5c": 0},
    "color": {"enabled": 1, "value_38": 0},
    "alpha": {"enabled": 1, "flag_68": 0, "pair_60": [0, 0], "flag_68b": 0, "value_6c": 0},
    "camera": {"enabled": 1, "offset": [0.0, 0.0, 1.0]},
    "billboard": {"enabled": 1, "flag_9": 0, "sort_c": 0.0, "material_root": "FX",
                  "uv_4c": [0.5, 0.5]},
    "bloc": {"start": 0.0, "flag_28": 1, "name": "", "track": 0, "flag_50": 0},
    "effect": {"flag_68": 0, "value_70": 0, "mode_6c": 1, "flag_69": 1},
    "root": {"resource": 0, "flag_170": 0, "value_174": 0.0, "flag_1c": 0},
}

LAYER_KEYS = {"name", "material", "blend", "burst", "rate", "lifetime", "size", "speed", "up",
              "radius", "spread", "rotation", "colors", "grow", "delay", "duration",
              "gravity", "drag", "spin", "light", "mesh", "angle"}

#: Classes a layer adds only when it uses them (their parents are in CLASSES).
OPTIONAL = ("oC3dParticleEffectorForceFieldSettings", "oC3dParticleEffectorDampingSettings",
            "oC3dParticleEffectorSelfRotateSettings", "oC3dLightParticleRendererSettings",
            "oI3dMeshParticleRendererSettings")

#: ``mesh = "decal"``: the cube the game projects ground decals with (278 of
#: 1874 shipped mesh layers).
DECAL = ("3D", "DecalCube_1x1.fbx")


def mesh_ref(name: str) -> tuple[str, str]:
    """A layer's ``mesh`` as the (root, path) the renderer names."""
    if name == "decal":
        return DECAL
    if not name.replace("_", "").isalnum():
        raise EffectError(f"mesh {name!r} is the name of a shipped FX mesh (letters, digits, _)")
    return "FX", f"Meshes\\{name}.fbx"


#: The mesh renderer as most shipped mesh layers set it: the particle colour
#: feeds the shader's u_color, vertical up axis.
MESH = {"enabled": 1, "flag_9": 0, "sort_c": 0.0, "vec_48": [0.0, 1.0, 0.0],
        "material_root": "FX", "color_param": "u_color", "channel_count": 4,
        "channels": [2, 2, 2, 2], "param_b0": "", "param_c0": "", "param_118": "",
        "param_128": "", "tail": [1.0, 1.0, 1.0]}

#: The point-light renderer as most shipped glows set it (radius = 1 × size,
#: up to 10 lights, the toon omni-light material).
LIGHT = {"enabled": 1, "flag_9": 0, "sort_c": 0.0, "value_50": 0.0, "radius": 1.0,
         "inner": 0.0, "max": 10, "flag_48": 1, "material_root": "Lights",
         "material": "OmniLightToon.mat.ot"}


class EffectError(ValueError):
    pass


def _pair(v, what: str) -> list[float]:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return [float(v), float(v)]
    if isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
        return [float(v[0]), float(v[1])]
    raise EffectError(f"{what} is a number or a [min, max] pair")


def _even(values: list) -> list[float]:
    n = len(values)
    return [0.0] if n == 1 else [i / (n - 1) for i in range(n)]


def _curve(values: list[float], what: str) -> dict:
    """A float curve through ``values`` at evenly spaced times, its handles a
    third of the way to each neighbour (flat tangents, as shipped keys have)."""
    if not values or not all(isinstance(x, (int, float)) for x in values):
        raise EffectError(f"{what} is a list of numbers")
    ts = _even(values)
    keys = []
    for i, (t, v) in enumerate(zip(ts, values, strict=True)):
        left = (ts[i] - ts[i - 1]) / 3 if i else 0.1
        right = (ts[i + 1] - ts[i]) / 3 if i + 1 < len(ts) else 0.1
        keys.append([t, float(v), t - left, float(v), t + right, float(v), 1, 1])
    return {**DEFAULTS["curve"], "keys": keys}


@functools.cache
def _class_table(extra: tuple[str, ...] = ()) -> list[cooked.ClassDef]:
    """Each class's engine id, version and parent, as shipped effects declare
    it: the core set, then the optional ``extra`` classes a layer uses."""
    from . import corpus
    want = CLASSES + extra
    found: dict[str, cooked.ClassDef] = {}
    for rel in sorted(corpus.rels("FX/Settings/")):
        if not rel.endswith(".ScheduledVfxSettings.gen"):
            continue
        for c in cooked.parse(corpus.read(rel)).classes:
            if c.name in want and c.name not in found:
                found[c.name] = cooked.ClassDef(c.name, c.class_id, c.version_major,
                                                c.version_minor, c.parent_id)
        if len(found) == len(want):
            break
    missing = [n for n in want if n not in found]
    if missing:
        raise EffectError(f"no shipped effect declares {missing}")
    return [found[n] for n in want]


#: An effect of nothing (no layers, no blocs): what a part that must name an
#: effect plays when it should show none. Written by the hero kind wherever a
#: hero names it (hero_ability.NO_FX).
NO_EFFECT = "Settings\\FX\\Common_FX\\RSMM_No_Effect.vfx.ot"


def build(layers: list[dict], *, length: float | None = None, empty: bool = False) -> bytes:
    """A cooked effect playing ``layers`` (see the module doc); ``empty``
    allows none (an effect that shows nothing)."""
    if not layers and not empty:
        raise EffectError("an effect has at least one layer")
    objects: list[V.Obj] = []
    settings, blocs = [], []

    def add(obj: V.Obj) -> int:
        objects.append(obj)
        return len(objects) - 1

    end = 0.0
    for n, raw in enumerate(layers):
        if not isinstance(raw, dict) or set(raw) - LAYER_KEYS:
            raise EffectError(f"layer {n}: a table of {', '.join(sorted(LAYER_KEYS))}")
        if not raw.get("material") and not raw.get("light"):
            raise EffectError(f"layer {n}: needs a material (what it draws) or a light")
        name = str(raw.get("name") or f"Layer {n + 1}")
        e = copy.deepcopy(DEFAULTS["emitter"])
        e["value_18"] = int(raw.get("burst", 1 if not raw.get("rate") else 0))
        e["value_14"] = float(raw.get("rate", 0.0))
        e["range_8"] = _pair(raw.get("lifetime", 0.5), f"layer {n}: lifetime")
        e["range_80"] = _pair(raw.get("size", 1.0), f"layer {n}: size")
        rot = math.radians(float(raw.get("rotation", 0.0)))
        e["range_88"] = [-rot, rot]
        speed, up = float(raw.get("speed", 0.0)), float(raw.get("up", 0.0))
        if speed:                         # outward from a sphere (shape 3)
            e["shape"] = 3
            e["value_cc"] = speed
            e["vec_d8"] = [speed / 8] * 3
        e["value_d0"] = up
        e["value_100"] = float(raw.get("radius", 0.0))
        e["value_11c"] = math.radians(float(raw.get("spread", 360.0)))
        if raw.get("angle") is not None:
            # mode 1 + euler min/max (x, y, z): a fixed yaw, as shipped slashes
            yaw = _rad_bits(float(raw["angle"]))
            e["rate_90"] = [1, 0, yaw, 0, 0, yaw, 0]
        em = add(V.Obj("oC3dParticleEmitterSettings", e))

        mods = []
        colors = raw.get("colors") or [[1, 1, 1, 1], [1, 1, 1, 0]]
        if not all(isinstance(c, list) and len(c) == 4 for c in colors):
            raise EffectError(f"layer {n}: colors is a list of [r, g, b, a]")
        ramp = {"head": 0, "t0": 0.0, "t1": 1.0,
                "keys": [[t, *map(float, c)] for t, c in zip(_even(colors), colors,
                                                               strict=True)]}
        mods.append(add(V.Obj("oC3dParticleEffectorColorRampSettings",
                              {**DEFAULTS["color"], "ramp": ramp})))
        mods.append(add(V.Obj("oC3dParticleEffectorAlphaRampSettings", {
            **DEFAULTS["alpha"], "alpha": _curve([float(c[3]) for c in colors],
                                                 f"layer {n}: colors alpha")})))
        grow = raw.get("grow") or [1.0, 1.0]
        size_curve = _curve([float(x) for x in grow], f"layer {n}: grow")
        mods.append(add(V.Obj("oC3dParticleEffectorSizeRampSettings", {
            **DEFAULTS["size"], "size": size_curve, "size_2": _curve([1.0, 1.0], "size_2")})))
        if not raw.get("mesh"):           # sprites only: shipped mesh layers have none
            mods.append(add(V.Obj("oC3dParticleEffectorCameraOffsetSettings",
                                  copy.deepcopy(DEFAULTS["camera"]))))
        gravity = raw.get("gravity")
        if gravity:
            force = ([0.0, -float(gravity), 0.0] if isinstance(gravity, (int, float))
                     else gravity)
            if not (isinstance(force, list) and len(force) == 3
                    and all(isinstance(x, (int, float)) for x in force)):
                raise EffectError(f"layer {n}: gravity is a number or an [x, y, z] force")
            mods.append(add(V.Obj("oC3dParticleEffectorForceFieldSettings", {
                "enabled": 1, "force": [float(x) for x in force], "local": 0})))
        drag = raw.get("drag")
        if drag:
            drag = drag if isinstance(drag, list) else [drag, drag]
            mods.append(add(V.Obj("oC3dParticleEffectorDampingSettings", {
                "enabled": 1, "flag_58": 1, "flag_59": 1, "flag_5a": 1,
                "damping": _curve(drag, f"layer {n}: drag")})))
        if raw.get("spin"):
            # speed_max turns the SPRITE: the emitter seeds particle +0x58 from
            # the layer's rotation range (FUN_140617370) and SelfRotate adds
            # speed_max*dt to +0x58 (FUN_140626210); speed_min feeds +0x54.
            mods.append(add(V.Obj("oC3dParticleEffectorSelfRotateSettings", {
                "enabled": 1, "speed_min": 0.0,
                "speed_max": math.radians(float(raw["spin"]))})))
        rends = []
        if raw.get("mesh"):
            if not raw.get("material"):
                raise EffectError(f"layer {n}: a mesh needs a material")
            root_, path = mesh_ref(str(raw["mesh"]))
            rends.append(add(V.Obj("oI3dMeshParticleRendererSettings", {
                **copy.deepcopy(MESH), "mesh_root": root_, "mesh": path,
                "material": str(raw["material"])})))
        elif raw.get("material"):
            rends.append(add(V.Obj("oI3dBillboardParticleRendererSettings", {
                **copy.deepcopy(DEFAULTS["billboard"]), "material": str(raw["material"]),
                "blend": int(raw.get("blend", 0))})))
        if raw.get("light"):
            rends.append(add(V.Obj("oC3dLightParticleRendererSettings",
                                   {**LIGHT, "intensity": float(raw["light"])})))

        effect = V.Obj("oC3dParticleEffectSetting", {
            "modifiers": V.Obj("oCParticleModifiersSettings", {"items": mods}),
            "emitters": V.Obj("oCParticleEmittersSettings", {"items": [em]}),
            "renderers": V.Obj("oCParticleRenderersSettings", {"items": rends}),
            **DEFAULTS["effect"]})
        settings.append(add(V.Obj("oCVisualEffectParticleSetting",
                                  {"name": name, "effect": effect})))
        delay = float(raw.get("delay", 0.0))
        duration = float(raw.get("duration", max(e["range_8"])))
        blocs.append(add(V.Obj("oCVfxControlCineBloc", {
            **DEFAULTS["bloc"], "start": delay, "duration": duration, "target": name})))
        end = max(end, delay + duration + max(e["range_8"]))

    root = V.Obj("oCScheduledVfxSettings", {
        "resource": 0,
        "settings": V.Obj("oCVisualEffectSettings", {"items": settings}),
        "cinematic": V.Obj("oCCinematic", {"blocs": blocs,
                                           "length": float(length if length else
                                                            (end or 0.1)),
                                           "flag_1c": 0}),
        "flag_170": 0, "value_174": 0.0})
    cf = cooked.CookedFile(variant="A", hdr_a=0x10, flags=1, extra=1,
                           type_tag=_type_tag())
    used = {o.cls for o in objects}
    cf.classes = list(_class_table(tuple(c for c in OPTIONAL if c in used)))
    return V.encode(V.Vfx(cf, objects, root))


def _type_tag():
    from . import corpus
    rel = next(r for r in corpus.rels("FX/Settings/") if r.endswith(".ScheduledVfxSettings.gen"))
    return cooked.parse(corpus.read(rel)).type_tag


__all__ = ["CLASSES", "DECAL", "DEFAULTS", "LAYER_KEYS", "LIGHT", "MESH", "NO_EFFECT", "OPTIONAL",
           "EffectError", "build", "mesh_ref"]
