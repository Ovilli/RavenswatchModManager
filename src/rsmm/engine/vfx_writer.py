"""Write a visual effect from values: no shipped effect is copied.

An effect is one or more LAYERS, each a particle system the engine plays from
``delay`` for ``duration`` seconds (one ``oCVfxControlCineBloc`` each):

    {"name": "Leaves", "material": "Materials\\\\Hero_Jack_Leaf.mat.ot",
     "blend": 0, "burst": 12, "rate": 0, "lifetime": [0.4, 0.8],
     "size": [0.6, 1.0], "speed": 6, "up": 0, "radius": 0.5, "spread": 360,
     "rotation": 180, "colors": [[1, 1, 1, 1], [0.6, 1, 0.4, 0]],
     "grow": [0.4, 1.0], "delay": 0, "duration": 0.3}

* ``burst`` particles at once and/or ``rate`` per second while it plays;
* each lives ``lifetime`` seconds (a min, max range) at ``size`` metres;
* ``speed`` m/s outward from a sphere of ``radius`` (``spread`` degrees of
  it; 360 all round), plus ``up`` m/s straight up; each starts turned up to
  ``rotation`` degrees either way;
* over its life its colour (and opacity) runs through ``colors`` and its size
  through ``grow`` (multiples of ``size``), keys spaced evenly;
* drawn camera-facing with ``material`` (an FX-rooted ``.mat.ot``) and
  ``blend`` (the billboard's mode, 0 as most shipped particles).

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

_TWO_PI_BITS = struct.unpack("<I", struct.pack("<f", 2 * math.pi))[0]
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
              "radius", "spread", "rotation", "colors", "grow", "delay", "duration"}


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


def _class_table() -> list[cooked.ClassDef]:
    """Each class's engine id, version and parent, as shipped effects declare it."""
    from . import corpus
    found: dict[str, cooked.ClassDef] = {}
    for rel in sorted(corpus.rels("FX/Settings/")):
        if not rel.endswith(".ScheduledVfxSettings.gen"):
            continue
        for c in cooked.parse(corpus.read(rel)).classes:
            if c.name in CLASSES and c.name not in found:
                found[c.name] = cooked.ClassDef(c.name, c.class_id, c.version_major,
                                                c.version_minor, c.parent_id)
        if len(found) == len(CLASSES):
            break
    missing = [n for n in CLASSES if n not in found]
    if missing:
        raise EffectError(f"no shipped effect declares {missing}")
    return [found[n] for n in CLASSES]


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
        if not raw.get("material"):
            raise EffectError(f"layer {n}: needs a material (what it draws)")
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
        mods.append(add(V.Obj("oC3dParticleEffectorCameraOffsetSettings",
                              copy.deepcopy(DEFAULTS["camera"]))))
        rend = add(V.Obj("oI3dBillboardParticleRendererSettings", {
            **copy.deepcopy(DEFAULTS["billboard"]), "material": str(raw["material"]),
            "blend": int(raw.get("blend", 0))}))

        effect = V.Obj("oC3dParticleEffectSetting", {
            "modifiers": V.Obj("oCParticleModifiersSettings", {"items": mods}),
            "emitters": V.Obj("oCParticleEmittersSettings", {"items": [em]}),
            "renderers": V.Obj("oCParticleRenderersSettings", {"items": [rend]}),
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
    cf.classes = _class_table()
    return V.encode(V.Vfx(cf, objects, root))


def _type_tag():
    from . import corpus
    rel = next(r for r in corpus.rels("FX/Settings/") if r.endswith(".ScheduledVfxSettings.gen"))
    return cooked.parse(corpus.read(rel)).type_tag


__all__ = ["CLASSES", "DEFAULTS", "LAYER_KEYS", "NO_EFFECT", "EffectError", "build"]
