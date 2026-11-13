"""A projectile written from data: an empty entity of the hero's own on the
engine's generic hero projectile, its slots filled from the shared base.

The way ``hero_frame`` writes a hero on ``Hero_Common`` instead of copying a
hero, this writes a projectile on ``Projectile_Model\\Hero_Projectile_Model``
(physics, hit, piercing, damage, despawn, network) instead of copying a shipped
projectile (the builder used to start from Red's ``Hero_Red_Projectile_Spike``
and keep its sounds). Every part it carries is one of the shared base's own
slots, overridden:

* ``Mesh``: the mod's cooked mesh and material, a size and a pitch (a model
  authored flying along +Y is turned onto the flight axis by a quarter turn
  about X, as every shipped thrown prop is);
* ``Projectile Attack Selector``: the piercing attack (passes through and hits
  each enemy once) or the plain one (stops at the first hit);
* ``Lifetime Duration``: seconds before it expires;
* ``Alive Fx Default`` / ``Impact Fx Default``: the effect it trails while
  flying and bursts with when it lands, each an ``oCEntityCpntFxSetup``
  sub-object naming one ``.vfx.ot`` (the trail's own written as a copy of the
  base's impact setup, flagged looping).

Byte layouts were read off the base and Red's spike (the only differences are
those fields); ``tests/test_projectile_frame.py`` holds them.
"""

from __future__ import annotations

import math
import struct

from . import cooked
from . import entity_fields as EF
from . import entity_parts as P
from . import hero_frame as HF
from .entity_graph_edit import EntityEditError, EntityFile

MODEL = "Projectile_Model\\Hero_Projectile_Model.entity.ot"
BASE = "Projectile_Model\\Projectile_Model.entity.ot"
#: The base's own impact effect (what a projectile with no impact of its own shows).
BASE_IMPACT = "Settings\\FX\\Common_FX\\Basic_Impact_01.vfx.ot"
_BASE_MESH, _BASE_MAT = "Shapes\\Sphere1.fbx", "Dt_GreyColor.mat.ot"
_SAMPLES = "samples"
#: A shipped thrown prop's mesh pitch (Red's spike: pi/2 about X) and size.
PITCH, SIZE = math.pi / 2, 1.5
FIELDS = {"model", "albedo", "mra", "normal", "scale", "lifetime", "trail", "impact",
          "pierce", "size", "pitch"}


class ProjectileError(ValueError):
    pass


def _value_field(ef: EntityFile, part: str, name: str) -> tuple[bytearray, int, int]:
    """(part bytes, start, size) of field ``name`` in ``part``."""
    c = ef.component(part)
    f = next((x for x in EF.fields(c) if x.name == name), None)
    if f is None:
        raise ProjectileError(f"{part!r} has no field {name!r}")
    p = ef.objects[c.index - 1]
    return p, len(p) - len(c.body) + f.offset, f.size


def _swap_resource(ef: EntityFile, part: str, old: tuple[str, str], new: tuple[str, str]) -> None:
    c = ef.component(part)
    p = ef.objects[c.index - 1]
    o = P._lstr(old[0]) + P._lstr(old[1])
    head = len(p) - len(c.body)
    at = c.body.find(o)
    if at < 0 or c.body.find(o, at + 1) >= 0:
        raise ProjectileError(f"{part!r}: no single {old[1]!r}")
    p[head + at:head + at + len(o)] = P._lstr(new[0]) + P._lstr(new[1])


#: A value picker's float sits 25 bytes in (begin, class, 00, begin, class,
#: type, unit); a transform group is a u32 "set" flag and four pickers (x, y,
#: z, then a vec3 one of 45 bytes): the second group is the euler rotation.
_PICK_F32, _GROUP = 37, 4 + 37 * 3 + 45


def _set_pitch(ef: EntityFile, radians: float) -> None:
    p, at, size = _value_field(ef, "Mesh", "obj_3")
    g2 = at + 8 + _GROUP                         # past the object head + translation
    if g2 + 4 + _PICK_F32 > at + size or p[g2 + 4:g2 + 8] != cooked.MARK_BEGIN:
        raise ProjectileError("the Mesh transform is not laid out as the base's")
    struct.pack_into("<I", p, g2, 1 if radians else 0)
    v = g2 + 4 + 25
    (t,) = struct.unpack_from("<I", p, v - 8)
    if t != 0:                                   # union type 0 = f32
        raise ProjectileError("the Mesh rotation X is not a float")
    struct.pack_into("<f", p, v, radians)


