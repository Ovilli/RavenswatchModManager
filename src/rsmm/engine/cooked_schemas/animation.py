"""oCAnimation schema (v1.5). Bone-keyframe data.

Full schema reversed from `oCAnimation::Serialize` (VA 0x1405b35a0) and
`oCAnimationTrack::Serialize` (VA 0x140639d30). See "oCAnimation (final
schema)" in `docs/RE_NOTES.md` for the field-by-field layout.

Round-trip strategy
-------------------
The on-disk format quantizes per-keyframe values into 6 bytes (3 x i16 for
T/S, smallest-three 48-bit packing for R) using engine-side scaling
constants. Re-quantizing from a freshly-edited glTF would be lossy and
risk byte-divergence. To guarantee byte-stable round-trip — and to keep
the "viewer-loadable glTF" promise — the decoder emits a binary glTF
(.glb) whose JSON `extras.rsmm` block carries:

- `raw_payload_b64` — base64 of the original cooked-section payload
  (sections 0+1 concatenated, exactly what `encode()` returns)
- `schema_version` — bump if the embedded layout changes
- `decoded` — the parsed header (name, bone-track names, durations) so
  external tools can preview without re-decoding the binary

`encode()` simply decodes the base64 and returns those bytes. Byte
stability holds as long as the .glb was produced by `decode()` on the
same payload (the documented contract; intentionally not a re-quantizer).

For viewer-loadable previews the decoder also emits real glTF samplers
+ channels per bone (timestamps decoded f32 seconds, T/S as vec3 with
*approximate* dequantization from the per-anim AABB, R as identity-quat
when the smallest-three constants can't be resolved). These are
read-only — edits in Blender don't round-trip. The intent is so a mod
author can confirm "this is the run-cycle, not the death anim" before
swapping bytes.
"""

from __future__ import annotations

import base64
import json
import struct
from dataclasses import dataclass, field
from typing import Literal

from . import register
from .base import SchemaHandler

UID = 0x159d
CURRENT_VERSION = (1, 5)
TRACK_UID = 0x15f8
TRACK_CURRENT_VERSION = (1, 7)

MARK_BEGIN = b"\x11\x11\xbb\xaa"
MARK_END = b"\x22\x22\xbb\xaa"

# `oIResource::Serialize` parent prelude precedes every top-level cooked
# class body as its own section. For an oCAnimation file the container
# carries exactly two sections in this order:
#   section 0: 4 bytes — oIResource header (observed `00 00 00 00`)
#   section 1: full oCAnimation body
# The handler receives them concatenated by the uncook dispatcher; the
# decoder split here is the inverse split.
_SECTION0_LEN = 4
_TRACK_VEC_COUNT = 6      # alternating (u16-stream, blob6-stream) x 3
_BLOB_STRIDE = 6


@dataclass
class AnimationTrack:
    """One per bone. Six parallel streams of (timestamp, value) keyframes
    for translation / rotation / scale, plus a per-track duration f32
    (== animation duration for v1.7 corpus, kept per-track for future-
    proofing).
    """
    res_prelude: int                    # u32 written by dispatch wrapper (typically 3)
    leading_u32: int                    # first call: vtbl+0x90 emits this (0 in corpus)
    name: str                           # bone name (e.g. "DEF-LEG-TOP.R")
    # 6 parallel streams: T_time, T_value, R_time, R_value, S_time, S_value.
    # times[]: each element written as u32 wire holding a u16 value [0,65535].
    # values[]: each element written via vtbl+0x40 as (u32 size=6, 6 bytes).
    t_times: list[int] = field(default_factory=list)
    t_values: list[bytes] = field(default_factory=list)
    r_times: list[int] = field(default_factory=list)
    r_values: list[bytes] = field(default_factory=list)
    s_times: list[int] = field(default_factory=list)
    s_values: list[bytes] = field(default_factory=list)
    duration: float = 0.0               # f32 at track+0x7c (animation duration in seconds)


