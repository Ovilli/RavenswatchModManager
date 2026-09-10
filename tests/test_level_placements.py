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
    """Pinned against a hexdump read by hand, not against itself."""
    level = _level(_BLOCKER)
    barricade = LP.placements_of(
        level, "DarkHills\\SceneryObjects_DarkHills\\Barricade_Broken_2x2_B.entity.ot")
    log = LP.placements_of(
        level, "DarkHills\\SceneryObjects_DarkHills\\Log_4m_Broken_B.entity.ot")
    assert len(barricade) == 1 and len(log) == 1
    assert barricade[0].tilt_deg == pytest.approx(11.2, abs=0.2)
    assert log[0].tilt_deg == pytest.approx(0.0, abs=0.2)
    assert barricade[0].pos[0] == pytest.approx(1.52, abs=0.01)


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
    monkeypatch.setattr(LP, "_detect_offset", lambda blobs: None)
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
def test_the_template_is_never_the_streams_tail_record():
    """The last entity record is the TAIL, not an ordinary placement.

    Measured on five shipped Dark Hills levels, the final entity ref's record
    is a different size from every other one in the file, because it carries
    the chain on into the trailing material refs. `add_placement` used to take
    exactly that record as its template (`idx[-1]`), so every inserted
    placement was a duplicated tail — and the two same-sized records then both
    decoded as an object at the origin, the all-zeros false positive `_at`
    exists to reject. In-game it produced no object at all.
    """
    level = _level(_BLOCKER)
    out = LP.add_placement(level, _BONFIRE, pos=(1.0, 0.0, 2.0))

    from rsmm.engine.cooked_schemas import asset_refs as AR
    doc = AR._decode(out, "oCGameStream")
    refs, lits = doc["asset_refs"], doc["_literals"]
    ents = [(i, len(bytes.fromhex(lits[i + 1]))) for i, r in enumerate(refs)
            if r.lower().endswith(".entity.ot") and i + 1 < len(lits)]
    ours = [n for i, n in ents if refs[i] == _BONFIRE]
    assert len(ours) == 1, ours

    counts: dict[int, int] = {}
    for _i, n in ents:
        counts[n] = counts.get(n, 0) + 1
    # Our record must share the shape the ordinary placements use, not the
    # one-of-a-kind tail shape.
    assert counts[ours[0]] > 1, (
        f"inserted a record of a size nothing else uses: {counts}")


@needs_corpus
def test_a_level_with_no_repeated_record_shape_is_refused():
    """One sample cannot establish a transform layout, so fail closed."""
    level = _level("DarkHills\\Tiles\\3x3_Blocker_01.level.ot")
    with pytest.raises(LP.LevelPlacementError, match="more than once"):
        LP.add_placement(level, _BONFIRE, pos=(0.0, 0.0, 0.0))


def _object_vector_of(level: bytes) -> list[int]:
    """The level's own object list, read straight out of the bytes."""
    i = level.rfind(cooked.MARK_BEGIN)
    assert i >= 0
    (n,) = struct.unpack_from("<I", level, i + 8)
    return list(struct.unpack_from(f"<{n}I", level, i + 12))


@needs_corpus
def test_the_whole_corpus_keeps_its_object_vector_at_the_last_begin():
    """The invariant the append is built on, checked where it came from.

    390 of 390 shipped levels put a `u32 count` + `0..count-1` right after the
    trailer's last BEGIN. If a game patch moved it, `add_placement` must start
    failing loudly rather than writing an orphan again.
    """
    levels = sorted((DATA_DIR / "uncooked" / "Ot").rglob("*.level.ot.GameStream.gen"))
    assert levels, "corpus has no levels"
    for p in levels:
        ids = _object_vector_of(p.read_bytes())
        assert ids == list(range(len(ids))), p.name


@needs_corpus
def test_add_placement_grows_the_levels_object_vector():
    """The line between a placement and an ORPHAN.

    A record written into the stream but absent from this vector deserializes,
    is byte-stable, passes every cache and reference check — and is never
    instantiated. That is what made a mod tile measure PLACED and BUILT with
    nothing standing in it.
    """
    level = _level(_BLOCKER)
    before = _object_vector_of(level)
    out = LP.add_placement(level, _BONFIRE, pos=(0.0, 0.0, 0.0))
    after = _object_vector_of(out)

    assert after == list(range(len(before) + 1)), "the added object must be owned"
    assert len(LP.decode(out)) == len(LP.decode(level)) + 1


def _self_sized_sections(level: bytes) -> dict[int, int]:
    """`{section index: declared size}` for sections carrying a self-size.

    A section states its own length twice, as u32s at payload `+0x08` and
    `+0x0c`, biased by 16. Only sections that already satisfy the invariant are
    reported, so a class without the header is simply absent rather than wrong.
    """
    out = {}
    for i, s in enumerate(cooked.parse(level).sections):
        pl = s.payload
        if len(pl) < 16:
            continue
        a, b = struct.unpack_from("<II", pl, 8)
        if a == b and a == len(pl) - 16:
            out[i] = a
    return out


@needs_corpus
def test_add_placement_restamps_the_sections_self_declared_size():
    """The size a grown section DECLARES, which nothing else in the repo reads.

    ⚠ MEASURED IN-GAME 2026-09-08 and this is the whole reason an added POI was
    invisible. `add_placement` grows `section_lens` itself, and `_encode` used
    to take that already-grown list as its restamp BASELINE — so the restamp saw
    "nothing changed", kept the pre-insert size, and the engine read the level
    short by exactly the inserted bytes. That cut the object vector in half:
    the tile was placed and built, and NOTHING in the level was instantiated.

    Invisible to every other check. The file parses, round-trips, decodes one
    more placement than it had and passes every cache and reference test.
    """
    level = _level(_BLOCKER)
    sized = _self_sized_sections(level)
    assert sized, "6x6_Blocker_02 must carry a self-size to test against"

    out = LP.add_placement(level, _BONFIRE, pos=(1.0, 0.0, 2.0))
    assert len(out) > len(level), "the placement must have added bytes"
    # A second add on the output: the baseline has to survive a decode/encode
    # round trip, not just the first one.
    out = LP.add_placement(out, _BONFIRE, pos=(-1.0, 0.0, 2.0))

    still = _self_sized_sections(out)
    for i in sized:
        assert i in still, (
            f"section {i} lost its self-size: it declares "
            f"{struct.unpack_from('<II', cooked.parse(out).sections[i].payload, 8)} "
            f"for a payload of {len(cooked.parse(out).sections[i].payload)} bytes")
