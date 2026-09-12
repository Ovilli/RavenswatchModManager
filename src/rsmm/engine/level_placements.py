"""Read and write the objects a level STANDS, at the level of the object graph.

A cooked level is a serialized object graph, and the grammar is now read off
the engine's write side rather than inferred from the bytes
(``data/symbols.json::Serializer_ReadObjectNamed``, 2026-09-12). ``LevelBinary_Load``
builds a loader and hands it to ``LevelStream_Deserialize``, which reads THREE
independent graphs by name — ``*a_pLvlId``, ``*a_pLinks``, ``*a_pLevel`` — each
with its own class table and its own object table. The level is the last one,
and it is read in four strictly sequential phases:

1. class table: ``uClassCount`` + one row per class;
2. object table: ``uOjbectsCount`` (the engine's own typo) + one
   ``uClassFinfoIndex`` per object. **This phase decides how many objects exist
   and what they are** — each entry is instantiated and pushed into the
   loader's object vector before a single payload byte is read;
3. one payload block per object, in table order, each framed
   ``MARK_BEGIN | uClassInfoIndex | ...`` and read with no seek;
4. the root object last, which is why the level's own list of what it owns sits
   at the END of the stream.

An id anywhere in the file is an index into the phase-2 table, so — verified on
390 of 390 shipped levels — **an object's id is its position in the stream**.
Two more corpus invariants come from the same walk: a table of count ``m`` is
followed by exactly ``m`` payload blocks plus one root block, and entry ``i``
equals the leading class index of block ``i``.

**Layout of one placement**, inside its own payload block::

    u32     uClassInfoIndex
    lstr    instance name           (often empty)
    lstr    group name
    ...     0x26 bytes of flags and defaults
    float3  position                <-- the transform
    float4  rotation quaternion (x, y, z, w)
    float3  scale
    ...
    lstr    "EntitySettings"        <-- the anchor the entity ref hangs off
    lstr    the placed entity's path

The transform is at a STRUCTURAL offset, not a searched one: two length-prefixed
names then a constant ``0x26``. That resolves 116708 of 116708 marker-free
placement blocks in the corpus, where the previous consensus search over the
bytes between asset references resolved 7686 — and attributed every one of them
to the WRONG object, because the bytes following a reference belong to the NEXT
block, not to the one the reference came out of.
"""

from __future__ import annotations

import math
import struct
from collections import Counter
from dataclasses import dataclass

from . import cooked

#: How far |q| may stray from 1 before a record is rejected. The offset is
#: structural, so this is not a search filter — it is the tripwire that fires if
#: a game patch moves the layout, and |q| = 1 is the one invariant random bytes
#: essentially never satisfy.
_QUAT_TOLERANCE = 1e-3

#: Generous sanity bounds. The shipped range is 0.02 .. 97.57 for scale, so a
#: tight cap rejects real level data: at 50.0 it threw out five genuine
#: placements from the Roc camp and the submerged palace.
_SCALE_RANGE = (1e-3, 1e3)
_POS_LIMIT = 1e5

#: The engine clamps a vector's element count here (Serializer_ReadPolyPtrVector).
_MAX_OBJECTS = 1_000_000

#: The `oCGameStream` wrapper's own header, ahead of the level's inner stream.
#: Its last two u32s are the inner stream's length, stated twice.
_INNER_OFF = 16
_SELF_SIZE_OFF = 8

#: The literal that precedes a placement's entity reference. Present exactly
#: once in 116708 of 118289 `oCEntitySpawnerGo` blocks.
_ANCHOR = b"\x0e\x00\x00\x00EntitySettings"

#: Distance from the end of a placement's two names to its transform.
_TRANSFORM_DELTA = 0x26

#: A serialized transform: float3 position, float4 quaternion, float3 scale.
_TRANSFORM_LEN = 40


class LevelPlacementError(ValueError):
    pass


@dataclass(frozen=True)
class Placement:
    """One object standing in a level."""

    ref: str
    pos: tuple[float, float, float]
    quat: tuple[float, float, float, float]
    scale: tuple[float, float, float]

    @property
    def tilt_deg(self) -> float:
        """Angle between this object's own up axis and world up.

        What "is it standing?" means. A swapped-in prop adopts this, so a tall
        replacement on a slot authored for something lying down leans over —
        and the taller the replacement, the further its top travels.
        """
        x, _y, z, _w = self.quat
        return math.degrees(math.acos(max(-1.0, min(1.0, 1 - 2 * (x * x + z * z)))))

    @property
    def yaw_deg(self) -> float:
        """Rotation about the up axis. Cosmetic for a symmetric prop."""
        _x, y, _z, w = self.quat
        return math.degrees(2 * math.atan2(y, w))

    def distance_to(self, other: Placement) -> float:
        return math.dist(self.pos, other.pos)