def _set_float(ef: EntityFile, part: str, name: str, value: float) -> None:
    p, at, size = _value_field(ef, part, name)
    if size != _PICK_F32 or struct.unpack_from("<I", p, at + 17)[0] != 0:
        raise ProjectileError(f"{part}.{name} is not a plain float")
    struct.pack_into("<f", p, at + 25, value)


def _fx_ids(ef: EntityFile, part: str) -> list[int]:
    p, at, _size = _value_field(ef, part, "bytes_1")
    (n,) = struct.unpack_from("<I", p, at)
    return list(struct.unpack_from(f"<{n}I", p, at + 4))


_M, _E = cooked.MARK_BEGIN, cooked.MARK_END


def _as_trail(obj: bytearray) -> None:
    """An impact setup turned into a trail's, the two differences between
    Red's spike's own pair: the impact's orientation reads the hit
    (``[Dt Damage] Projectile_Model\\Damage``) and its effect is drawn at
    scale 2; a trail has neither (flag 0, plain picker / 1.0)."""
    import re
    b = bytes(obj)
    # Both pickers that read the hit (position, then rotation): each made a
    # plain picker, the position's "set" flag before it cleared.
    linked = re.compile(rb"(\x01\x00\x00\x00)?" + re.escape(_M) + rb"(....)\x01\x00"
                        + re.escape(_M) + rb"....(.{16})(....)\[Dt Damage\] "
                        rb"Projectile_Model\\Damage" + re.escape(_E) + rb"....", re.S)
    hits = list(linked.finditer(b))
    if len(hits) != 2:
        raise ProjectileError(f"the impact setup reads the hit {len(hits)} times, not twice")
    for m in reversed(hits):
        flag = b"\x00\x00\x00\x00" if m.group(1) else b""
        b = b[:m.start()] + flag + _M + m.group(2) + b"\x00" + b[m.end():]
    scale = re.compile(re.escape(b"\x01\x00\x00\x00" + _M) + rb"(....)\x00" + re.escape(_M)
                       + rb"(....)\x00\x00\x00\x00\x00\x00\x00\x00" + re.escape(
                           struct.pack("<f", 2.0)), re.S)
    m = scale.search(b)
    if m is not None:                    # Red's impact; the base's draws at 1 already
        b = (b[:m.start()] + b"\x00\x00\x00\x00" + _M + m.group(1) + b"\x00" + _M + m.group(2)
             + bytes(8) + struct.pack("<f", 1.0) + b[m.end():])
    obj[:] = b


def _set_fx(ef: EntityFile, part: str, setup: int | None, vfx: str, *,
            looping: bool) -> None:
    """``part`` showing ``vfx``: its setup sub-object repointed, or, for a part
    with none (the base's trail), a copy of ``setup`` made its own."""
    ids = _fx_ids(ef, part)
    if not ids:
        if setup is None:
            raise ProjectileError(f"{part!r} has no effect setup to copy")
        ef.objects.append(bytearray(ef.objects[setup]))
        new = len(ef.objects) - 1
        if looping:
            _as_trail(ef.objects[new])
        p, at, size = _value_field(ef, part, "bytes_1")
        p[at:at + size] = struct.pack("<II", 1, new)
        ids = [new]
    obj = ef.objects[ids[0]]
    # u32 class index, then the resource: root ("FX") and path, each u32 + bytes.
    (n,) = struct.unpack_from("<I", obj, 4)
    if bytes(obj[8:8 + n]) != b"FX":
        raise ProjectileError(f"{part!r}: its setup does not name an FX resource")
    (m,) = struct.unpack_from("<I", obj, 8 + n)
    obj[8 + n:12 + n + m] = P._lstr(vfx)
    # The byte after the path: 1 = plays once (impact), 0 = keeps playing (trail).
    flag_at = 12 + n + len(vfx.encode("latin-1"))
    if obj[flag_at] not in (0, 1):
        raise ProjectileError(f"{part!r}: its setup is not laid out as the base's")
    obj[flag_at] = 0 if looping else 1
    if looping:
        _trail_tuning(obj, flag_at)


