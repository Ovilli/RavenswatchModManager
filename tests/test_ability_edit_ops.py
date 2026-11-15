"""The animatic and level-scaling ability steps (PR #149): `add_cinebloc`,
`animatic_speed`, `scale_with_level`, on a shipped hero."""

from __future__ import annotations

import struct

import pytest

from rsmm.engine import ability_edit as AE
from rsmm.engine import entity_check as EC
from rsmm.engine import entity_graph as EG

_RED = "EntitySettings/Heroes/Hero_Red/Hero_Red.entity.ot.EntitySettingsResource.gen"


def _raw():
    from rsmm.engine import corpus
    try:
        return corpus.read(_RED)
    except Exception:  # noqa: BLE001
        return None


needs_corpus = pytest.mark.skipif(_raw() is None, reason="no hero corpus")


def _apply(steps):
    raw = _raw()
    out = AE.apply({"Hero_Red": raw}, steps, main="Hero_Red", seed="t").files["Hero_Red"]
    assert EC.check(out, raw, name="Hero_Red") == []
    return out


def _timeline(ef, comp):
    """(bloc count, duration, play rate) of animatic ``comp``."""
    from rsmm.engine.entity_graph_edit import _B
    c, f, at = ef._field(comp, "bytes_8")
    p = ef.objects[c.index - 1]
    pos = p.find(_B + struct.pack("<I", [x.name for x in ef.cf.classes].index("oCCinematic")))
    n = struct.unpack_from("<I", p, pos + 8)[0]
    return (n, struct.unpack_from("<f", p, pos + 12 + 4 * n)[0],
            struct.unpack_from("<f", p, at + f.offset)[0])


@needs_corpus
def test_a_cine_bloc_is_added_at_its_start_and_the_animatic_rate_rescales_its_length():
    from rsmm.engine.entity_graph_edit import EntityFile
    anim = "Dash Ability Anim"
    n0, dur0, rate0 = _timeline(EntityFile(_raw(), "Hero_Red"), anim)
    out = _apply([
        {"add_cinebloc": anim, "to": "Agressive Defense FMod Event Active", "value": 0.2},
        {"animatic_speed": anim, "value": 2.0}])
    ef = EntityFile(out, "Hero_Red")
    n1, dur1, rate1 = _timeline(ef, anim)
    assert n1 == n0 + 1
    _c, sub = ef._cinebloc(anim, n0)
    assert struct.unpack_from("<f", ef.objects[sub], 4)[0] == pytest.approx(0.2)
    assert rate1 == 2.0
    assert dur1 == pytest.approx(dur0 * (rate0 if rate0 > 0 else 1.0) / 2.0)
    with pytest.raises(AE.AbilityEditError, match="value"):
        _apply([{"animatic_speed": anim}])
    with pytest.raises(AE.AbilityEditError, match="speed must be > 0"):
        _apply([{"animatic_speed": anim, "value": 0}])


@needs_corpus
def test_scale_with_level_reads_the_owners_level_damage():
    mod = "Basic Wide Attacks AP Modifier"
    out = _apply([{"scale_with_level": mod, "value": 10.0}])
    g = {c.name: c for c in EG.parse(out, "Hero_Red").components}
    scaled = g[f"{mod} Level Scaled"]
    assert any(r.guid == scaled.guid for r in g[mod].refs)
    assert {r.path.rsplit("\\", 1)[-1] for r in scaled.refs} >= {
        "Owner Level Damage", f"{mod} Level Ratio"}