# --------------------------------------------------------------------------
# The object graph
# --------------------------------------------------------------------------

def _blocks(data: bytes) -> list[tuple[int, int, bytes]]:
    """Every depth-0 ``MARK_BEGIN .. MARK_END`` block, as (begin, end, payload).

    Nested markers are consumed by `cooked._find_section_end`'s depth count, so
    a block that frames sub-structure of its own comes back whole.
    """
    out: list[tuple[int, int, bytes]] = []
    pos = 0
    while True:
        i = data.find(cooked.MARK_BEGIN, pos)
        if i < 0:
            return out
        end = cooked._find_section_end(data, i + 4)
        out.append((i, end, data[i + 4:end - 4]))
        pos = end


def _is_class_table(p: bytes) -> bool:
    """Does this block hold a ``uClassCount`` + rows, consuming itself exactly?"""
    if len(p) < 4:
        return False
    (n,) = struct.unpack_from("<I", p, 0)
    if not 0 < n <= 200:
        return False
    o = 4
    for _ in range(n):
        if o + 4 > len(p):
            return False
        (ln,) = struct.unpack_from("<I", p, o)
        o += 4 + ln + 16          # name, then id / vmaj / vmin / parent
        if o > len(p):
            return False
    return o == len(p)


@dataclass(frozen=True)
class _Graph:
    """The level's own object graph — the last of the stream's three."""

    inner: bytes
    blocks: list[tuple[int, int, bytes]]
    ot: int                       # index of the object-table block
    count: int                    # uOjbectsCount
    class_idx: list[int]          # one uClassFinfoIndex per object

    @property
    def objects(self) -> list[tuple[int, int, bytes]]:
        return self.blocks[self.ot + 1:self.ot + 1 + self.count]

    @property
    def root(self) -> tuple[int, int, bytes]:
        return self.blocks[-1]


def _graph(inner: bytes) -> _Graph:
    """Locate the level's object table, or raise.

    Found by its RELATIONSHIPS, never by a block index: it is preceded by a
    class table, it consumes itself exactly as ``u32 count`` + ``count`` u32s,
    and exactly ``count + 1`` blocks follow it — the payloads plus the root.
    Three independent constraints, so a game patch that reshapes the stream
    fails here instead of writing into the wrong place.
    """
    try:
        bl = _blocks(inner)
    except (ValueError, struct.error) as e:
        # `cooked._find_section_end` raises on an unterminated block. That is a
        # stream this walk cannot read, not a crash for the caller to handle.
        raise LevelPlacementError(f"level stream does not frame cleanly: {e}") from None
    if len(bl) < 2:
        raise LevelPlacementError("level stream holds no object graph")
    if bl[-1][1] != len(inner):
        raise LevelPlacementError("level stream does not end on a complete block")
    for j in range(len(bl) - 2, 0, -1):
        p = bl[j][2]
        if len(p) < 4:
            continue
        (n,) = struct.unpack_from("<I", p, 0)
        if n > _MAX_OBJECTS or 4 + 4 * n != len(p):
            continue
        if len(bl) - 1 - j != n + 1:
            continue
        if not _is_class_table(bl[j - 1][2]):
            continue
        idx = list(struct.unpack_from(f"<{n}I", p, 4)) if n else []
        return _Graph(inner=inner, blocks=bl, ot=j, count=n, class_idx=idx)
    raise LevelPlacementError(
        "cannot find the level's object table; refusing to touch a stream "
        "whose grammar this walk does not recognise")


def _inner(level_bytes: bytes) -> tuple[cooked.CookedFile, bytes, bytes]:
    """``(container, wrapper section payload, inner stream)``.

    The outer file is an `oCGameStream` with two sections: an empty object
    table of its own, and one payload whose first 16 bytes are the wrapper's
    header — the last two u32s of which state the inner stream's length, twice.
    All three facts hold on 390 of 390 shipped levels.
    """
    try:
        cf = cooked.parse(level_bytes)
    except (ValueError, KeyError, IndexError, struct.error) as e:
        raise LevelPlacementError(f"not a readable level: {e}") from None
    if len(cf.sections) != 2:
        raise LevelPlacementError(
            f"expected an oCGameStream wrapper of 2 sections, got {len(cf.sections)}")
    sec = cf.sections[-1].payload
    if len(sec) < _INNER_OFF:
        raise LevelPlacementError("level wrapper section is too short to hold a stream")
    a, b = struct.unpack_from("<II", sec, _SELF_SIZE_OFF)
    if a != b or a != len(sec) - _INNER_OFF:
        raise LevelPlacementError(
            "level wrapper does not declare its own size; refusing to edit a "
            "stream whose length field this walk cannot keep honest")
    return cf, sec, sec[_INNER_OFF:]


