"""The map-generation recipe: read it, and be able to write it back unchanged.

Byte-identical round-trip is the whole proof. A codec that decodes into
plausible-looking numbers but cannot reproduce the file it came from has not
understood the layout, it has found a reading that happens to fit — which is
exactly the failure the old placement decoder shipped for months.
"""

from __future__ import annotations

import pytest

from rsmm.engine import tilegen as TG
from rsmm.engine.paths import DATA_DIR

needs_corpus = pytest.mark.skipif(
    not (DATA_DIR / "uncooked" / "Ot").is_dir(),
    reason="uncooked corpus absent (run scripts/extract_uncooked.py)")


def _levels():
    root = DATA_DIR / "uncooked" / "Ot"
    return sorted(root.glob("*/Map_*_TileGeneration.level.ot.GameStream.gen"))


@needs_corpus
def test_the_corpus_has_the_three_tile_generated_chapters():
    """Baba Yaga is the scripted boss arena and generates no tiles, so three."""
    assert len(_levels()) == 3


@needs_corpus
@pytest.mark.parametrize("path", _levels(), ids=lambda p: p.parent.name)
def test_recipe_round_trips_byte_identically(path):
    raw = path.read_bytes()
    assert TG.write(raw, TG.read(raw)) == raw


@needs_corpus
@pytest.mark.parametrize("path", _levels(), ids=lambda p: p.parent.name)
def test_every_cross_dimension_holds(path):
    """`validate` runs inside `read`; this states the invariants it enforces.

    Each one is a way the engine could be handed a recipe it would misread in
    silence: a mask indexed by the wrong kind, a slot in no footprint group.
    """
    tg = TG.read(path.read_bytes())
    nk = len(tg.spawner.kind_ids)
    ns = len(tg.spawner.scenarios)
    ng = len(tg.spawner.size_ids)

    assert nk == len(tg.kinds) and ng == len(tg.sizes)
    for k in tg.kinds.values():
        assert len(k.footprints) == ng
    for s in tg.slots.values():
        if not s.kinds:
            continue
        assert len(s.kinds) == nk
        assert len(s.compat) == ns
        assert all(len(row) == nk for row in s.compat)

    listed = set(tg.spawner.whole_map.slots)
    for i in tg.spawner.size_ids:
        listed |= set(tg.sizes[i].slots)
    assert listed == set(tg.slots), "every slot belongs to exactly one group"


@needs_corpus
@pytest.mark.parametrize("path", _levels(), ids=lambda p: p.parent.name)
def test_the_recipe_names_its_own_mapdef(path):
    """`+0x0f8` is the backref that ties the recipe to the chapter it builds."""
    tg = TG.read(path.read_bytes())
    root, ref = tg.spawner.mapdef
    assert root == "Definitions"
    assert ref.startswith("Maps\\") and ref.endswith(".mapdef.ot")


@needs_corpus
def test_dark_hills_reads_the_numbers_a_modder_would_edit():
    """A regression fence on the semantics, not just the shape.

    These are the values that make a chapter feel like itself, and every one of
    them was unreadable before the grammar was taken off the engine's write
    side.
    """
    path = next(p for p in _levels() if p.parent.name == "DarkHills")
    tg = TG.read(path.read_bytes())
    by = {k.name: k for k in tg.kinds.values()}

    assert by["Crystal"].count == 50
    assert by["Teleporter"].count == 17
    assert by["Teleporter"].min_distance == pytest.approx(55.0)
    assert by["Start"].count == 1 and by["Map_Boss"].count == 1

    # The footprint mask is what makes those counts placeable: a 40x40 start
    # tile cannot go in a 3x3 blocker slot, and the mask says so.
    groups = tg.size_names
    assert groups == ["3x3", "6x6", "40x40", "64x64"]
    assert by["Start"].footprints == [0, 0, 1, 0]
    assert by["Map_Boss"].footprints == [0, 0, 0, 1]
    assert by["Crystal"].footprints == [1, 1, 0, 0]

    assert [s.label for s in tg.spawner.scenarios] == [
        f"Enemy Camp Difficulty 0{i}" for i in (1, 2, 3, 4)]
    assert {q.flags[0]: q.limit for q in tg.spawner.quotas}["Wishing_Well"] == 1


