"""Decode where a level actually STANDS each object it places.

`asset_refs` recovers *what* a level references; this recovers *where*. The
difference has cost this repo several playtests, because a `swaps` target
inherits the donor's transform whole — position, rotation AND scale — so the
donor's slot decides what the replacement looks like, and nothing could read
that slot. Three separate in-game reports ("some of them tipped over", "it is
moved and not standing", "stuck in some stone") were all one missing oracle.

**Layout**, per placed object, inside the literal that FOLLOWS its entity
reference::

    +N+0x00  float3  position
    +N+0x0c  float4  rotation quaternion (x, y, z, w)
    +N+0x1c  float3  scale

``N`` is NOT fixed. It is 0x41 in `6x6_Blocker_02` (125-byte records) and
something else in `40x40_DarkHills_Starting_Tile_Update3`, whose records come
in four sizes (132/192/139/314) — a hardcoded 0x41 decodes 30/30 of the first
level and **0 of 136** of the second. So the offset is DETECTED per level, by
consensus: the offset at which the most records yield a unit quaternion and a
plausible scale wins, and the walk refuses the level if too few agree.

The quaternion is what makes that safe. |q| = 1 is a strong, cheap invariant
that random bytes essentially never satisfy, and the record is byte-shifted
from the literal's start, so a naive 4-byte-aligned scan reads zeros — which
is exactly the wrong answer a fixed offset gives you silently.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from . import cooked

#: How far |q| may stray from 1 before a candidate offset is rejected.
_QUAT_TOLERANCE = 1e-3

#: Scale multipliers outside this range mean the offset is wrong, not that a
#: level-designer did something exotic (the shipped range is 0.70 .. 1.00).
_SCALE_RANGE = (0.02, 50.0)

#: A tile is tens of units across; anything past this is not a coordinate.
_POS_LIMIT = 1e4

#: Smallest magnitude a real coordinate takes. Anything between this and zero
#: is a DENORMAL — the signature of reading a couple of stray bytes as a float.
#: Without this test, offset 0x0f in `6x6_Blocker_02` scores identically to the
#: true 0x41: its "position" is (5.6e-45, 0, 0), which is non-zero, so it
#: counted as informative and won the tie by being found first.
_DENORMAL = 1e-6

#: Sanity bound on the object vector's count. A level is tens of objects;
#: anything past this means the walk landed somewhere that is not the vector.
_MAX_OBJECTS = 10000

#: Fraction of a level's placements that must agree on one offset before the
#: decode is trusted. Below it the layout is not what this walk understands and
#: returning half a level's transforms would be worse than returning none.
_CONSENSUS = 0.75


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


def _sane(v: float, limit: float) -> bool:
    """A float that could be real level data: finite, in range, not denormal."""
    if not math.isfinite(v) or abs(v) > limit:
        return False
    return v == 0.0 or abs(v) >= _DENORMAL


def _at(blob: bytes, off: int):
    """The transform at `off`, or None if it is not one."""
    if off < 0 or len(blob) < off + 40:
        return None
    quat = struct.unpack_from("<4f", blob, off + 12)
    if abs(math.sqrt(sum(c * c for c in quat)) - 1.0) > _QUAT_TOLERANCE:
        return None
    scale = struct.unpack_from("<3f", blob, off + 28)
    if not all(_SCALE_RANGE[0] <= abs(v) <= _SCALE_RANGE[1] for v in scale):
        return None
    pos = struct.unpack_from("<3f", blob, off)
    # Position is the field that catches a run of zeros: an identity quaternion
    # is unit and a (1,1,1) scale is in range, so without this a block of 00s
    # followed by three 1.0s scores as a perfect transform — and it did,
    # returning every object at tilt 0 with a position of 7.9e34.
    if not all(_sane(v, _POS_LIMIT) for v in pos):
        return None
    if not all(_sane(v, 1.0) for v in quat):
        return None
    return pos, quat, scale


def _detect_offset(blobs: list[bytes]) -> int | None:
    """The offset at which most records hold a transform, or None.

    Consensus rather than a constant: record sizes differ between levels (and
    within one), so the only reliable anchor is that the SAME offset works for
    almost every object in a given file.
    """
    votes: dict[int, int] = {}
    informative: dict[int, int] = {}
    for blob in blobs:
        for off in range(0, len(blob) - 40):
            got = _at(blob, off)
            if got is None:
                continue
            votes[off] = votes.get(off, 0) + 1
            pos, quat, _s = got
            # An offset that only ever yields the identity rotation at the
            # origin is matching padding, not transforms. Real level data
            # varies; score on that and the degenerate candidates lose.
            if any(v for v in pos) or quat[:3] != (0.0, 0.0, 0.0):
                informative[off] = informative.get(off, 0) + 1
    if not votes:
        return None
    off = max(votes, key=lambda o: (informative.get(o, 0), votes[o]))
    return off if votes[off] >= _CONSENSUS * len(blobs) else None


def decode(level_bytes: bytes) -> list[Placement]:
    """Every entity placement in a cooked level, in file order.

    Returns ``[]`` when no offset commands a consensus — a level whose layout
    this walk does not understand yields nothing rather than a plausible-looking
    half, because callers use these transforms to make refusals.
    """
    from .cooked_schemas import asset_refs as AR

    doc = AR._decode(level_bytes, "oCGameStream")
    refs, lits = doc["asset_refs"], doc["_literals"]
    pairs = [(r, bytes.fromhex(lits[i + 1]))
             for i, r in enumerate(refs)
             if r.lower().endswith(".entity.ot") and i + 1 < len(lits)]
    if not pairs:
        return []
    # Per RECORD SIZE, not per level: one level mixes several record shapes
    # (the Dark Hills start tile has four — 132/192/139/314 bytes) and each
    # shape puts the transform somewhere different. Detecting one offset for
    # the whole file decoded 72 of 390 shipped levels; per size it is far more.
    by_size: dict[int, list[bytes]] = {}
    for _r, blob in pairs:
        by_size.setdefault(len(blob), []).append(blob)
    offsets = {n: _detect_offset(bs) for n, bs in by_size.items()}
    out: list[Placement] = []
    for ref, blob in pairs:
        off = offsets.get(len(blob))
        if off is None:
            continue
        got = _at(blob, off)
        if got is not None:
            out.append(Placement(ref, *got))
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


def _object_vector(literals: list[bytes]) -> tuple[int, int, list[int]]:
    """``(literal index, offset, ids)`` of the level's OBJECT vector.

    A level is a serialized object graph and this is the list of what is in it
    — ``u32 count`` + ``count`` sub-object ids, right after the trailer's
    nested BEGIN and class index. Exactly the shape
    ``entity_append.component_vector`` walks one level down, and it fails the
    same way: a placement written into the stream but absent from this vector
    is an ORPHAN. It deserializes, it is byte-stable, it passes every cache and
    reference check, and the engine never instantiates it — which is why an
    added POI could be measured PLACED and BUILT while nothing stood in the
    tile.

    Located at the LAST ``MARK_BEGIN`` in the stream, verified against the
    whole corpus: 390 of 390 shipped levels have the vector there and its ids
    are exactly ``0..count-1``. That identity-prefix shape is what makes the
    append trivial — a new object is always id ``count``, whatever position in
    the stream it was inserted at.
    """
    for k in range(len(literals) - 1, -1, -1):
        i = literals[k].rfind(cooked.MARK_BEGIN)
        if i < 0:
            continue
        blob, o = literals[k], i + 8          # BEGIN, class index
        if o + 4 > len(blob):
            break
        (n,) = struct.unpack_from("<I", blob, o)
        if n > _MAX_OBJECTS or o + 4 + 4 * n > len(blob):
            break
        ids = list(struct.unpack_from(f"<{n}I", blob, o + 4))
        if ids != list(range(n)):
            break
        return k, o, ids
    raise LevelPlacementError(
        "cannot find the level's object vector; refusing to add a placement "
        "the engine would never instantiate")


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

    A placement is three consecutive things in the stream: the resource ROOT
    (at the tail of the preceding literal), the entity PATH (a ref), and a
    fixed-size TRANSFORM record (the following literal). There is NO object
    count anywhere in the file — checked across six levels, every u32 equal to
    the placement count was coincidence — so the reader walks the stream to the
    section's declared length, and an insert is a duplicate of an existing
    placement with its transform rewritten.

    The bookkeeping that is easy to get wrong: `asset_refs._encode` only
    redistributes the length DELTAS of existing refs, so the bytes an insert
    adds are invisible to it. The owning section is grown here by exactly the
    inserted size, which keeps `sum(section_lens) == len(concat)` and leaves the
    section split where it was.

    `after` names the entity whose record is used as the template (default: the
    last placement). The template supplies the record's non-transform bytes,
    which this walk does not decode.
    """
    import json

    from .cooked_schemas import asset_refs as AR

    try:
        doc = AR._decode(level_bytes, "oCGameStream")
    except (ValueError, KeyError, IndexError, struct.error) as e:
        raise LevelPlacementError(f"not a readable level: {e}") from None
    refs, lits = doc["asset_refs"], doc["_literals"]
    cont = doc["_container"]

    idx = [i for i, r in enumerate(refs) if r.lower().endswith(".entity.ot")]
    if not idx:
        raise LevelPlacementError("level places no entity to copy a record from")
    if after is not None:
        idx = [i for i in idx if refs[i] == after] or idx

    def _rec(i: int) -> bytes | None:
        return bytes.fromhex(lits[i + 1]) if i + 1 < len(lits) else None

    # NEVER the LAST entity record, which is what `idx[-1]` used to take.
    # Measured across five shipped Dark Hills levels, the final entity ref's
    # record is a different size from every other one in the file -- 125B x29
    # + 267B, 143/142/23B + 80B, 125B + 1160B, 5 of 5 -- because it carries the
    # stream's TAIL: the chain on into the trailing material refs and the
    # section end, not just a transform. Duplicating it inserted a copy of that
    # tail into the middle of the stream, and the two 267B records then both
    # decoded as an object at the origin, which is exactly the all-zeros false
    # positive `_at` exists to reject. In-game the placement produced nothing.
    #
    # Take the MODAL record size instead: the shape ordinary placements share.
    sizes: dict[int, list[int]] = {}
    for i in idx:
        rec = _rec(i)
        if rec is not None:
            sizes.setdefault(len(rec), []).append(i)
    if not sizes:
        raise LevelPlacementError("placement record is missing from the stream")
    modal = max(sizes, key=lambda n: (len(sizes[n]), n))
    if len(sizes[modal]) < 2:
        shape = ", ".join(f"{n}B x{len(v)}" for n, v in sorted(sizes.items()))
        raise LevelPlacementError(
            f"no placement shape in this level occurs more than once ({shape}) "
            f"— refusing to infer a transform layout from a single record")
    src = sizes[modal][-1]

    record = bytearray(_rec(src))
    # Detect the offset from EVERY record of this size, exactly as `decode`
    # does. One sample is not enough evidence: a lone record can agree with a
    # degenerate offset, and then the transform is written somewhere the reader
    # never looks.
    same_size = [bytes.fromhex(lits[i + 1]) for i in idx
                 if i + 1 < len(lits)
                 and len(bytes.fromhex(lits[i + 1])) == len(record)]
    off = _detect_offset(same_size or [bytes(record)])
    if off is None or _at(bytes(record), off) is None:
        raise LevelPlacementError(
            "cannot locate the transform in the template record; refusing to "
            "write a placement this walk does not understand")
    struct.pack_into("<3f", record, off, *pos)
    struct.pack_into("<4f", record, off + 12, *quat)
    struct.pack_into("<3f", record, off + 28, *scale)

    raw_ref = ref.encode("utf-8")
    added = 4 + len(raw_ref) + len(record)

    # Grow the section that owns the insertion point, or `_encode` splits the
    # stream at the old boundaries and silently truncates the tail.
    section_lens = list(cont["section_lens"])
    bounds, acc = [], 0
    for sl in section_lens:
        bounds.append((acc, acc + sl))
        acc += sl
    at = cont["ref_offsets"][src]
    owner = next((si for si, (a, b) in enumerate(bounds) if a <= at < b),
                 len(section_lens) - 1)
    section_lens[owner] += added

    doc["asset_refs"] = refs[:src + 1] + [ref] + refs[src + 1:]
    # `literal[i + 1]` FOLLOWS `ref[i]`, so the record for a ref inserted at
    # src+1 belongs at literal src+2 — putting it at src+1 pairs it with the
    # PREVIOUS placement and the new object reads as an all-zero transform.
    # Copying the template also carries its trailing resource ROOT, which is
    # what the ref after ours needs, so the chain stays intact.
    new_lits = lits[:src + 2] + [record.hex()] + lits[src + 2:]

    # THE OBJECT VECTOR, without which none of the above is worth anything.
    # Everything before this line writes a well-formed object into the stream;
    # this line is what makes the level OWN it. Skipping it produced a mod tile
    # that was measured placed and built with nothing standing in it — the same
    # orphan the entity component vector produced one level down, and just as
    # silent (see `entity_append.component_vector`).
    vk, voff, ids = _object_vector([bytes.fromhex(h) for h in new_lits])
    blob = bytes.fromhex(new_lits[vk])
    grown = (blob[:voff] + struct.pack("<I", len(ids) + 1)
             + struct.pack(f"<{len(ids) + 1}I", *ids, len(ids))
             + blob[voff + 4 + 4 * len(ids):])
    new_lits[vk] = grown.hex()

    doc["_literals"] = new_lits
    cont["ref_offsets"] = (cont["ref_offsets"][:src + 1] + [at]
                           + cont["ref_offsets"][src + 1:])
    cont["ref_orig_lens"] = (cont["ref_orig_lens"][:src + 1] + [len(raw_ref)]
                             + cont["ref_orig_lens"][src + 1:])
    # The vector's 4 extra bytes belong to whichever section holds it, which is
    # not necessarily the one the placement went into.
    vstart = len(new_lits[0]) // 2
    for i in range(vk):
        vstart += 4 + len(doc["asset_refs"][i].encode("utf-8"))
        if i + 1 < vk:
            vstart += len(new_lits[i + 1]) // 2
    vstart += voff
    acc, vowner = 0, len(section_lens) - 1
    for si, sl in enumerate(section_lens):
        if acc <= vstart < acc + sl:
            vowner = si
            break
        acc += sl
    section_lens[vowner] += 4

    cont["section_lens"] = section_lens
    return AR._encode(json.dumps(doc).encode("utf-8"))