# --------------------------------------------------------------------------
# One placement inside its block
# --------------------------------------------------------------------------

def _transform_off(p: bytes) -> int | None:
    """Where the transform starts: past two length-prefixed names, plus 0x26."""
    o = 4                                   # uClassInfoIndex
    for _ in range(2):
        if o + 4 > len(p):
            return None
        (ln,) = struct.unpack_from("<I", p, o)
        if ln > len(p):
            return None
        o += 4 + ln
    o += _TRANSFORM_DELTA
    return o if o + _TRANSFORM_LEN <= len(p) else None


def _transform_at(p: bytes, o: int):
    """``(pos, quat, scale)`` at `o`, or None if that is not a transform."""
    quat = struct.unpack_from("<4f", p, o + 12)
    if not all(math.isfinite(v) for v in quat):
        return None
    if abs(math.sqrt(sum(c * c for c in quat)) - 1.0) > _QUAT_TOLERANCE:
        return None
    scale = struct.unpack_from("<3f", p, o + 28)
    if not all(math.isfinite(v) and _SCALE_RANGE[0] <= abs(v) <= _SCALE_RANGE[1]
               for v in scale):
        return None
    pos = struct.unpack_from("<3f", p, o)
    if not all(math.isfinite(v) and abs(v) <= _POS_LIMIT for v in pos):
        return None
    return pos, quat, scale


def _entity_ref_span(p: bytes) -> tuple[int, int] | None:
    """``(offset of the length prefix, length)`` of the placed entity's path."""
    if p.count(_ANCHOR) != 1:
        return None
    k = p.find(_ANCHOR) + len(_ANCHOR)
    if k + 4 > len(p):
        return None
    (ln,) = struct.unpack_from("<I", p, k)
    if not 0 < ln <= 300 or k + 4 + ln > len(p):
        return None
    return k, ln


def _as_placement(p: bytes) -> tuple[str, int, tuple] | None:
    """``(ref, transform offset, transform)`` if this block is a plain placement.

    "Plain" means it frames no sub-structure of its own — no nested
    ``MARK_BEGIN``. That is not a convenience: a nested block is where a
    spawner keeps the poly-pointer vector of the settings objects it OWNS, and
    duplicating one would hand a second spawner the same children. Across 390
    levels, every object that owns children has a nested marker and no level
    with owned children lacks one, so marker-free means owns-nothing.
    """
    if cooked.MARK_BEGIN in p:
        return None
    span = _entity_ref_span(p)
    if span is None:
        return None
    o = _transform_off(p)
    if o is None:
        return None
    got = _transform_at(p, o)
    if got is None:
        return None
    k, ln = span
    return p[k + 4:k + 4 + ln].decode("utf-8", errors="replace"), o, got


def decode(level_bytes: bytes) -> list[Placement]:
    """Every entity placement in a cooked level, in stream order.

    Each placement's transform is read out of the SAME object that names the
    entity. Returns ``[]`` when the graph walk fails, because callers use these
    to make refusals and half a level's transforms would be worse than none.
    """
    try:
        _cf, _sec, inner = _inner(level_bytes)
        g = _graph(inner)
    except LevelPlacementError:
        return []
    out: list[Placement] = []
    for _b, _e, p in g.objects:
        got = _as_placement(p)
        if got is not None:
            ref, _o, (pos, quat, scale) = got
            out.append(Placement(ref, pos, quat, scale))
    return out


def placements_of(level_bytes: bytes, ref: str) -> list[Placement]:
    """Every slot at which `level_bytes` stands `ref`."""
    return [p for p in decode(level_bytes) if p.ref == ref]


def nearest(level_bytes: bytes, to: Placement,
            limit: int = 5) -> list[tuple[float, Placement]]:
    """The `limit` objects standing closest to `to`, nearest first.

    A replacement is only as good as the room its slot has: an obelisk three
    times the donor's size reaches into whatever the level parked beside it.
    """
    others = [p for p in decode(level_bytes) if p is not to and p.pos != to.pos]
    return sorted(((to.distance_to(p), p) for p in others),
                  key=lambda r: r[0])[:limit]


# --------------------------------------------------------------------------
# Adding one
# --------------------------------------------------------------------------

def _frame(payload: bytes) -> bytes:
    return cooked.MARK_BEGIN + payload + cooked.MARK_END


