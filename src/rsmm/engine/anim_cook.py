"""Cook a glTF animation into the game's ``oCAnimation`` format.

The inverse of the preview exporter in :mod:`cooked_schemas.animation`. Every
quantizer here is proven against the shipped corpus (all 2240 animations,
2026-09-24): translation and scale re-encode byte-identically, and rotation
matches on every keyframe except ~0.16% near-ties (two components equal to
five decimals), where the other axis is dropped instead. Those decode to the
SAME rotation, and :func:`cook` keeps the template's original blob whenever
the rotation is unchanged, so an unedited round trip is byte-identical.

On-disk encoding (``oCAnimationTrack``):

* time — u16 in a u32 wire, ``round(seconds / duration * 65535)``;
* translation / scale — 3 × i16, ``round(clamp(v, -32, 31) * 1024)``;
* rotation — 48-bit "smallest three": the largest-magnitude component is
  dropped (index in bits 45-46, sign flipped so it is positive) and the other
  three are signed 15-bit fields scaled by ``sqrt(2) * 16383``.

A cooked clip is built ON A TEMPLATE — the shipped clip being replaced — which
supplies the bone order, the per-clip tail fields and any bone the glTF does
not animate. Bones are matched by NAME: a glTF node animated by a channel must
be named exactly like the game bone (``DEF-LEG-TOP.R``), which is what the
exporter writes and what a Blender armature keeps on export.
"""

from __future__ import annotations

import json
import struct
from dataclasses import replace

from .cooked_schemas import animation as A

_SC = A._QUAT_SCALE
_TIME_MAX = 65535


class AnimCookError(ValueError):
    pass


# --------------------------------------------------------------------------
# quantizers (proven against the corpus; see module docstring)
# --------------------------------------------------------------------------

def quant_time(t: float, duration: float) -> int:
    if duration <= 0:
        return 0
    return max(0, min(_TIME_MAX, int(round(t / duration * _TIME_MAX))))


def quant_ts(v) -> bytes:
    return struct.pack("<hhh", *[
        max(-32768, min(32767, int(round(max(-32.0, min(31.0, float(c))) * 1024))))
        for c in v])


def quant_quat(q) -> bytes:
    n = sum(c * c for c in q) ** 0.5 or 1.0
    q = [c / n for c in q]
    idx = max(range(4), key=lambda i: abs(q[i]))
    s = -1.0 if q[idx] < 0 else 1.0
    f = [int(round(q[i] * s * _SC)) & 0x7FFF for i in range(4) if i != idx]
    raw = (idx << 45) | (f[0] << 30) | (f[1] << 15) | f[2]
    return struct.pack("<IH", raw & 0xFFFFFFFF, raw >> 32)


def _same_rotation(a: bytes, b: bytes) -> bool:
    qa, qb = A._decode_quat(a), A._decode_quat(b)
    return abs(sum(x * y for x, y in zip(qa, qb, strict=True))) > 1 - 1e-6


# --------------------------------------------------------------------------
# glTF animation reader
# --------------------------------------------------------------------------

_COMP = {5126: ("f", 4), 5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2)}
_NORM = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0}
_NCOMP = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}


def _read_glb(glb: bytes) -> tuple[dict, bytes]:
    if glb[:4] != b"glTF" or struct.unpack_from("<I", glb, 4)[0] != 2:
        raise AnimCookError("not a glTF 2 binary (.glb)")
    pos, doc, binc = 12, None, b""
    while pos + 8 <= len(glb):
        ln, kind = struct.unpack_from("<I4s", glb, pos)
        chunk = glb[pos + 8:pos + 8 + ln]
        if kind == b"JSON":
            doc = json.loads(chunk.rstrip(b" \0"))
        elif kind == b"BIN\0":
            binc = chunk
        pos += 8 + ln
    if doc is None:
        raise AnimCookError("glb has no JSON chunk")
    return doc, binc


def _accessor(doc: dict, binc: bytes, i: int) -> list:
    acc = doc["accessors"][i]
    if "sparse" in acc:
        raise AnimCookError("sparse accessors are not supported")
    fmt, size = _COMP[acc["componentType"]]
    n = _NCOMP[acc["type"]]
    view = doc["bufferViews"][acc["bufferView"]]
    base = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = view.get("byteStride") or size * n
    norm = acc.get("normalized") and acc["componentType"] in _NORM
    out = []
    for k in range(acc["count"]):
        vals = struct.unpack_from(f"<{n}{fmt}", binc, base + k * stride)
        if norm:
            vals = tuple(max(-1.0, v / _NORM[acc["componentType"]]) for v in vals)
        out.append(float(vals[0]) if n == 1 else tuple(float(v) for v in vals))
    return out