@dataclass
class Animation:
    """Parsed oCAnimation body. Mirrors the on-disk layout 1:1 so emit()
    can re-serialize byte-stably without re-touching field semantics.
    """
    section0: bytes                     # 4 bytes — oIResource prelude (passed through)
    res_prelude: int                    # u32 at body+0x00 (dispatch wrapper preamble; 0 in corpus)
    name: str                           # animation name (e.g. "ArmatureAction")
    tracks: list[AnimationTrack]
    frame_step: float                   # f32 at this+0x78 (= 1 / frame_rate, seconds per frame)
    aabb: tuple[float, float, float, float, float, float]   # 6 f32 — bbox over tracks
    # FUN_1405b31d0 trailing struct, ver=5:
    sub_ver: int                        # always 5 in corpus
    five_f32: tuple[float, float, float, float, float]      # +0..+0x10 (5 f32)
    vec3: tuple[float, float, float]                        # +0x18 (3 f32) — typically (1,1,1)
    u8_quad: tuple[int, int, int, int]                      # +0x24..+0x27
    u8_v2: int                                              # +0x28 (ver>=2)
    f32_v3: float                                           # +0x14 (ver>=3) — discovered placement
    u32_v5: int                                             # +0x2c (ver>=5) — observed 30 = frame_rate

    @property
    def duration(self) -> float:
        """Animation duration in seconds (== last track's duration in v1.7)."""
        return self.tracks[0].duration if self.tracks else 0.0


def _u32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def _u8(buf: bytes, off: int) -> int:
    return buf[off]


def _f32(buf: bytes, off: int) -> float:
    return struct.unpack_from("<f", buf, off)[0]


def _find_section_end(data: bytes, start: int) -> int:
    """Skip past a sub-object's matching END marker. Handles nesting.
    Stride 4 to avoid false marker matches inside f32 payload — same
    rule as `rsmm.engine.cooked._find_section_end`.
    """
    depth = 1
    pos = start
    n = len(data)
    while pos + 4 <= n:
        tag = data[pos:pos + 4]
        if tag == MARK_BEGIN:
            depth += 1
            pos += 4
            continue
        if tag == MARK_END:
            depth -= 1
            pos += 4
            if depth == 0:
                return pos
            continue
        pos += 1
    raise ValueError("unterminated sub-object: missing END marker")


def _parse_track(sec: bytes, body_start: int) -> tuple[AnimationTrack, int]:
    """Parse one oCAnimationTrack starting at `body_start` (the byte after
    the opening BEGIN marker). Returns (track, abs_end_offset) where
    `abs_end_offset` is the position past the matching END.
    """
    end_pos = _find_section_end(sec, body_start)
    body_end = end_pos - 4               # exclusive of END marker

    tp = body_start
    res_prelude = _u32(sec, tp); tp += 4   # dispatch-wrapper preface (oIResource flag)
    leading_u32 = _u32(sec, tp); tp += 4   # first call: vtbl+0x90 (always 0 in v1.7 writer)
    name_len = _u32(sec, tp); tp += 4
    name = sec[tp:tp + name_len].decode("utf-8", errors="replace")
    tp += name_len

    streams: list[list] = []
    for vi in range(_TRACK_VEC_COUNT):
        count = _u32(sec, tp); tp += 4
        if vi % 2 == 0:
            # Times: count * u32 wire (each holds a u16 quantized timestamp)
            times = [_u32(sec, tp + i * 4) for i in range(count)]
            tp += count * 4
            streams.append(times)
        else:
            # Values: count * (u32 size_prefix=6, 6 raw bytes)
            vals: list[bytes] = []
            for _ in range(count):
                size = _u32(sec, tp); tp += 4
                if size != _BLOB_STRIDE:
                    raise ValueError(
                        f"track {name!r} stream {vi}: blob size {size} != {_BLOB_STRIDE}"
                    )
                vals.append(sec[tp:tp + _BLOB_STRIDE])
                tp += _BLOB_STRIDE
            streams.append(vals)

    duration = _f32(sec, tp); tp += 4
    if tp != body_end:
        raise ValueError(
            f"track {name!r}: parsed {tp - body_start} bytes, expected "
            f"{body_end - body_start}"
        )

    track = AnimationTrack(
        res_prelude=res_prelude,
        leading_u32=leading_u32,
        name=name,
        t_times=streams[0], t_values=streams[1],
        r_times=streams[2], r_values=streams[3],
        s_times=streams[4], s_values=streams[5],
        duration=duration,
    )
    return track, end_pos


