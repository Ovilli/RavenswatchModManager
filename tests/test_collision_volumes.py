"""Collision volumes (engine/collision_volumes.py, poi ``collision``): walkable
ground and blocking wall boxes written onto a prop entity as clones of a
shipped COL_Ground record."""

from __future__ import annotations

import math

import pytest

from rsmm.engine import collision_volumes as CV

HOST = ("EntitySettings/DarkHills/SceneryObjects_DarkHills/Wall_Ruins_Block_Small_A"
        ".entity.ot.EntitySettingsResource.gen")


def _corpus() -> bool:
    try:
        from rsmm.engine import corpus
        return corpus.read(CV.DONOR) is not None and corpus.read(HOST) is not None
    except Exception:  # noqa: BLE001
        return False


needs_corpus = pytest.mark.skipif(not _corpus(), reason="no entity corpus")


@needs_corpus
def test_the_donor_reads_as_a_shipped_ground_box():
    from rsmm.engine import corpus
    name, rec = CV.read_volumes(corpus.read(CV.DONOR))[0]
    assert name == CV.DONOR_COMPONENT
    assert (rec["group"], rec["mask"], rec["shape"]) == (7, 1, CV.SHAPE_BOX)
    assert rec["half"] == (4.0, 1.0, 3.5)
    assert rec["obj_4"][8:10] == [-1.0, 3.5]      # centre y, z


@needs_corpus
def test_volumes_land_with_their_shape_transform_and_flags():
    from rsmm.engine import corpus
    from rsmm.engine import entity_graph as EG
    host = corpus.read(HOST)
    vols = CV.parse([
        {"kind": "ground", "size": [4, 1, 6], "at": [0, -0.5, 1]},
        {"kind": "ground", "size": [2, 0.5, 3], "at": [0, 0.2, 4], "rot": [-18, 0, 0]},
        {"kind": "wall", "size": [1, 2, 1], "at": [3, 1, 0], "rot": [0, 45, 0]},
    ])
    out = CV.add_volumes(host, vols, name="t", seed="t")
    got = dict(CV.read_volumes(out))
    assert list(got) == ["COL_RSMM_000", "COL_RSMM_001", "COL_RSMM_002"]
    a, b, c = got.values()
    assert (a["group"], a["mask"], a["half"]) == (7, 1, (2.0, 0.5, 3.0))
    assert a["obj_4"][7:10] == [0.0, -0.5, 1.0]
    assert math.isclose(b["obj_4"][13], math.radians(-18), abs_tol=1e-5)
    assert (c["group"], c["mask"]) == (8, 2)
    assert math.isclose(c["obj_4"][14], math.radians(45), abs_tol=1e-5)
    # the host keeps everything it had, and the boxes are real components
    before = [x.name for x in EG.parse(host, "h").components]
    after = [x.name for x in EG.parse(out, "h").components]
    assert after[:len(before)] == before and len(after) == len(before) + 3


@needs_corpus
def test_no_volumes_is_a_no_op():
    from rsmm.engine import corpus
    host = corpus.read(HOST)
    assert CV.add_volumes(host, []) == host


@pytest.mark.parametrize("bad, match", [
    ({"kind": "lava", "size": [1, 1, 1], "at": [0, 0, 0]}, "kind"),
    ({"size": [1, 0, 1], "at": [0, 0, 0]}, "positive"),
    ({"size": [1, 1], "at": [0, 0, 0]}, "three numbers"),
    ({"size": [1, 1, 1], "at": [0, 0, 999]}, "out of range"),
    ({"size": [1, 1, 1], "at": [0, 0, 0], "spin": 1}, "unknown key"),
])
def test_bad_volumes_are_refused(bad, match):
    with pytest.raises(CV.CollisionError, match=match):
        CV.parse([bad])


def test_the_poi_schema_takes_collision():
    from rsmm.sdk.kinds import poi
    item = poi.poi_json_schema()["properties"]["collision"]["items"]
    assert set(item["properties"]) == {"kind", "size", "at", "rot"}
    assert item["properties"]["kind"]["enum"] == sorted(CV.KINDS)


# --- poi `clear`: sink a cloned tile's own scenery -------------------------

POOL = "Ot/DarkHills/Tiles/40x40_Small_PoolPlatform_Ghouls_Camp.level.ot.GameStream.gen"


def _pool() -> bytes | None:
    try:
        from rsmm.engine import corpus
        return corpus.read(POOL)
    except Exception:  # noqa: BLE001
        return None


@pytest.mark.skipif(_pool() is None, reason="no tile corpus")
def test_clear_sinks_everything_but_the_camp():
    from types import SimpleNamespace

    from rsmm.engine import level_placements as LP
    from rsmm.engine.scenery_edit import SINK
    from rsmm.sdk.kinds import poi
    raw = _pool()
    out = poi._clear_level(raw, SimpleNamespace(id="t", fields={"own_level": True, "clear": True}))
    assert len(out) == len(raw)                       # rewritten in place
    before, after = dict(LP.objects(raw)), dict(LP.objects(out))
    assert before.keys() == after.keys()              # nothing renumbered
    standing = {p.ref.rsplit("\\", 1)[-1] for p in after.values() if p.pos[1] > -SINK / 2}
    assert standing == {"Enemy_Camp_Reward_Spawner_Dark_Hills.entity.ot",
                        "LD_Reward_Pedestal.entity.ot"}
    moved = [oid for oid in before if before[oid].pos != after[oid].pos]
    assert all(after[o].pos[1] == pytest.approx(before[o].pos[1] - SINK) for o in moved)
    # an explicit keep list wins over the default
    kept = poi._clear_level(raw, SimpleNamespace(
        id="t", fields={"own_level": True, "clear": {"keep": ["Rock_Moss"]}}))
    assert all("Rock_Moss" in p.ref for p in dict(LP.objects(kept)).values()
               if p.pos[1] > -SINK / 2)


@pytest.mark.skipif(_pool() is None, reason="no tile corpus")
def test_clear_refuses_the_shipped_level():
    from types import SimpleNamespace

    from rsmm.sdk.content import ContentError
    from rsmm.sdk.kinds import poi
    with pytest.raises(ContentError, match="own_level"):
        poi._clear_level(_pool(), SimpleNamespace(id="t", fields={"clear": True}))


@pytest.mark.skipif(_pool() is None, reason="no tile corpus")
def test_clear_remove_sinks_only_the_named_entities():
    from types import SimpleNamespace

    from rsmm.engine import level_placements as LP
    from rsmm.engine.scenery_edit import SINK
    from rsmm.sdk.kinds import poi
    raw = _pool()
    out = poi._clear_level(raw, SimpleNamespace(id="t", fields={
        "own_level": True, "clear": {"remove": ["Tree_Small_A.entity.ot"]}}))
    sunk = [p.ref for p in dict(LP.objects(out)).values() if p.pos[1] < -SINK / 2]
    assert sunk and all(r.endswith("\\Tree_Small_A.entity.ot") for r in sunk)