def read_gltf_animation(glb: bytes, name: str | None = None) -> dict[str, dict[str, list]]:
    """``{bone: {"translation"|"rotation"|"scale": [(seconds, value), ...]}}``.

    Takes the animation called ``name``, or the first one. CUBICSPLINE
    samplers keep their value (the middle of each in-tangent/value/out-tangent
    triple); the engine interpolates linearly between keys.
    """
    doc, binc = _read_glb(glb)
    anims = doc.get("animations") or []
    if not anims:
        raise AnimCookError("glb contains no animation")
    anim = next((a for a in anims if a.get("name") == name), None) if name else anims[0]
    if anim is None:
        raise AnimCookError(f"no animation named {name!r}; have "
                            f"{[a.get('name') for a in anims]}")
    nodes = doc.get("nodes") or []
    out: dict[str, dict[str, list]] = {}
    for ch in anim["channels"]:
        tgt = ch.get("target") or {}
        path = tgt.get("path")
        if path not in ("translation", "rotation", "scale") or "node" not in tgt:
            continue
        bone = nodes[tgt["node"]].get("name")
        if not bone:
            raise AnimCookError(f"animated node {tgt['node']} has no name to match a bone")
        smp = anim["samplers"][ch["sampler"]]
        times = _accessor(doc, binc, smp["input"])
        vals = _accessor(doc, binc, smp["output"])
        if smp.get("interpolation") == "CUBICSPLINE":
            vals = vals[1::3]
        if len(vals) != len(times):
            raise AnimCookError(f"{bone}.{path}: {len(times)} times but {len(vals)} values")
        out.setdefault(bone, {})[path] = list(zip(times, vals, strict=True))
    return out


# --------------------------------------------------------------------------
# cooker
# --------------------------------------------------------------------------

def _stream(keys, template_times, template_vals, duration, quant, same):
    times = [quant_time(t, duration) for t, _ in keys]
    vals = [quant(v) for _, v in keys]
    # Unedited round trip: keep the template's own blob where the value is the
    # same (a near-tie rotation re-encodes to different, equivalent bytes).
    if times == template_times and len(vals) == len(template_vals):
        vals = [o if (n != o and same(n, o)) else n
                for n, o in zip(vals, template_vals, strict=True)]
    return times, vals


def cook(glb: bytes, template_payload: bytes, *, name: str | None = None,
         strict: bool = False) -> tuple[bytes, list[str]]:
    """Cook the glTF animation onto ``template_payload`` (a shipped clip).

    Returns ``(payload, notes)``. A template bone the glTF does not animate
    keeps its first template key as a constant pose (listed in ``notes``);
    with ``strict`` that is an error. A glTF bone the template does not have
    is an error: the skeleton would have no joint to drive.
    """
    tpl = A.parse_payload(template_payload)
    src = read_gltf_animation(glb, name)
    names = {t.name for t in tpl.tracks}
    unknown = sorted(set(src) - names)
    if unknown:
        raise AnimCookError(f"glTF animates bone(s) the target skeleton lacks: {unknown[:8]}")
    duration = max((t for ch in src.values() for keys in ch.values() for t, _ in keys),
                   default=0.0)
    if duration <= 0:
        raise AnimCookError("animation has no duration (all keys at t=0)")
    # A clip's stored length is not always its last key time (60% of shipped
    # clips stop keying before the end), so a glb from our own exporter carries
    # the real length in extras; keys added past it extend the clip.
    declared = declared_duration(glb, name)
    if declared and declared > duration - 1e-6:
        duration = declared

    notes: list[str] = []
    tracks = []
    for tr in tpl.tracks:
        ch = src.get(tr.name, {})
        new = replace(tr, duration=duration)
        for path, tattr, vattr, quant, same, dec in (
                ("translation", "t_times", "t_values", quant_ts, lambda a, b: a == b,
                 A._decode_trans_scale),
                ("rotation", "r_times", "r_values", quant_quat, _same_rotation, A._decode_quat),
                ("scale", "s_times", "s_values", quant_ts, lambda a, b: a == b,
                 A._decode_trans_scale)):
            keys = ch.get(path)
            if keys is None:
                old = getattr(tr, vattr)
                if not old:
                    continue
                if strict:
                    raise AnimCookError(f"{tr.name}.{path} is not animated in the glTF")
                notes.append(f"{tr.name}.{path}: not in glTF, held at the template's first key")
                keys = [(0.0, dec(old[0]))]
            keys = sorted(keys, key=lambda k: k[0])
            times, vals = _stream(keys, getattr(tr, tattr), getattr(tr, vattr),
                                  duration, quant, same)
            new = replace(new, **{tattr: times, vattr: vals})
        tracks.append(new)

    five = list(tpl.five_f32)
    if abs(five[1] - tpl.duration) < 1e-4:
        five[1] = duration
    frame_step = duration if abs(tpl.frame_step - tpl.duration) < 1e-4 else tpl.frame_step
    out = replace(tpl, tracks=tracks, five_f32=tuple(five), frame_step=frame_step)
    return A.emit_payload(out), notes


def declared_duration(glb: bytes, name: str | None = None) -> float | None:
    """The clip length our exporters recorded, if any: per-animation
    ``extras.rsmm.duration`` (character export) or the file-level
    ``extras.rsmm.decoded.duration`` (single-clip export)."""
    doc, _ = _read_glb(glb)
    anims = doc.get("animations") or []
    anim = next((a for a in anims if a.get("name") == name), None) if name else \
        (anims[0] if anims else None)
    d = (((anim or {}).get("extras") or {}).get("rsmm") or {}).get("duration")
    if d is None:
        d = (((doc.get("extras") or {}).get("rsmm") or {}).get("decoded") or {}).get("duration")
    return float(d) if isinstance(d, (int, float)) and d > 0 else None


def embedded_template(glb: bytes) -> bytes | None:
    """The original cooked payload our exporter embedded, if any."""
    try:
        return A._extract_raw_payload_from_glb(glb)
    except ValueError:
        return None