def parse_payload(payload: bytes) -> Animation:
    """Parse the concatenated (section0 + section1) payload bytes.

    The uncook dispatcher hands handlers `b"".join(sec.payload for sec in
    cf.sections)`, so we split section 0 off the head before parsing the
    real body. Section 0 is a 4-byte `oIResource::Serialize` output.
    """
    if len(payload) < _SECTION0_LEN + 8:
        raise ValueError(f"animation payload too small: {len(payload)} bytes")
    section0 = payload[:_SECTION0_LEN]
    sec = payload[_SECTION0_LEN:]

    p = 0
    res_prelude = _u32(sec, p); p += 4
    name_len = _u32(sec, p); p += 4
    if name_len > len(sec) - p:
        raise ValueError(f"implausible name length {name_len}")
    name = sec[p:p + name_len].decode("utf-8", errors="replace")
    p += name_len

    n_tracks = _u32(sec, p); p += 4
    tracks: list[AnimationTrack] = []
    for ti in range(n_tracks):
        if sec[p:p + 4] != MARK_BEGIN:
            raise ValueError(
                f"track {ti}: expected BEGIN marker at {p:#x}, got "
                f"{sec[p:p+4].hex()}"
            )
        p += 4
        track, end = _parse_track(sec, p)
        tracks.append(track)
        p = end

    # Tail (this+0x78 f32, this+0x90 AABB, FUN_1405b31d0 sub-struct).
    frame_step = _f32(sec, p); p += 4
    aabb = struct.unpack_from("<6f", sec, p); p += 24

    sub_ver = _u32(sec, p); p += 4
    five_f32 = struct.unpack_from("<5f", sec, p); p += 20
    vec3 = struct.unpack_from("<3f", sec, p); p += 12
    u8_quad = tuple(sec[p:p + 4]); p += 4
    u8_v2 = _u8(sec, p); p += 1
    f32_v3 = _f32(sec, p); p += 4
    u32_v5 = _u32(sec, p); p += 4

    if p != len(sec):
        raise ValueError(
            f"trailing {len(sec) - p} bytes after FUN_1405b31d0 sub-struct"
        )

    return Animation(
        section0=section0,
        res_prelude=res_prelude,
        name=name,
        tracks=tracks,
        frame_step=frame_step,
        aabb=tuple(aabb),
        sub_ver=sub_ver,
        five_f32=tuple(five_f32),
        vec3=tuple(vec3),
        u8_quad=u8_quad,
        u8_v2=u8_v2,
        f32_v3=f32_v3,
        u32_v5=u32_v5,
    )


