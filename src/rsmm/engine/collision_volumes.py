"""Collision volumes: walkable ground and blocking walls on an entity.

A prop the game draws is not something a hero can stand on or bump into. What
makes ground walkable is a ``oCEntityCpntCollisionVolumeSettings`` component,
and the shipped Dark Hills docks are built from nothing else: the High
Fisherman Platform tile stands its decks on 27 placed ``Platform_Floor_*``
entities, each carrying one ``COL Ground`` BOX, and the navmesh is rebuilt from
live physics at level load, so enemies path across them too. Some shipped
entities are collision ONLY, with no graphic at all (``Pontoon_8x7``,
``LD_Terrain_Shapes\\Slope_ColOnly_12x12``): the art is a separate mesh, and
the walkable shape is a handful of boxes.

This module writes those boxes onto an entity. Each one is a clone of a shipped
``COL_Ground`` record with its shape, transform and flag set rewritten.

Field layout, read off the shipped records (``entity_fields`` names):

``bytes_1`` (24 B)
    ``u32 1, u32 group, u32 mask, u32 0, u32 8, u32 0``. Ground is group 7 /
    mask 1 (every ``COL Ground`` / ``COL_Ground``); a wall is group 8 / mask 2
    (``COL_Wall_*``, chest and door bodies, arena barriers). 61 shipped wall
    volumes are boxes, so a wall box is the ground record with this changed.
``value_2``
    1.0 on ground, 0.5 on walls. Copied with the flag set.
``bytes_3`` (20 B)
    ``u32 2, u32 shape, f32 x3``. Shape 0 is a box and the floats are its
    HALF extents (``Platform_Floor_8x8``: 4, 1, 4). Shape 2 is a cylinder.
``obj_4``
    The volume's transform in the entity's space, as literals: ``[3..5]`` the
    centre, ``[7..9]`` an Euler rotation in RADIANS, ``[11..13]`` a scale.
    ``Platform_Floor_8x8`` sits its box at y = -1 with half height 1, so its
    TOP is the entity origin. The shipped ramp (``Slope_ColOnly_12x12``) is a
    6 x 1 x 6.53 half-extent box turned 0.324 rad (18.6 deg) about X. A
    POSITIVE X rotation LOWERS the box's +Z end (right-handed): the shipped
    ``Platform_Floor_Slope_8x6_01`` / ``_12x8_01`` put their landing box at
    local z = -0.5, 2 m / 4 m up, and descend toward +Z with rx = +0.324. (The
    first hut ramp was written with the opposite sign; 0.5 m is a climbable
    step, so walking onto that deck proved the deck, not the ramp.)

★ PROVEN IN GAME 2026-11-14 (fishermans-camp v0.2.0): a hero walked up a
tilted ground box onto a 0.5-high ground deck and stood on it, and a wall box
blocked. Enemy pathing across mod boxes is not yet observed.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from . import corpus
from .entity_graph_edit import EntityFile

#: A collision-only shipped entity whose ``COL_Ground`` is a plain box.
DONOR = ("EntitySettings/DarkHills/Objects_DarkHills/Pontoon_8x7.entity.ot"
         ".EntitySettingsResource.gen")
DONOR_COMPONENT = "COL_Ground"

KINDS = {"ground": (7, 1, 1.0), "wall": (8, 2, 0.5)}
SHAPE_BOX = 0
#: Literal indexes inside ``obj_4``.
POS, ROT, SCALE = (3, 4, 5), (7, 8, 9), (11, 12, 13)
#: Sanity bounds: a tile is at most 64 units across.
MAX_EXTENT = 128.0
MAX_VOLUMES = 256


class CollisionError(ValueError):
    pass


@dataclass(frozen=True)
class Volume:
    kind: str                                  # "ground" | "wall"
    size: tuple[float, float, float]           # FULL size, x y z
    at: tuple[float, float, float]             # centre, entity space
    rot: tuple[float, float, float] = (0.0, 0.0, 0.0)  # degrees about x y z


def _vec(v, what: str) -> tuple[float, float, float]:
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise CollisionError(f"{what} must be three numbers, got {v!r}")
    try:
        out = tuple(float(x) for x in v)
    except (TypeError, ValueError):
        raise CollisionError(f"{what} must be three numbers, got {v!r}") from None
    if not all(math.isfinite(x) and abs(x) <= MAX_EXTENT for x in out):
        raise CollisionError(f"{what} {v!r} is out of range (|x| <= {MAX_EXTENT})")
    return out  # type: ignore[return-value]


def parse(items, what: str = "collision") -> list[Volume]:
    """``[{kind, size, at, rot?}, ...]`` from a manifest -> volumes."""
    if not isinstance(items, list):
        raise CollisionError(f"{what} must be a list of tables")
    if len(items) > MAX_VOLUMES:
        raise CollisionError(f"{what}: {len(items)} volumes, at most {MAX_VOLUMES}")
    out = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise CollisionError(f"{what}[{i}] must be a table")
        extra = set(it) - {"kind", "size", "at", "rot"}
        if extra:
            raise CollisionError(f"{what}[{i}]: unknown key(s) {sorted(extra)}")
        kind = it.get("kind", "ground")
        if kind not in KINDS:
            raise CollisionError(f"{what}[{i}].kind must be one of {sorted(KINDS)}")
        size = _vec(it.get("size"), f"{what}[{i}].size")
        if min(size) <= 0:
            raise CollisionError(f"{what}[{i}].size must be positive, got {size}")
        out.append(Volume(kind, size, _vec(it.get("at"), f"{what}[{i}].at"),
                          _vec(it.get("rot", [0, 0, 0]), f"{what}[{i}].rot")))
    return out


def _donor() -> EntityFile:
    raw = corpus.read(DONOR)
    if raw is None:
        raise CollisionError(f"collision donor {DONOR} is not readable")
    return EntityFile(raw, "Pontoon_8x7")


def _write(ef: EntityFile, name: str, v: Volume) -> None:
    group, mask, weight = KINDS[v.kind]
    c, f, at = ef._field(name, "bytes_1")
    p = ef.objects[c.index - 1]
    if f.size != 24 or struct.unpack_from("<I", p, at + f.offset)[0] != 1:
        raise CollisionError(f"{name}: unexpected bytes_1 layout")
    struct.pack_into("<II", p, at + f.offset + 4, group, mask)
    c, f, at = ef._field(name, "bytes_3")
    if f.size != 20 or struct.unpack_from("<I", p, at + f.offset)[0] != 2:
        raise CollisionError(f"{name}: unexpected bytes_3 layout")
    struct.pack_into("<I3f", p, at + f.offset + 4, SHAPE_BOX, *(s / 2 for s in v.size))
    ef.set_value(name, "value_2", weight)
    for idx, val in zip(POS, v.at, strict=True):
        ef.set_value(name, f"obj_4[{idx}]", val)
    for idx, val in zip(ROT, v.rot, strict=True):
        ef.set_value(name, f"obj_4[{idx}]", math.radians(val))


def add_volumes(entity_bytes: bytes, volumes: list[Volume], *, name: str = "",
                seed: str = "") -> bytes:
    """``entity_bytes`` with one collision box per volume appended as
    components named ``COL_RSMM_<n>``."""
    if not volumes:
        return entity_bytes
    ef = EntityFile(entity_bytes, name)
    donor = _donor()
    for k, v in enumerate(volumes):
        new = f"COL_RSMM_{k:03d}"
        ef.clone([DONOR_COMPONENT], rename={DONOR_COMPONENT: new}, source=donor,
                 seed=f"{seed}/collision/{k}")
        _write(ef, new, v)
    return ef.to_bytes()


def read_volumes(entity_bytes: bytes) -> list[tuple[str, dict]]:
    """Every collision volume on an entity, decoded (for tests and `rsmm`
    inspection): name -> {group, mask, shape, half, pos, rot}."""
    from . import entity_fields as EF
    from . import entity_graph as EG
    out = []
    for c in EG.parse(entity_bytes, "x").components:
        if c.cls != "oCEntityCpntCollisionVolumeSettings":
            continue
        fs = {f.name: f for f in EF.fields(c)}
        b1 = c.body[fs["bytes_1"].offset:fs["bytes_1"].offset + 24]
        b3 = c.body[fs["bytes_3"].offset:fs["bytes_3"].offset + fs["bytes_3"].size]
        nums = [float(x) for x in fs["obj_4"].text.replace("vec3", " ").replace("f32", " ").split()
                if _is_num(x)]
        rec = {"group": struct.unpack_from("<I", b1, 4)[0],
               "mask": struct.unpack_from("<I", b1, 8)[0],
               "shape": struct.unpack_from("<I", b3, 4)[0],
               "half": struct.unpack_from(f"<{(len(b3) - 8) // 4}f", b3, 8),
               "obj_4": nums}
        out.append((c.name, rec))
    return out


def _is_num(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False
