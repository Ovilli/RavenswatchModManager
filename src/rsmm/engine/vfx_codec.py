"""The VFX format (``*.vfx.ot.ScheduledVfxSettings.gen``): decode a shipped
effect into plain values and write one from values, byte for byte.

A cooked effect is an object graph (``cooked``): section 0 lists each
object's class, one section per object, and the root (``oCScheduledVfxSettings``)
last. Each object's bytes are what its class's ``Serialize`` writes, parents
first, through the serializer's stream calls (vtable offsets on the stream):

* ``+0x70`` one byte, ``+0x78`` a float, ``+0x90``/``+0x98`` a u32,
  ``+0x60`` a string (u32 length + bytes), ``+0xa0`` an INLINE object
  (``MARK_BEGIN``, u32 class index, its body, ``MARK_END``), and the
  pointer-vector helper (``FUN_140207bd0``) a u32 count + that many object ids.

Each class below is ONE function used both ways (``_Io`` reads into a dict or
writes from it), transcribed from its ``Serialize`` with every version gate
resolved against the class table's version (the serializer's
``GetClassVersion``), so the reader and the writer cannot drift apart.
Addresses are the b9c3642884a8 build's ``Serialize`` (vtable slot 3).
``tests/test_vfx_codec.py`` re-encodes every shipped effect byte for byte.

A class without a function here is kept as its raw bytes (an object section)
or, inline, as the raw bytes between its markers: a shipped effect always
round-trips; only the classes listed can be WRITTEN from values.
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from dataclasses import dataclass, field

from . import cooked

_B, _E = cooked.MARK_BEGIN, cooked.MARK_END


class VfxError(ValueError):
    pass


@dataclass
class Obj:
    """One object: its class and its fields (``raw`` for a class the codec
    does not know). Inline objects nest as ``Obj`` values in ``fields``."""
    cls: str
    fields: dict = field(default_factory=dict)
    raw: bytes | None = None


class _Io:
    """A read or a write over one object body, driven by a class function."""

    def __init__(self, names: list[str], versions: dict[str, int], data: bytes | None = None):
        self.names, self.versions = names, versions
        self.reading = data is not None
        self.b = data or b""
        self.o = 0
        self.out = bytearray()
        self.d: dict = {}

    # -- versions --
    def ver(self, cls: str) -> int:
        return self.versions[cls]

    # -- primitives --
    def _prim(self, name: str, fmt: str):
        n = struct.calcsize(fmt)
        if self.reading:
            if self.o + n > len(self.b):
                raise VfxError(f"{name}: past the end")
            (v,) = struct.unpack_from(fmt, self.b, self.o)
            self.o += n
            self.d[name] = v
        else:
            self.out += struct.pack(fmt, self.d[name])
        return self.d[name]

    def u8(self, name: str):
        return self._prim(name, "<B")

    def u32(self, name: str):
        return self._prim(name, "<I")

    def f32(self, name: str):
        return self._prim(name, "<f")

    def floats(self, name: str, n: int):
        if self.reading:
            if self.o + 4 * n > len(self.b):
                raise VfxError(f"{name}: past the end")
            self.d[name] = list(struct.unpack_from(f"<{n}f", self.b, self.o))
            self.o += 4 * n
        else:
            v = self.d[name]
            if len(v) != n:
                raise VfxError(f"{name}: {n} numbers, got {len(v)}")
            self.out += struct.pack(f"<{n}f", *v)
        return self.d[name]

    def str(self, name: str):
        if self.reading:
            (n,) = struct.unpack_from("<I", self.b, self.o)
            if self.o + 4 + n > len(self.b):
                raise VfxError(f"{name}: string past the end")
            self.d[name] = self.b[self.o + 4:self.o + 4 + n].decode("latin-1")
            self.o += 4 + n
        else:
            s = self.d[name].encode("latin-1")
            self.out += struct.pack("<I", len(s)) + s
        return self.d[name]

    def words(self, name: str, n: int):
        """``n`` u32 words kept as they are (fields not named yet)."""
        if self.reading:
            if self.o + 4 * n > len(self.b):
                raise VfxError(f"{name}: past the end")
            self.d[name] = list(struct.unpack_from(f"<{n}I", self.b, self.o))
            self.o += 4 * n
        else:
            self.out += struct.pack(f"<{n}I", *self.d[name])
        return self.d[name]

    def sub(self, name: str, fn) -> dict:
        """A nested structure written by a direct call (no markers)."""
        if self.reading:
            inner = _Io(self.names, self.versions, self.b)
            inner.o = self.o
            fn(inner)
            self.o = inner.o
            self.d[name] = inner.d
        else:
            inner = _Io(self.names, self.versions)
            inner.d = self.d[name]
            fn(inner)
            self.out += inner.out
        return self.d[name]

    def ids(self, name: str):
        """A pointer vector: u32 count, then that many object ids."""
        if self.reading:
            (n,) = struct.unpack_from("<I", self.b, self.o)
            self.d[name] = list(struct.unpack_from(f"<{n}I", self.b, self.o + 4))
            self.o += 4 + 4 * n
        else:
            v = self.d[name]
            self.out += struct.pack(f"<I{len(v)}I", len(v), *v)
        return self.d[name]

    def obj(self, name: str):
        """An inline object (MARK_BEGIN, class index, body, MARK_END)."""
        if self.reading:
            if self.b[self.o:self.o + 4] != _B:
                raise VfxError(f"{name}: no inline object at {self.o}")
            (ci,) = struct.unpack_from("<I", self.b, self.o + 4)
            cls = self.names[ci]
            fn = CLASSES.get(cls)
            if fn is None:
                end = _match_end(self.b, self.o)
                self.d[name] = Obj(cls, raw=self.b[self.o + 8:end])
                self.o = end + 4
            else:
                sub = _Io(self.names, self.versions, self.b)
                sub.o = self.o + 8
                fn(sub)
                if self.b[sub.o:sub.o + 4] != _E:
                    raise VfxError(f"{name} ({cls}): body did not end at its marker "
                                   f"({sub.o})")
                self.d[name] = Obj(cls, sub.d)
                self.o = sub.o + 4
        else:
            v: Obj = self.d[name]
            self.out += _B + struct.pack("<I", self.names.index(v.cls))
            if v.raw is not None:
                self.out += v.raw
            else:
                sub = _Io(self.names, self.versions)
                sub.d = v.fields
                CLASSES[v.cls](sub)
                self.out += sub.out
            self.out += _E
        return self.d[name]


def _match_end(b: bytes, at: int) -> int:
    """Offset of the MARK_END closing the inline object opening at ``at``."""
    depth, o = 0, at
    while o < len(b) - 3:
        w = b[o:o + 4]
        if w == _B:
            depth += 1
            o += 8                           # the marker and its class index
            continue
        if w == _E:
            depth -= 1
            if depth == 0:
                return o
            o += 4
            continue
        o += 1
    raise VfxError(f"no end for the inline object at {at}")


# ---- classes ------------------------------------------------------------------
# Each takes an _Io; parents first, as their Serialize calls them.

CLASSES: dict[str, Callable[[_Io], None]] = {}


def _cls(name: str):
    def reg(fn):
        CLASSES[name] = fn
        return fn
    return reg


def _vec(io: _Io, name: str, n: int) -> None:
    io.floats(name, n)


# root -------------------------------------------------------------------------

def _root(io: _Io) -> None:
    """oCScheduledVfxSettings (0x1406ba710), after oIResource's u32."""
    io.u32("resource")
    io.obj("settings")                    # oCVisualEffectSettings: the effect's settings
    io.obj("cinematic")                   # oCCinematic: when each plays
    if io.ver("oCScheduledVfxSettings") != 0:
        io.u8("flag_170")
    if io.ver("oCScheduledVfxSettings") >= 2:
        io.f32("value_174")


