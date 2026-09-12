"""Where a level STANDS the things it places.

`asset_refs` recovers what a level references; this recovers where. The gap
between the two cost three in-game reports — "some of them tipped over", "it is
not standing", "stuck in some stone" — all of which are one number the pipeline
could not read: the donor slot's rotation.
"""

from __future__ import annotations

import math
import struct

import pytest

from rsmm.engine import cooked
from rsmm.engine import level_placements as LP
from rsmm.engine import prop_cook as PC
from rsmm.engine.paths import DATA_DIR
from rsmm.sdk.kinds import poi as P

_BLOCKER = "DarkHills\\Tiles\\6x6_Blocker_02.level.ot"
_BONFIRE = "DarkHills\\Objects_DarkHills\\BonFire.entity.ot"

needs_corpus = pytest.mark.skipif(
    not (DATA_DIR / "uncooked").is_dir(),
    reason="uncooked corpus absent (run scripts/extract_uncooked.py)")


def _level(ref: str) -> bytes:
    return P._corpus(PC.level_cooked_path(ref), "test", "level")


@needs_corpus
def test_every_placement_decodes_to_a_unit_quaternion():
    """The invariant that proves the walk landed on a transform at all.

    Random bytes essentially never satisfy |q| = 1, so this is what separates a
    real decode from a plausible-looking one at the wrong offset.
    """
    placements = LP.decode(_level(_BLOCKER))
    assert len(placements) == 30, "6x6_Blocker_02 places 30 objects"
    for p in placements:
        n = math.sqrt(sum(c * c for c in p.quat))
        assert abs(n - 1.0) < 1e-3, f"{p.ref}: |q| = {n}"


@needs_corpus
def test_the_decoder_reads_the_hand_verified_slots():
    """Pinned against a hexdump read by hand, not against itself.

    ⚠ RE-PINNED 2026-09-12, and the old numbers were the wrong object's.
    The walk used to pair a reference with the bytes that FOLLOW it, but a
    reference sits near the end of its own object's block, so those bytes are
    the next block's. Every placement in every level was reported with its
    successor's position and rotation, and the last one with a run of zeros.
    The values below come from each object's own block: the log is not upright
    at all, it is a log lying at 27 degrees.
    """
    level = _level(_BLOCKER)
    barricade = LP.placements_of(
        level, "DarkHills\\SceneryObjects_DarkHills\\Barricade_Broken_2x2_B.entity.ot")
    log = LP.placements_of(
        level, "DarkHills\\SceneryObjects_DarkHills\\Log_4m_Broken_B.entity.ot")
    assert len(barricade) == 1 and len(log) == 1
    assert barricade[0].tilt_deg == pytest.approx(11.19, abs=0.05)
    assert barricade[0].pos == pytest.approx((0.8425, 0.0587, 0.9776), abs=1e-3)
    assert log[0].tilt_deg == pytest.approx(27.09, abs=0.05)
    assert log[0].pos == pytest.approx((1.2936, -0.5282, -0.2686), abs=1e-3)


@needs_corpus
def test_a_padding_run_is_not_mistaken_for_a_transform():
    """The failure this walk is most likely to have: an identity quaternion is
    unit and a (1,1,1) scale is in range, so a block of zeros scores as a
    perfect transform. It won on a tie once, with a denormal 5.6e-45 standing in
    for a coordinate — every object came back upright at the origin."""
    placements = LP.decode(_level(_BLOCKER))
    assert any(p.tilt_deg > 1.0 for p in placements), "all-upright means padding"
    assert any(any(c for c in p.pos) for p in placements), "all-origin means padding"


@needs_corpus
def test_a_level_that_does_not_decode_returns_nothing(monkeypatch):
    """Fails closed: callers use these to make refusals, so half a level's
    transforms would be worse than none."""
    def _no_graph(_inner):
        raise LP.LevelPlacementError("pretend a patch moved the object table")

    monkeypatch.setattr(LP, "_graph", _no_graph)
    assert LP.decode(_level(_BLOCKER)) == []


@needs_corpus
def test_nearest_orders_by_distance():
    level = _level(_BLOCKER)
    log = LP.placements_of(
        level, "DarkHills\\SceneryObjects_DarkHills\\Log_4m_Broken_B.entity.ot")[0]
    near = LP.nearest(level, log, limit=3)
    assert len(near) == 3
    assert near == sorted(near, key=lambda r: r[0])


@needs_corpus
def test_add_placement_adds_one_and_moves_nothing():
    """ADDING is the alternative to swapping, and the point is control: the new
    object takes the transform given here instead of inheriting a donor's."""
    level = _level(_BLOCKER)
    before = LP.decode(level)
    out = LP.add_placement(
        level, "DarkHills\\Objects_DarkHills\\BonFire.entity.ot",
        pos=(1.5, 0.0, -2.25), scale=(2.0, 2.0, 2.0))
    after = LP.decode(out)

    added = [p for p in after if p.ref.endswith("BonFire.entity.ot")]
    assert len(added) == 1
    assert added[0].pos == pytest.approx((1.5, 0.0, -2.25))
    assert added[0].scale == pytest.approx((2.0, 2.0, 2.0))
    assert added[0].tilt_deg == pytest.approx(0.0, abs=0.01)

    kept = [p for p in after if not p.ref.endswith("BonFire.entity.ot")]
    assert len(kept) == len(before), "an add must not drop a placement"
    for a, b in zip(kept, before, strict=True):
        assert a.ref == b.ref and a.pos == b.pos, "an add must not move anything"