def add_placement(level_bytes: bytes, ref: str,
                  pos: tuple[float, float, float],
                  quat: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0),
                  scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
                  after: str | None = None) -> bytes:
    """Return `level_bytes` with one more object standing in it.

    ADDING rather than swapping is the difference between accepting a slot the
    level author chose and choosing your own. A `swaps` target inherits the
    donor's transform whole, which is where every "not standing", "buried" and
    "offset" report in this feature came from; an added placement takes the
    position, rotation and scale given here, and destroys nothing.

    **Three writes make an object, and this used to do only the third.**
    The engine instantiates exactly ``uOjbectsCount`` objects from the class
    indices beside it, BEFORE it reads a single payload byte, and then reads one
    payload block per object with no seek. So a block spliced into the stream
    without growing that count does not produce an inert extra object: it
    shifts every following object onto its predecessor's bytes, deserializes
    them into an instance of the wrong class, and leaves the root's own block to
    be consumed as the last sub-object. Measured on four shipped levels on
    2026-09-12 — one extra payload block, ``uOjbectsCount`` untouched. So:

    1. ``uOjbectsCount`` grows by one and the template's ``uClassFinfoIndex``
       is appended, which is what brings the object into existence;
    2. the new payload block goes in IMMEDIATELY BEFORE THE ROOT, because an
       object's id is its position — inserting mid-stream would renumber every
       later id in every vector in the file, while appending takes id ``count``
       and renumbers nothing;
    3. the root's own vector gains that id, which is what makes the level own it.

    The template is a shipped placement block, copied whole and rewritten in two
    places: its transform and its entity reference. Nothing else needs touching
    — 2996 groups of shipped blocks are byte-identical apart from exactly those
    two fields, so a placement carries no per-object identity to collide on.

    `after` names the entity whose block is used as the template. A block is
    self-framed, so the old hazard this argument had to dodge — that the last
    record in the stream is not an ordinary placement but the tail, and copying
    it spliced the stream's ending into its middle — cannot arise here.
    """
    cf, sec, inner = _inner(level_bytes)
    g = _graph(inner)
    if g.count > _MAX_OBJECTS - 1:
        raise LevelPlacementError(f"level already holds {g.count} objects")

    cands = [(i, p, got)
             for i, (_b, _e, p) in enumerate(g.objects)
             if (got := _as_placement(p)) is not None]
    if not cands:
        raise LevelPlacementError(
            "level places nothing this walk can copy; refusing to invent a "
            "placement block from scratch")
    if after is not None:
        cands = [c for c in cands if c[2][0] == after] or cands
    # The modal class, so an oddball one-off is never the template.
    seen = Counter(g.class_idx[i] for i, _p, _got in cands)
    modal = max(seen, key=lambda c: (seen[c], c))
    tmpl_i, tmpl, (_ref, tr, _got) = next(
        c for c in reversed(cands) if g.class_idx[c[0]] == modal)

    block = bytearray(tmpl)
    struct.pack_into("<3f", block, tr, *pos)
    struct.pack_into("<4f", block, tr + 12, *quat)
    struct.pack_into("<3f", block, tr + 28, *scale)
    k, ln = _entity_ref_span(bytes(block))
    raw = ref.encode("utf-8")
    block[k:k + 4 + ln] = struct.pack("<I", len(raw)) + raw

    # 1. the object table: one more object, of the template's class.
    table = (struct.pack("<I", g.count + 1)
             + struct.pack(f"<{g.count}I", *g.class_idx)
             + struct.pack("<I", g.class_idx[tmpl_i]))

    # 3. the root's vector: one more id, which is the new object's position.
    root = g.root[2]
    (rn,) = struct.unpack_from("<I", root, 4)
    if 8 + 4 * rn > len(root):
        raise LevelPlacementError("the level's own object vector runs past its block")
    ids = struct.unpack_from(f"<{rn}I", root, 8)
    # The root's first member is a poly-pointer vector into the object table.
    # Prove that before growing it: a level whose root begins with something
    # else would still unpack, and appending there would write an id into the
    # middle of some other field. Holds on 390 of 390 shipped levels.
    if rn > g.count or any(i >= g.count for i in ids) or len(set(ids)) != rn:
        raise LevelPlacementError(
            f"the level's root does not begin with a vector of object ids "
            f"({rn} entries against {g.count} objects); refusing to grow it")
    new_root = (root[:4] + struct.pack("<I", rn + 1)
                + struct.pack(f"<{rn + 1}I", *ids, g.count)
                + root[8 + 4 * rn:])

    ot_begin, ot_end, _ = g.blocks[g.ot]
    root_begin = g.root[0]
    new_inner = (inner[:ot_begin]
                 + _frame(table)
                 + inner[ot_end:root_begin]      # 2. every existing payload, in order
                 + _frame(bytes(block))          #    then ours, id == g.count
                 + _frame(new_root))

    new_sec = bytearray(sec[:_INNER_OFF]) + new_inner
    struct.pack_into("<II", new_sec, _SELF_SIZE_OFF, len(new_inner), len(new_inner))
    cf.sections[-1] = cooked.Section(payload=bytes(new_sec))
    return cooked.emit(cf)
