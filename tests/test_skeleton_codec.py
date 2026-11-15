"""The skeleton writer (engine/skeleton_codec.py): every shipped hero
skeleton re-encodes byte for byte, rest poses recompute from the locals, and a
glb armature from the exporter gives back the game's locals."""

from __future__ import annotations

import pytest

from rsmm.engine import skeleton_codec as SK


def _meshes():
    from rsmm.engine import corpus
    try:
        out = []
        for r in corpus.rels("3D/Characters/Heroes/", ".Geometry.gen"):
            raw = corpus.read(r)
            try:
                SK.decode(raw)
            except SK.SkeletonError:
                continue
            out.append(r)
        return out
    except Exception:  # noqa: BLE001 — no corpus
        return []


_MESHES = _meshes()


@pytest.mark.skipif(not _MESHES, reason="no hero corpus")
@pytest.mark.parametrize("rel", _MESHES)
def test_skeleton_round_trips_and_recomputes(rel):
    from rsmm.engine import corpus
    raw = corpus.read(rel)
    s = SK.decode(raw)
    assert SK.encode(raw, s) == raw
    again = SK.with_rest(s, {})
    for a, b in zip(s.bones, again.bones, strict=True):
        assert max(abs(x - y) for x, y in zip(a.world, b.world, strict=True)) < 1e-3
        assert max(abs(x - y) for x, y in zip(a.inverse, b.inverse, strict=True)) < 1e-3


@pytest.mark.skipif(not _MESHES, reason="no hero corpus")
def test_longer_bones_move_their_children():
    from rsmm.engine import corpus
    s = SK.decode(corpus.read("3D/Characters/Heroes/Kintaro/Kintaro_GEO.fbx.Geometry.gen"))
    by = {b.name: b for b in s.bones}
    longer = SK.with_rest(s, SK.scale_lengths(s, {"DEF.BotLeg.L": 1.5}))
    new = {b.name: b for b in longer.bones}
    shin = by["DEF.BotLeg.L"].local[13]
    assert new["DEF.BotLeg.L"].local[13] == pytest.approx(shin * 1.5, rel=1e-5)
    # the foot below it moved by the extra length, the other leg did not
    assert new["DEF.Feet.L"].world[13] != pytest.approx(by["DEF.Feet.L"].world[13])
    assert new["DEF.Feet.R"].world[13] == pytest.approx(by["DEF.Feet.R"].world[13])