@needs_corpus
def test_add_placement_survives_a_second_add():
    """Two adds must not fight over the section length; the second one is the
    case where the first add's own bytes are already in the stream."""
    level = _level(_BLOCKER)
    ref = "DarkHills\\Objects_DarkHills\\BonFire.entity.ot"
    once = LP.add_placement(level, ref, pos=(1.0, 0.0, 0.0))
    twice = LP.add_placement(once, ref, pos=(-1.0, 0.0, 0.0))
    assert len(LP.decode(twice)) == len(LP.decode(level)) + 2
    xs = sorted(p.pos[0] for p in LP.decode(twice) if p.ref.endswith("BonFire.entity.ot"))
    assert xs == pytest.approx([-1.0, 1.0])


@needs_corpus
def test_add_placement_refuses_a_level_it_cannot_read():
    """It writes into a level, so an unreadable template must stop it rather
    than produce a plausible-looking record at a guessed offset."""
    with pytest.raises(LP.LevelPlacementError):
        LP.add_placement(b"not a level", "x\\y.entity.ot", pos=(0, 0, 0))

@needs_corpus
def test_the_added_block_is_a_whole_object_not_a_spliced_record():
    """A placement is a self-framed BLOCK, which retires a whole class of bug.

    The walk used to work in the space BETWEEN asset references, where a
    "record" straddles two objects and the last one carries the stream's ending.
    Copying that tail spliced the file's ending into its middle. Copying a block
    cannot: it begins at a MARK_BEGIN and ends at its own MARK_END, so the
    inserted object is the same shape as every other one in the table.
    """
    level = _level(_BLOCKER)
    out = LP.add_placement(level, _BONFIRE, pos=(1.0, 0.0, 2.0))
    _cf, _sec, inner = LP._inner(out)
    g = LP._graph(inner)

    ours = [i for i, (_b, _e, blk) in enumerate(g.objects)
            if (got := LP._as_placement(blk)) is not None and got[0] == _BONFIRE]
    assert ours == [g.count - 1], "the new object must be the last one in the table"
    sizes = {len(blk) for _b, _e, blk in g.objects
             if (got := LP._as_placement(blk)) is not None}
    assert len(g.objects[ours[0]][2]) in sizes


@needs_corpus
def test_a_level_that_places_nothing_copyable_is_refused():
    """Fail closed: with no shipped placement to copy, there is no template."""
    level = _level("DarkHills\\Map_Dark_Hills_Collisions.level.ot")
    assert LP.decode(level) == []
    with pytest.raises(LP.LevelPlacementError, match="nothing this walk can copy"):
        LP.add_placement(level, _BONFIRE, pos=(0.0, 0.0, 0.0))


@needs_corpus
def test_a_level_with_a_single_placement_is_enough():
    """The transform's offset is STRUCTURAL, so one sample is a whole template.

    This level was refused outright while the offset had to be inferred by
    consensus across same-sized records, which needed at least two of them.
    Reading the layout instead of searching for it costs that restriction
    nothing and buys 70 more levels.
    """
    level = _level("DarkHills\\Tiles\\3x3_Blocker_01.level.ot")
    out = LP.add_placement(level, _BONFIRE, pos=(0.5, 0.0, 1.5))
    added = [p for p in LP.decode(out) if p.ref == _BONFIRE]
    assert len(added) == 1
    assert added[0].pos == pytest.approx((0.5, 0.0, 1.5))


def _graph_of(level: bytes):
    _cf, _sec, inner = LP._inner(level)
    return LP._graph(inner)


@needs_corpus
def test_the_whole_corpus_keeps_the_engines_object_grammar():
    """The three invariants the append is built on, checked where they came from.

    Read off the write side (`Serializer_ReadObjectNamed`): the engine
    instantiates exactly `uOjbectsCount` objects from the class indices beside
    it and then reads one payload block per object with no seek. So a table of
    count m must be followed by exactly m payload blocks plus one root block,
    entry i must name the class of block i, and every id the root owns must
    point inside the table. If a game patch moves any of that, `add_placement`
    must start failing loudly rather than corrupting a stream again.
    """
    levels = sorted((DATA_DIR / "uncooked" / "Ot").rglob("*.level.ot.GameStream.gen"))
    assert levels, "corpus has no levels"
    for path in levels:
        g = _graph_of(path.read_bytes())
        assert len(g.objects) == g.count, path.name
        for i, (_b, _e, blk) in enumerate(g.objects):
            assert struct.unpack_from("<I", blk, 0)[0] == g.class_idx[i], path.name
        (rn,) = struct.unpack_from("<I", g.root[2], 4)
        ids = struct.unpack_from(f"<{rn}I", g.root[2], 8)
        assert rn <= g.count and all(i < g.count for i in ids), path.name


