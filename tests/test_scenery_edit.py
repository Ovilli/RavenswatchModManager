"""Chapter scenery edits: move, sink, add (`engine/scenery_edit`, kind `scenery`).

Needs game data (mirror or install); skips without it.
"""

from __future__ import annotations

import tomllib

import pytest

from rsmm.engine import corpus
from rsmm.engine import level_placements as LP
from rsmm.engine import map_editor as ME
from rsmm.engine import scenery_edit as SE

LEVEL = "Ot/DarkHills/Map_Dark_Hills_Scenery_SouthWest.level.ot.GameStream.gen"
needs_game = pytest.mark.skipif(
    corpus.read(LEVEL) is None, reason="no game data (uncooked mirror or install)"
)


@pytest.fixture(scope="module")
def chapter():
    return ME.find_chapter("DarkHills")


@pytest.fixture(scope="module")
def shipped():
    return corpus.read(LEVEL)


@needs_game
def test_rewriting_every_transform_unchanged_is_byte_stable(shipped):
    objs = LP.objects(shipped)
    assert len(objs) > 1000
    assert LP.set_transforms(shipped, {i: (p.pos, p.quat, p.scale) for i, p in objs}) == shipped


@needs_game
def test_a_move_touches_only_that_object(shipped):
    objs = LP.objects(shipped)
    oid, p = objs[7]
    out = LP.set_transforms(
        shipped, {oid: ((p.pos[0] + 2, p.pos[1], p.pos[2]), p.quat, (2.0, 2.0, 2.0))}
    )
    assert len(out) == len(shipped)
    after = dict(LP.objects(out))
    assert after[oid].pos[0] == pytest.approx(p.pos[0] + 2) and after[oid].scale == (2.0, 2.0, 2.0)
    assert all(after[i] == q for i, q in objs if i != oid)


@needs_game
def test_apply_moves_sinks_and_adds(chapter, shipped):
    objs = LP.objects(shipped)
    (a, pa), (b, pb) = objs[3], objs[4]
    prop = next(p["entity"] for p in SE.chapter_props(chapter) if p["scenery"])
    out, notes = SE.apply(
        chapter,
        LEVEL,
        {
            "moves": {
                str(a): {
                    "entity": pa.ref,
                    "at": list(pa.pos),
                    "pos": [pa.pos[0] + 1, pa.pos[1], pa.pos[2]],
                    "yaw": 90,
                    "scale": 1.5,
                }
            },
            "removes": {str(b): {"entity": pb.ref, "at": list(pb.pos)}},
            "adds": [{"entity": prop, "pos": list(pa.pos), "yaw": 0, "scale": 1}],
        },
    )
    after = LP.objects(out)
    assert len(after) == len(objs) + 1 and len(notes) == 3
    got = dict(after)
    assert got[b].pos[1] == pytest.approx(pb.pos[1] - SE.SINK)
    assert got[a].scale == (1.5, 1.5, 1.5)
    assert after[-1][1].ref == prop


@needs_game
def test_apply_refuses_a_stale_anchor_and_an_uncached_add(chapter, shipped):
    oid, p = LP.objects(shipped)[3]
    with pytest.raises(SE.SceneryEditError, match="game changed"):
        SE.apply(
            chapter,
            LEVEL,
            {
                "moves": {
                    str(oid): {
                        "entity": p.ref,
                        "at": [p.pos[0] + 5, p.pos[1], p.pos[2]],
                        "pos": [0, 0, 0],
                    }
                }
            },
        )
    with pytest.raises(SE.SceneryEditError, match="already places"):
        SE.apply(
            chapter, LEVEL, {"adds": [{"entity": "Nope\\Not_Here.entity.ot", "pos": [0, 0, 0]}]}
        )


@needs_game
def test_scenery_json_draws_what_the_scene_view_draws(chapter):
    sj = SE.scenery_json(chapter)
    import base64

    instances = sum(len(base64.b64decode(m)) // 64 for m in sj["matrices"])
    owners = sum(len(base64.b64decode(o)) // 4 for o in sj["owners"])
    assert instances == owners == ME.scene_json(chapter)["instances"]
    assert sj["objects"]["count"] == sum(len(LP.objects(corpus.read(lv))) for lv in sj["levels"])


@needs_game
def test_kind_emit_and_manifest_round_trip(chapter, shipped, tmp_path):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import scenery

    oid, p = LP.objects(shipped)[3]
    edits = {"removes": {str(oid): {"entity": p.ref, "at": list(p.pos)}}}
    files = scenery.emit(
        "m",
        ContentDef("scenery", "sw", {"chapter": "DarkHills", "level": LEVEL, **edits}),
        tmp_path,
    )
    assert [f.relative_to(tmp_path).as_posix() for f in files] == [LEVEL]

    text = ME.manifest_toml("my-scenery", "", chapter, {}, None, {LEVEL: edits})
    data = tomllib.loads(text)
    assert data["mod"]["experimental"] is True
    assert data["mod"]["multiplayer_scope"] == "deterministic-shared"
    assert [c["kind"] for c in data["content"]] == ["scenery"]  # no empty tilegen block
    assert ME.read_manifest(text)["scenery"] == {LEVEL: edits}