#: A trail's own settings after its path, as Red's spike trail sets them where
#: an impact differs (offsets from the byte after the path; the layout after
#: the path holds no strings): a mode 0 (follows its owner; an impact's 2
#: stays where it burst), a switch on, and a 0.25 s float (its fade).
_TRAIL_AT = {204: (2, 0), 414: (0, 1)}
_TRAIL_FADE_AT = 517


def _trail_tuning(obj: bytearray, flag_at: int) -> None:
    for off, (was, now) in _TRAIL_AT.items():
        if obj[flag_at + off] not in (was, now):
            raise ProjectileError("the trail setup is not laid out as the base's")
        obj[flag_at + off] = now
    at = flag_at + _TRAIL_FADE_AT
    if struct.unpack_from("<f", obj, at)[0] not in (0.0, 0.25):
        raise ProjectileError("the trail setup's fade is not where the base keeps it")
    struct.pack_into("<f", obj, at, 0.25)


def build(read, *, stem: str, mesh: str, material: str, lifetime: float = 1.0,
          trail: str = "", impact: str = "", pierce: bool = True,
          size: float = SIZE, pitch: float = PITCH) -> bytes:
    """The projectile entity ``stem`` (cooked bytes). ``read`` reads a shipped
    entity by reference; ``mesh``/``material`` are cooked 3D paths of the
    mod's own; ``trail``/``impact`` name ``.vfx.ot`` effects (an empty trail
    flies bare; an empty impact keeps the base's)."""
    raw_base, raw_model = read(BASE), read(MODEL)
    if raw_base is None or raw_model is None:
        raise ProjectileError("the shared projectile base is not readable (no install or mirror)")
    base = EntityFile(raw_base, "Projectile_Model")
    model = EntityFile(raw_model, "Hero_Projectile_Model")
    ef = EntityFile(HF.main_frame(MODEL, HF.guid(stem, "projectile")), stem)
    try:
        HF.fill_slot(ef, base, "Lifetime Duration", value=float(lifetime))
        HF.fill_slot(ef, base, "Mesh")
        _swap_resource(ef, "Mesh", (_SAMPLES, _BASE_MESH), ("3D", mesh))
        if material:                     # else the base's plain grey
            _swap_resource(ef, "Mesh", (_SAMPLES, _BASE_MAT), ("3D", material))
        _set_float(ef, "Mesh", "value_10", float(size))
        _set_pitch(ef, float(pitch))
        HF.fill_slot(ef, base, "Projectile Attack Selector")
        if pierce:
            plain = base.component("Projectile Attack")
            pier = model.component("Piercing Projectile Attack")
            c = ef.component("Projectile Attack Selector")
            p = ef.objects[c.index - 1]
            old = plain.guid + P._lstr(
                "[Gpn Projectile Attack] Projectile_Model\\Projectile Attack")
            new = pier.guid + P._lstr(
                "[Gpn Projectile Attack] Hero_Projectile_Model\\Piercing Projectile Attack")
            if bytes(p).count(old) != 1:
                raise ProjectileError("the attack selector does not name the plain attack once")
            p[:] = bytes(p).replace(old, new)
        HF.fill_slot(ef, base, "Impact Fx Default")
        setup = _fx_ids(ef, "Impact Fx Default")[0]
        if impact:
            _set_fx(ef, "Impact Fx Default", None, impact, looping=False)
        HF.fill_slot(ef, base, "Alive Fx Default")
        if trail:
            _set_fx(ef, "Alive Fx Default", setup, trail, looping=True)
            # Red's trail part: not stopped on hit / on death (values 2, 3).
            for name in ("value_2", "value_3"):
                pp, at, _sz = _value_field(ef, "Alive Fx Default", name)
                if struct.unpack_from("<I", pp, at + 17)[0] == 2:     # bool union
                    pp[at + 25] = 0
    except (HF.FrameError, EntityEditError) as e:
        raise ProjectileError(f"projectile {stem}: {e}") from e
    return ef.to_bytes()


__all__ = ["BASE", "BASE_IMPACT", "FIELDS", "MODEL", "PITCH", "SIZE", "ProjectileError",
           "build"]