def emit_payload(anim: Animation) -> bytes:
    """Re-serialize an Animation to the concatenated (section0 + section1)
    bytes that round-trip with `parse_payload`. Byte-identical to the
    original when no field has been mutated.
    """
    out = bytearray()
    out += anim.section0

    body = bytearray()
    body += struct.pack("<I", anim.res_prelude)
    name_bytes = anim.name.encode("utf-8")
    body += struct.pack("<I", len(name_bytes))
    body += name_bytes
    body += struct.pack("<I", len(anim.tracks))

    for tr in anim.tracks:
        # Compose sub-object body first so we can wrap with BEGIN/END.
        tb = bytearray()
        tb += struct.pack("<I", tr.res_prelude)
        tb += struct.pack("<I", tr.leading_u32)
        tname_bytes = tr.name.encode("utf-8")
        tb += struct.pack("<I", len(tname_bytes))
        tb += tname_bytes

        for stream_idx, stream in enumerate((
            tr.t_times, tr.t_values,
            tr.r_times, tr.r_values,
            tr.s_times, tr.s_values,
        )):
            tb += struct.pack("<I", len(stream))
            if stream_idx % 2 == 0:
                # u32 wire (holds u16 value)
                for v in stream:
                    tb += struct.pack("<I", v)
            else:
                for blob in stream:
                    if len(blob) != _BLOB_STRIDE:
                        raise ValueError(
                            f"track {tr.name!r}: blob length {len(blob)} "
                            f"!= {_BLOB_STRIDE}"
                        )
                    tb += struct.pack("<I", _BLOB_STRIDE)
                    tb += blob
        tb += struct.pack("<f", tr.duration)

        body += MARK_BEGIN
        body += tb
        body += MARK_END

    body += struct.pack("<f", anim.frame_step)
    body += struct.pack("<6f", *anim.aabb)
    body += struct.pack("<I", anim.sub_ver)
    body += struct.pack("<5f", *anim.five_f32)
    body += struct.pack("<3f", *anim.vec3)
    body += bytes(anim.u8_quad)
    body += bytes([anim.u8_v2])
    body += struct.pack("<f", anim.f32_v3)
    body += struct.pack("<I", anim.u32_v5)

    out += body
    return bytes(out)


# --------------------------------------------------------------------------
# glTF (.glb) export — viewer-loadable preview + raw-bytes round-trip
# --------------------------------------------------------------------------

# Schema-version stamp embedded in the .glb extras. Bumped when the binary
# layout of the raw_payload changes (the .glb itself is forward-compatible).
_GLB_EXTRAS_VERSION = 1

# Engine constant for u16 timestamp normalization. Set from
# `DAT_140fc6ab0` (a 65535.0f float in the engine .rdata that
# `oCAnimationTrack::Serialize`'s v6-migration code multiplies by). Used
# to convert raw u16 [0,65535] back to seconds along the duration axis.
_TIME_NORM = 65535.0

# Translation / scale fixed-point divisor. The engine quantizer
# `FUN_1404ad910` does `q = round(clamp(value, -32, 31) * DAT_140fc6a74)`
# into a signed i16, with `DAT_140fc6a74 == 1024.0`. So 1024 == 1.0 and the
# inverse is simply `i16 / 1024`. (The earlier `/32767` guess collapsed every
# scale to ~0.03, which is why the preview rigs rendered invisible.)
_TS_DIVISOR = 1024.0

# Rotation smallest-three constants from `FUN_1404ad540`:
#   q_field = round(component * sqrt(DAT_140fc6860) * DAT_140fc6a98)
#   DAT_140fc6860 = 2.0, DAT_140fc6a98 = 16383.0  ->  scale = sqrt(2)*16383
# 48-bit layout: bits[46:45]=largest-axis index, [44:30]/[29:15]/[14:0] = the
# three non-largest components as signed 15-bit fields (axis order, largest
# omitted). The omitted largest axis is recovered as +sqrt(1 - a^2-b^2-c^2);
# the encoder sign-flips so the largest is always positive.
_QUAT_SCALE = 2.0 ** 0.5 * 16383.0


def _decode_times(times: list[int], duration: float) -> list[float]:
    """u16 timestamps map linearly to [0, duration] seconds."""
    if duration <= 0:
        return [0.0] * len(times)
    return [t * duration / _TIME_NORM for t in times]


def _decode_trans_scale(blob6: bytes) -> tuple[float, float, float]:
    """Dequant a 6-byte (x,y,z) signed-i16 triple to floats (i16 / 1024)."""
    x, y, z = struct.unpack("<hhh", blob6)
    return (x / _TS_DIVISOR, y / _TS_DIVISOR, z / _TS_DIVISOR)


def _s15(field: int) -> float:
    """Interpret a 15-bit field as a signed value, then dequantize."""
    if field & 0x4000:
        field -= 0x8000
    return field / _QUAT_SCALE