@needs_corpus
def test_editing_a_kind_changes_only_that_kind():
    """The write path is in-place: no object moves, so no id is invalidated."""
    path = next(p for p in _levels() if p.parent.name == "DarkHills")
    raw = path.read_bytes()
    tg = TG.read(raw)
    kid = next(i for i, k in tg.kinds.items() if k.name == "Fountain")
    tg.kinds[kid].count = 12
    out = TG.write(raw, tg)

    again = TG.read(out)
    assert {k.name: k.count for k in again.kinds.values()}["Fountain"] == 12
    assert len(again.slots) == len(tg.slots)
    assert [s.pos for s in again.slots.values()] == [s.pos for s in tg.slots.values()]
    # One u32 differs, and the file keeps its length: nothing was re-laid-out.
    assert len(out) == len(raw)


@needs_corpus
def test_slots_for_refuses_a_kind_the_chapter_does_not_have():
    path = next(p for p in _levels() if p.parent.name == "DarkHills")
    tg = TG.read(path.read_bytes())
    assert tg.slots_for("Fountain")
    with pytest.raises(TG.TileGenError):
        tg.slots_for("Not_A_Kind")


# --------------------------------------------------------------------------
# changing the object count: add/remove slots, add kinds
# --------------------------------------------------------------------------

@needs_corpus
@pytest.mark.parametrize("path", _levels(), ids=lambda p: p.parent.name)
def test_a_renumbering_rebuild_of_an_unchanged_recipe_is_byte_identical(path):
    """The proof that `_rebuild` sees every id reference: if it missed one, the
    shipped layout (kinds, groups, slots after the fixed prefix) would still
    come back, but some vector would point at the wrong object."""
    from rsmm.engine.level_placements import _graph, _inner

    raw = path.read_bytes()
    cf, sec, inner = _inner(raw)
    g = _graph(inner)
    assert TG._rebuild(cf, sec, inner, g, TG._class_names(g), TG.read(raw)) == raw


@needs_corpus
@pytest.mark.parametrize("path", _levels(), ids=lambda p: p.parent.name)
def test_slots_and_kinds_can_be_added_and_removed(path):
    raw = path.read_bytes()
    tg = TG.read(raw)
    n_slots, n_kinds = len(tg.slots), len(tg.kinds)
    victim = next(i for i in sorted(tg.slots) if i not in tg.spawner.whole_map.slots)
    gone_pos = tg.slots[victim].pos
    TG.remove_slot(tg, victim)
    TG.add_slot(tg, "40x40", (12.5, 3.0, -7.25), {"Start": True})
    TG.add_slot(tg, "40x40", (99.0, 0.0, 99.0))
    TG.add_kind(tg, "RSMM_Placed_1", count=1, footprints={"40x40": True})

    out = TG.write(raw, tg)
    back = TG.read(out)
    assert (len(back.slots), len(back.kinds)) == (n_slots + 1, n_kinds + 1)
    assert gone_pos not in {s.pos for s in back.slots.values()}
    new = next(s for s in back.slots.values() if s.pos == (12.5, 3.0, -7.25))
    assert new.kinds[back.kind_names.index("Start")] == 1
    assert all(row == [2] * len(back.kind_names) for row in new.compat)
    assert back.kind_names[-1] == "RSMM_Placed_1"
    assert back.kinds[back.spawner.kind_ids[-1]].count == 1
    assert TG.write(out, back) == out


@needs_corpus
def test_bad_slot_and_kind_edits_are_refused():
    raw = _levels()[0].read_bytes()
    tg = TG.read(raw)
    with pytest.raises(TG.TileGenError, match="footprint group"):
        TG.add_slot(tg, "99x99", (0, 0, 0))
    with pytest.raises(TG.TileGenError, match="no kind"):
        TG.add_slot(tg, "40x40", (0, 0, 0), {"Nope": True})
    with pytest.raises(TG.TileGenError, match="whole-map"):
        TG.remove_slot(tg, tg.spawner.whole_map.slots[0])
    with pytest.raises(TG.TileGenError, match="already exists"):
        TG.add_kind(tg, "Camp")