@_cls("oCVisualEffectSettings")
def _settings(io: _Io) -> None:
    """oIRsSettingsGroup (0x14048b190): the group's settings objects."""
    io.ids("items")


for _c in ("oCParticleModifiersSettings", "oCParticleEmittersSettings",
           "oCParticleRenderersSettings", "oCTrailModifiersSettings",
           "oCTrailEmittersSettings", "oCTrailRenderersSettings",
           "oCBeamModifiersSettings", "oCBeamEmittersSettings", "oCBeamRenderersSettings"):
    CLASSES[_c] = _settings


@_cls("oCCinematic")
def _cinematic(io: _Io) -> None:
    """0x1406cf8a0: its blocs, its length, a byte (v>=2)."""
    io.ids("blocs")
    if io.ver("oCCinematic") != 0:
        io.f32("length")
    if io.ver("oCCinematic") >= 2:
        io.u8("flag_1c")


def _cine_bloc(io: _Io) -> None:
    """oICineBloc (0x1406cfcd0): start, a byte, a name, a u32."""
    v = io.ver("oICineBloc")
    io.f32("start")
    if v != 0:
        io.u8("flag_28")
    if 1 < v < 4:
        io.str("name")
    if v > 3:
        io.str("name")
    if v >= 3:
        io.u32("track")