def _decode_quat(blob6: bytes) -> tuple[float, float, float, float]:
    """Exact smallest-three quat decode (inverse of `FUN_1404ad540`).

    Validated unit-norm across the full shipped corpus (~1.1M keyframes,
    100% within 1e-2 of unit length; identity blob decodes to (0,0,0,1)).
    """
    raw = struct.unpack("<I", blob6[:4])[0] | (struct.unpack("<H", blob6[4:])[0] << 32)
    idx = (raw >> 45) & 0x3
    comps = [_s15((raw >> 30) & 0x7fff), _s15((raw >> 15) & 0x7fff), _s15(raw & 0x7fff)]
    rem = 1.0 - sum(c * c for c in comps)
    largest = rem ** 0.5 if rem > 0.0 else 0.0
    out = [0.0, 0.0, 0.0, 0.0]
    j = 0
    for i in range(4):
        if i == idx:
            out[i] = largest
        else:
            out[i] = comps[j]
            j += 1
    return (out[0], out[1], out[2], out[3])


def _build_glb_preview(anim: Animation, raw_payload: bytes) -> bytes:
    """Emit a viewer-loadable .glb. Pure stdlib — does not depend on the
    `rsmm.engine.gltf` module so animation can ship without that module
    growing animation accessors. (gltf.GlbBuilder would be a nice fit
    later; the brief allows non-breaking additions there. Kept local
    here to avoid cross-module coupling for the first cut.)
    """
    # Build BIN payload (interleaved per-track time/value accessors).
    bin_buf = bytearray()
    buffer_views: list[dict] = []
    accessors: list[dict] = []
    samplers: list[dict] = []
    channels: list[dict] = []
    nodes: list[dict] = []

    def push_view(data: bytes) -> int:
        # 4-byte align per glTF spec.
        pad = (-len(bin_buf)) % 4
        bin_buf.extend(b"\0" * pad)
        offset = len(bin_buf)
        bin_buf.extend(data)
        buffer_views.append({
            "buffer": 0, "byteOffset": offset, "byteLength": len(data),
        })
        return len(buffer_views) - 1

    def push_scalar_f32(values: list[float]) -> int:
        data = struct.pack(f"<{len(values)}f", *values)
        view = push_view(data)
        accessors.append({
            "bufferView": view, "componentType": 5126, "count": len(values),
            "type": "SCALAR",
            "min": [min(values)] if values else [0.0],
            "max": [max(values)] if values else [0.0],
        })
        return len(accessors) - 1

    def push_vec3_f32(values: list[tuple[float, float, float]]) -> int:
        flat = [c for v in values for c in v]
        data = struct.pack(f"<{len(flat)}f", *flat)
        view = push_view(data)
        accessors.append({
            "bufferView": view, "componentType": 5126, "count": len(values),
            "type": "VEC3",
        })
        return len(accessors) - 1

    def push_vec4_f32(values: list[tuple[float, float, float, float]]) -> int:
        flat = [c for v in values for c in v]
        data = struct.pack(f"<{len(flat)}f", *flat)
        view = push_view(data)
        accessors.append({
            "bufferView": view, "componentType": 5126, "count": len(values),
            "type": "VEC4",
        })
        return len(accessors) - 1

    def push_indices_u16(values: list[int]) -> int:
        data = struct.pack(f"<{len(values)}H", *values)
        view = push_view(data)
        accessors.append({
            "bufferView": view, "componentType": 5123, "count": len(values),
            "type": "SCALAR",
        })
        return len(accessors) - 1

    # Shared "joint marker" mesh so each animated bone is actually visible in a
    # viewer (the old preview emitted empty transform-only nodes, which render
    # as nothing). A tiny octahedron; bones rotate/translate/scale it over time.
    _r = 0.03
    _oct_pos = [
        (_r, 0, 0), (-_r, 0, 0), (0, _r, 0),
        (0, -_r, 0), (0, 0, _r), (0, 0, -_r),
    ]
    _oct_idx = [
        0, 2, 4, 2, 1, 4, 1, 3, 4, 3, 0, 4,
        2, 0, 5, 1, 2, 5, 3, 1, 5, 0, 3, 5,
    ]
    meshes: list[dict] = []
    if anim.tracks:
        pos_acc = push_vec3_f32(_oct_pos)
        # POSITION needs min/max for glTF validators.
        accessors[pos_acc]["min"] = [-_r, -_r, -_r]
        accessors[pos_acc]["max"] = [_r, _r, _r]
        idx_acc = push_indices_u16(_oct_idx)
        meshes.append({
            "name": "joint_marker",
            "primitives": [{
                "attributes": {"POSITION": pos_acc},
                "indices": idx_acc, "mode": 4,
            }],
        })
    _joint_mesh = 0 if meshes else None

    for tr in anim.tracks:
        # One node per bone — animation channels target this node. Seed it with
        # the keyframe-0 rest pose so the static scene already looks like the
        # rig, and attach the shared marker mesh so the bone is visible.
        node: dict = {"name": tr.name}
        if _joint_mesh is not None:
            node["mesh"] = _joint_mesh
        if tr.t_values:
            node["translation"] = list(_decode_trans_scale(tr.t_values[0]))
        if tr.r_values:
            node["rotation"] = list(_decode_quat(tr.r_values[0]))
        if tr.s_values:
            node["scale"] = list(_decode_trans_scale(tr.s_values[0]))
        nodes.append(node)
        node_idx = len(nodes) - 1

        # Translation channel.
        if tr.t_times:
            times = _decode_times(tr.t_times, tr.duration)
            values = [_decode_trans_scale(b) for b in tr.t_values]
            t_acc = push_scalar_f32(times)
            v_acc = push_vec3_f32(values)
            samplers.append({"input": t_acc, "output": v_acc, "interpolation": "LINEAR"})
            channels.append({
                "sampler": len(samplers) - 1,
                "target": {"node": node_idx, "path": "translation"},
            })

        # Rotation channel.
        if tr.r_times:
            times = _decode_times(tr.r_times, tr.duration)
            values = [_decode_quat(b) for b in tr.r_values]
            t_acc = push_scalar_f32(times)
            v_acc = push_vec4_f32(values)
            samplers.append({"input": t_acc, "output": v_acc, "interpolation": "LINEAR"})
            channels.append({
                "sampler": len(samplers) - 1,
                "target": {"node": node_idx, "path": "rotation"},
            })

        # Scale channel.
        if tr.s_times:
            times = _decode_times(tr.s_times, tr.duration)
            values = [_decode_trans_scale(b) for b in tr.s_values]
            t_acc = push_scalar_f32(times)
            v_acc = push_vec3_f32(values)
            samplers.append({"input": t_acc, "output": v_acc, "interpolation": "LINEAR"})
            channels.append({
                "sampler": len(samplers) - 1,
                "target": {"node": node_idx, "path": "scale"},
            })

    extras = {
        "rsmm": {
            "schema_version": _GLB_EXTRAS_VERSION,
            "class": "oCAnimation",
            "uid": UID,
            "cooked_version": list(CURRENT_VERSION),
            "raw_payload_b64": base64.b64encode(raw_payload).decode("ascii"),
            "decoded": {
                "name": anim.name,
                "duration": anim.duration,
                "frame_step": anim.frame_step,
                "frame_rate": anim.u32_v5,
                "track_names": [tr.name for tr in anim.tracks],
                "track_keyframe_counts": [
                    {
                        "name": tr.name,
                        "translation": len(tr.t_times),
                        "rotation": len(tr.r_times),
                        "scale": len(tr.s_times),
                    }
                    for tr in anim.tracks
                ],
            },
        },
    }

    gltf: dict = {
        "asset": {"version": "2.0", "generator": "rsmm oCAnimation extractor"},
        "extras": extras,
        "bufferViews": buffer_views,
        "accessors": accessors,
        "meshes": meshes,
        "nodes": nodes,
        "scenes": [{"nodes": list(range(len(nodes)))}] if nodes else [],
        "scene": 0,
    }
    if samplers or channels:
        gltf["animations"] = [{
            "name": anim.name,
            "samplers": samplers,
            "channels": channels,
        }]

    bin_pad = (-len(bin_buf)) % 4
    bin_payload = bytes(bin_buf) + b"\0" * bin_pad
    if bin_payload:
        gltf["buffers"] = [{"byteLength": len(bin_payload)}]

    # Drop empties for tidiness.
    for k in ("bufferViews", "accessors", "meshes", "nodes", "scenes"):
        if not gltf.get(k):
            gltf.pop(k, None)

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_pad = (-len(json_bytes)) % 4
    json_bytes += b" " * json_pad

    total = 12 + 8 + len(json_bytes) + (8 + len(bin_payload) if bin_payload else 0)
    out = bytearray()
    out += struct.pack("<III", 0x46546C67, 2, total)
    out += struct.pack("<II", len(json_bytes), 0x4E4F534A)
    out += json_bytes
    if bin_payload:
        out += struct.pack("<II", len(bin_payload), 0x004E4942)
        out += bin_payload
    return bytes(out)