@needs_corpus
def test_add_placement_makes_the_engine_instantiate_the_object():
    """The line between a placement and a CORRUPT stream.

    Three writes make an object and this used to do only the third. The engine
    creates exactly `uOjbectsCount` instances before it reads a payload byte,
    then reads one block per object sequentially, so a block spliced in without
    growing that count shifts every following object onto its predecessor's
    bytes. Measured on four shipped levels 2026-09-12: one extra payload block,
    `uOjbectsCount` untouched, and the level's own block consumed as a prop.
    """
    level = _level(_BLOCKER)
    before = _graph_of(level)
    out = LP.add_placement(level, _BONFIRE, pos=(0.0, 0.0, 0.0))
    after = _graph_of(out)

    # 1. the object exists at all
    assert after.count == before.count + 1
    assert after.class_idx[:-1] == before.class_idx
    # 2. its payload block is there, in table order, and is the last one
    assert len(after.objects) == after.count
    assert struct.unpack_from("<I", after.objects[-1][2], 0)[0] == after.class_idx[-1]
    # 3. the level owns it
    (rn_b,) = struct.unpack_from("<I", before.root[2], 4)
    (rn_a,) = struct.unpack_from("<I", after.root[2], 4)
    ids = list(struct.unpack_from(f"<{rn_a}I", after.root[2], 8))
    assert rn_a == rn_b + 1 and ids[-1] == before.count

    assert len(LP.decode(out)) == len(LP.decode(level)) + 1


@needs_corpus
def test_an_added_object_never_renumbers_an_existing_one():
    """Why the new block goes immediately BEFORE the root and nowhere else.

    An id is a position in the stream, so an insert in the middle would shift
    every later object's id and silently repoint every vector that names one.
    Appending takes id `count` and leaves every existing id meaning what it did.
    """
    level = _level(_BLOCKER)
    before = _graph_of(level)
    after = _graph_of(LP.add_placement(level, _BONFIRE, pos=(0.0, 0.0, 0.0)))
    for i, (_b, _e, blk) in enumerate(before.objects):
        assert after.objects[i][2] == blk, f"object {i} moved or changed"
    (rn,) = struct.unpack_from("<I", before.root[2], 4)
    kept = struct.unpack_from(f"<{rn}I", before.root[2], 8)
    (rn2,) = struct.unpack_from("<I", after.root[2], 4)
    assert struct.unpack_from(f"<{rn2}I", after.root[2], 8)[:rn] == kept


@needs_corpus
def test_add_placement_restamps_the_streams_self_declared_size():
    """The size the level's wrapper DECLARES, which nothing else in the repo reads.

    ⚠ MEASURED IN-GAME 2026-09-08 and this is the whole reason an added POI was
    invisible. The wrapper states the inner stream's length twice, and a grown
    stream that still declares the old one is read short: the engine never
    reaches the objects past the cut, so the tile is placed and built with
    nothing in it. Invisible to every other check, because the file parses,
    round-trips and decodes one more placement than it had.
    """
    level = _level(_BLOCKER)
    out = LP.add_placement(level, _BONFIRE, pos=(1.0, 0.0, 2.0))
    assert len(out) > len(level), "the placement must have added bytes"
    # A second add: the baseline has to survive a round trip, not just the first.
    out = LP.add_placement(out, _BONFIRE, pos=(-1.0, 0.0, 2.0))

    sec = cooked.parse(out).sections[-1].payload
    a, b = struct.unpack_from("<II", sec, 8)
    assert a == b == len(sec) - 16, (
        f"wrapper declares {a}/{b} for a payload of {len(sec)} bytes")
    assert cooked.emit(cooked.parse(out)) == out


@needs_corpus
def test_every_shipped_level_with_a_template_survives_an_add():
    """The whole corpus through the append, checked against the engine's rules.

    A level that cannot be read must refuse; one that can must come out the
    other side with a graph the engine would accept.
    """
    levels = sorted((DATA_DIR / "uncooked" / "Ot").rglob("*.level.ot.GameStream.gen"))
    added = refused = 0
    for path in levels:
        raw = path.read_bytes()
        try:
            out = LP.add_placement(raw, _BONFIRE, pos=(1.25, 0.5, -2.0))
        except LP.LevelPlacementError:
            refused += 1
            continue
        added += 1
        g = _graph_of(out)
        assert len(g.objects) == g.count, path.name
        assert g.root[1] == len(g.inner), path.name
        assert cooked.emit(cooked.parse(out)) == out, path.name
        assert len(LP.decode(out)) == len(LP.decode(raw)) + 1, path.name
    assert added >= 349 and refused <= 41, (added, refused)