def _vis_setting(io: _Io) -> None:
    """oIVisualEffectSetting (0x14059dbf0): its name (what blocs play)."""
    if io.ver("oIVisualEffectSetting") != 0:
        io.str("name")


# timeline blocs (objects) -------------------------------------------------------

@_cls("oCVfxControlCineBloc")
def _control_bloc(io: _Io) -> None:
    """0x140692a70: plays the setting ``target`` from ``start`` for ``duration``."""
    _cine_bloc(io)
    io.f32("duration")
    io.str("target")
    if io.ver("oCVfxControlCineBloc") != 0:
        io.u8("flag_50")


# particles ----------------------------------------------------------------------

@_cls("oCVisualEffectParticleSetting")
def _particle_setting(io: _Io) -> None:
    """0x14059caa0: a named particle system."""
    _vis_setting(io)
    io.obj("effect")


@_cls("oC3dParticleEffectSetting")
def _particle_effect(io: _Io) -> None:
    """0x14059f980: modifiers, emitters, renderers (inline lists of object ids)."""
    v = io.ver("oC3dParticleEffectSetting")
    if v == 0:
        io.u8("legacy_0")
    io.obj("modifiers")
    io.obj("emitters")
    io.obj("renderers")
    if v > 1:
        io.u8("flag_68")
    if v > 2:
        io.u32("value_70")
    if v >= 5:
        io.u32("mode_6c")                 # 0..1
    elif v > 3:
        io.u8("mode_6c")
    if v > 6:
        io.u8("flag_69")
    if v == 7:
        _vec(io, "legacy_7", 3)


def _ramp(io: _Io) -> None:
    """FUN_1404ec140: a colour ramp, keys of (t, r, g, b, a) between t0 and t1."""
    io.u32("head")
    io.f32("t0")
    io.f32("t1")
    if io.reading:
        (n,) = struct.unpack_from("<I", io.b, io.o)
        io.o += 4
        keys = []
        for _ in range(n):
            keys.append(list(struct.unpack_from("<5f", io.b, io.o)))
            io.o += 20
        io.d["keys"] = keys
    else:
        keys = io.d["keys"]
        io.out += struct.pack("<I", len(keys))
        for k in keys:
            io.out += struct.pack("<5f", *k)


def _curve(io: _Io) -> None:
    """FUN_1403669d0: a float curve: its mode, its keys (FUN_1404f9f20: each
    t, value, in-handle (t, v), out-handle (t, v), a byte, a u32), two bytes,
    then by mode a (lo, hi) range and a step."""
    mode = io.u32("mode")
    if io.reading:
        (n,) = struct.unpack_from("<I", io.b, io.o)
        io.o += 4
        keys = []
        for _ in range(n):
            f = list(struct.unpack_from("<6f", io.b, io.o))
            b, u = struct.unpack_from("<BI", io.b, io.o + 24)
            keys.append([*f, b, u])
            io.o += 29
        io.d["keys"] = keys
    else:
        keys = io.d["keys"]
        io.out += struct.pack("<I", len(keys))
        for k in keys:
            io.out += struct.pack("<6fBI", *k[:6], int(k[6]), int(k[7]))
    io.u8("flag_8")
    io.u8("flag_9")
    if mode:
        _vec(io, "range", 2)
    if mode >= 2:
        io.f32("step")


def _color_block(io: _Io, cls: str) -> None:
    """FUN_140588a20: a colour over life (start, end, or a ramp)."""
    v = io.ver(cls)
    if v > 0xd:
        io.u32("color_u32")
    io.u32("color_kind")                  # 0..3
    mode = io.u32("color_mode") if v >= 0xe else 0
    _vec(io, "color_start", 4)
    _vec(io, "color_end", 4)
    if mode >= 2:
        io.sub("color_ramp", _ramp)