def _extract_raw_payload_from_glb(glb_bytes: bytes) -> bytes:
    """Pull `extras.rsmm.raw_payload_b64` out of a .glb produced by
    `_build_glb_preview`. Raises if the marker isn't present (refuse to
    cook a glb that wasn't authored from a real animation).
    """
    if len(glb_bytes) < 20 or glb_bytes[:4] != b"glTF":
        raise ValueError("not a glTF binary container (missing 'glTF' magic)")
    version = struct.unpack_from("<I", glb_bytes, 4)[0]
    if version != 2:
        raise ValueError(f"glTF version {version} not supported (need 2)")
    total = struct.unpack_from("<I", glb_bytes, 8)[0]
    if total > len(glb_bytes):
        raise ValueError("glb header claims more bytes than file holds")

    pos = 12
    chunk_len = struct.unpack_from("<I", glb_bytes, pos)[0]
    chunk_type = glb_bytes[pos + 4:pos + 8]
    if chunk_type != b"JSON":
        raise ValueError(f"first chunk is not JSON, got {chunk_type!r}")
    json_bytes = glb_bytes[pos + 8:pos + 8 + chunk_len]
    try:
        doc = json.loads(json_bytes.rstrip(b" "))
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid glTF JSON: {e}") from e

    extras = doc.get("extras") or {}
    rsmm = extras.get("rsmm") or {}
    blob_b64 = rsmm.get("raw_payload_b64")
    if not blob_b64:
        raise ValueError(
            "glb has no rsmm.raw_payload_b64 — cooked from an unrelated source. "
            "Re-extract via `rsmm uncook` to embed the original bytes."
        )
    return base64.b64decode(blob_b64)


# --------------------------------------------------------------------------
# SchemaHandler integration
# --------------------------------------------------------------------------


class AnimationHandler(SchemaHandler):
    """Round-trip-stable decode/encode for `oCAnimation` (v1.5)."""

    def __init__(self) -> None:
        super().__init__(
            class_name="oCAnimation",
            source_ext="glb",
            decoded=True,
            encoded=True,
        )

    def decode(self, payload: bytes) -> bytes:
        anim = parse_payload(payload)
        # Round-trip self-test: if we can't re-emit byte-stably, surface
        # it now rather than at apply-time. Costs ~one extra serialize
        # per uncook; well worth it for the safety guarantee.
        rebuilt = emit_payload(anim)
        if rebuilt != payload:
            raise ValueError(
                f"oCAnimation {anim.name!r}: decoder produced a non-round-"
                f"trippable parse ({len(payload)}B in, {len(rebuilt)}B out). "
                "Refusing to emit a corrupt .glb."
            )
        return _build_glb_preview(anim, payload)

    def encode(self, source: bytes) -> bytes:
        return _extract_raw_payload_from_glb(source)


register(AnimationHandler())