def _emitter_base(io: _Io) -> None:
    """oI3dParticleEmitterSetting (0x140617be0)."""
    cls = "oI3dParticleEmitterSetting"
    v = io.ver(cls)
    io.f32("value_14")
    io.u8("flag_20")
    if v != 0:
        io.u32("value_18")
    if v > 1:
        _vec(io, "range_8", 2)
    if v == 3:
        _vec(io, "legacy_3", 3)
    if 5 <= v <= 7:
        _vec(io, "legacy_5", 3)
    if v > 5:
        io.u32("max_1c")
    if v > 6:
        io.f32("value_c0")
        io.u8("flag_21")
    if 8 <= v <= 10:
        _vec(io, "legacy_8", 4)
    if v > 7:
        _vec(io, "range_80", 2)
        _vec(io, "range_88", 2)
    if v < 0xd:
        if v == 0xc or v > 8:
            _vec(io, "legacy_c", 2)
    else:
        io.words("rate_90", 7)            # an object with its own Serialize
    if v > 10:
        if v == 0xb:
            _vec(io, "legacy_b", 8)
        else:
            _color_block(io, cls)
    if v >= 0xe:
        io.u8("flag_10")


@_cls("oC3dParticleEmitterSettings")
def _emitter(io: _Io) -> None:
    """0x140619a40: the base's fields, then the shape (``shape`` 0..6 and six
    numbers), directions, speed and the like."""
    _emitter_base(io)
    v = io.ver("oC3dParticleEmitterSettings")
    io.f32("value_cc")
    io.f32("value_d0")
    io.f32("value_d4")
    _vec(io, "vec_d8", 3)
    io.u32("shape")                       # 0..6
    _vec(io, "shape_104", 6)
    io.f32("value_11c")
    io.f32("value_120")
    io.u8("flag_124")
    if v == 1:
        io.f32("legacy_1")
    _vec(io, "vec_e4", 3)
    io.u8("flag_125")
    io.f32("value_100")
    io.u8("flag_126")
    if v != 0:
        _vec(io, "color_f0", 4)


# effectors (objects, in a modifiers list) ------------------------------------------

def _effector(io: _Io) -> None:
    """oI3dParticleEffectorSetting (0x1404ea170): its on switch."""
    io.u8("enabled")


@_cls("oC3dParticleEffectorSizeRampSettings")
def _size_ramp(io: _Io) -> None:
    """0x14061f3e0 (v>=3): size over life (a curve), a scale, a second curve,
    a byte."""
    _effector(io)
    v = io.ver("oC3dParticleEffectorSizeRampSettings")
    if v < 3:
        raise VfxError("size ramp below v3 is not supported")
    io.sub("size", _curve)
    io.f32("scale")
    io.sub("size_2", _curve)
    io.u8("flag_5c")


@_cls("oC3dParticleEffectorColorRampSettings")
def _color_ramp(io: _Io) -> None:
    """0x14061efd0: colour over life (a ramp), a u32 (v>=1)."""
    _effector(io)
    io.sub("ramp", _ramp)
    if io.ver("oC3dParticleEffectorColorRampSettings") != 0:
        io.u32("value_38")


@_cls("oC3dParticleEffectorAlphaRampSettings")
def _alpha_ramp(io: _Io) -> None:
    """0x14061ff80 (v>=3): opacity over life (a curve), then a byte, a u32
    pair (FUN_14032a140), the byte again and a u32 (v>=4)."""
    _effector(io)
    v = io.ver("oC3dParticleEffectorAlphaRampSettings")
    if v < 3:
        raise VfxError("alpha ramp below v3 is not supported")
    io.sub("alpha", _curve)
    io.u8("flag_68")
    io.words("pair_60", 2)
    io.u8("flag_68b")                     # read again, as the serializer does
    if v >= 4:
        io.u32("value_6c")


@_cls("oC3dParticleEffectorSubImageIndexSettings")
def _sub_image(io: _Io) -> None:
    """0x1406206a0 (v>=4): which frame of a flipbook texture, over life (a
    curve); its grid (u32 pairs) and rate."""
    _effector(io)
    v = io.ver("oC3dParticleEffectorSubImageIndexSettings")
    if v < 4:
        raise VfxError("sub-image below v4 is not supported")
    io.sub("frame", _curve)
    io.f32("value_local")
    io.words("grid_60", 2)
    io.u32("mode_10")
    io.words("pair_6c", 2)
    if v >= 5:
        io.f32("rate_68")


@_cls("oC3dParticleEffectorDampingSettings")
def _damping(io: _Io) -> None:
    """0x1406216c0 (v>=3): slows particles: three switches and a curve."""
    _effector(io)
    if io.ver("oC3dParticleEffectorDampingSettings") < 3:
        raise VfxError("damping below v3 is not supported")
    io.u8("flag_58")
    io.u8("flag_59")
    io.u8("flag_5a")
    io.sub("damping", _curve)


@_cls("oC3dParticleEffectorCameraOffsetSettings")
def _camera_offset(io: _Io) -> None:
    """pushes particles toward the camera: three numbers."""
    _effector(io)
    _vec(io, "offset", 3)


def _simple(cls: str, *fields: tuple[str, str], doc: str = "") -> None:
    """An effector whose Serialize is its on switch then fixed fields."""
    def fn(io: _Io) -> None:
        _effector(io)
        for name, kind in fields:
            if kind == "f":
                io.f32(name)
            elif kind == "b":
                io.u8(name)
            elif kind == "u":
                io.u32(name)
    fn.__doc__ = doc
    CLASSES[cls] = fn


_simple("oC3dParticleEffectorOrientWithSpeedSettings", ("value_10", "f"), ("value_14", "f"),
        ("flag_18", "b"), doc="turns particles along their flight")
_simple("oC3dParticleEffectorSelfRotateSettings", ("speed_min", "f"), ("speed_max", "f"),
        doc="spins each particle")


# renderers (objects, in a renderers list) ------------------------------------------

def _renderer(io: _Io) -> None:
    """oI3dParticleRendererSetting (0x140627240): on, a flag, a sort value."""
    v = io.ver("oI3dParticleRendererSetting")
    io.u8("enabled")
    if v > 1:
        io.u8("flag_9")
    if v >= 2:
        io.f32("sort_c")


def _resource(io: _Io, name: str) -> None:
    """FUN_1401c1900: a resource as its root and path (``FX``, ``Textures\\x.png``)."""
    io.str(f"{name}_root")
    io.str(name)


@_cls("oI3dBillboardParticleRendererSettings")
def _billboard(io: _Io) -> None:
    """0x140627630: camera-facing quads drawn with a material; its blend mode
    (0..4) and a (u, v) pair."""
    _renderer(io)
    v = io.ver("oI3dBillboardParticleRendererSettings")
    if v == 0:
        raise VfxError("billboard v0 is not supported")
    _resource(io, "material")
    if v > 1:
        io.u32("blend")
    if v > 2:
        _vec(io, "uv_4c", 2)


# ---- files ------------------------------------------------------------------------

@dataclass
class Vfx:
    cf: cooked.CookedFile
    objects: list[Obj]
    root: Obj

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.cf.classes]


def _versions(cf: cooked.CookedFile) -> dict[str, int]:
    return {c.name: c.version_minor for c in cf.classes}


def decode(raw: bytes) -> Vfx:
    cf = cooked.parse(raw)
    names, versions = [c.name for c in cf.classes], _versions(cf)
    table = cf.sections[0].payload
    (n,) = struct.unpack_from("<I", table, 0)
    objects = []
    for k in range(n):
        payload = cf.sections[k + 1].payload
        (ci,) = struct.unpack_from("<I", payload, 0)
        cls = names[ci]
        fn = CLASSES.get(cls)
        if fn is None:
            objects.append(Obj(cls, raw=bytes(payload[4:])))
            continue
        io = _Io(names, versions, bytes(payload))
        io.o = 4
        fn(io)
        if io.o != len(payload):
            raise VfxError(f"object {k} ({cls}): {len(payload) - io.o} bytes unread")
        objects.append(Obj(cls, io.d))
    payload = bytes(cf.sections[-1].payload)
    io = _Io(names, versions, payload)
    _root(io)
    if io.o != len(payload):
        raise VfxError(f"root: {len(payload) - io.o} bytes unread")
    return Vfx(cf, objects, Obj(names[0], io.d))


def encode(v: Vfx) -> bytes:
    names, versions = v.names, _versions(v.cf)
    table = struct.pack("<I", len(v.objects)) + b"".join(
        struct.pack("<I", names.index(o.cls)) for o in v.objects)
    sections = [cooked.Section(table)]
    for o in v.objects:
        head = struct.pack("<I", names.index(o.cls))
        if o.raw is not None:
            sections.append(cooked.Section(head + o.raw))
            continue
        io = _Io(names, versions)
        io.d = o.fields
        CLASSES[o.cls](io)
        sections.append(cooked.Section(head + bytes(io.out)))
    io = _Io(names, versions)
    io.d = v.root.fields
    _root(io)
    sections.append(cooked.Section(bytes(io.out)))
    v.cf.sections = sections
    return cooked.emit(v.cf)


__all__ = ["CLASSES", "Obj", "Vfx", "VfxError", "decode", "encode"]
