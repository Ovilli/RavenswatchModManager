"""`hero` kind: a clone is a new herodef + its own resource cache.

The hero-select roster is every registered oCDtHeroDefinition (FUN_140209b00
copies Registry_EnumInstances unfiltered), so these two files are the whole
contract — the same self-registration the enemy clone proved in game.
"""

from __future__ import annotations

import pytest

from rsmm.engine import enemy_pools as EP
from rsmm.engine import rsc_cache as RC
from rsmm.sdk.content import ContentDef, ContentError
from rsmm.sdk.kinds import heros

needs_corpus = pytest.mark.skipif(not heros.shipped_heroes(), reason="no hero corpus")


def _emit(tmp_path, id="Zz_Piper_Clone", **fields):
    return heros.emit("m", ContentDef(kind="hero", id=id, fields={"base": "Piper", **fields}),
                      tmp_path)


@needs_corpus
def test_clone_is_the_base_bytes_under_a_new_name_with_its_own_cache(tmp_path):
    gen, cache = _emit(tmp_path)
    assert gen.name == "Zz_Piper_Clone.herodef.ot.DtHeroDefinition.gen"
    assert gen.read_bytes() == EP.corpus_read(
        "Definitions/Heroes/Piper.herodef.ot.DtHeroDefinition.gen")
    lines = RC.parse(cache.read_bytes())
    assert lines == sorted(lines)
    assert "Definitions|Heroes\\Zz_Piper_Clone.herodef.ot|oCDtHeroDefinition" in lines
    assert not any("Heroes\\Piper.herodef.ot" in ln for ln in lines)


@needs_corpus
@pytest.mark.parametrize("fields,msg", [
    ({"base": "Carmilla"}, "paid DLC"),
    ({"base": "Merlin"}, "paid DLC"),
    ({"base": "Nobody"}, "no shipped hero"),
    ({"display_name": "X"}, "unsupported field"),
])
def test_bad_clones_are_refused(tmp_path, fields, msg):
    with pytest.raises(ContentError, match=msg):
        _emit(tmp_path, **fields)


@needs_corpus
def test_a_shipped_id_is_refused(tmp_path):
    with pytest.raises(ContentError, match="collides"):
        _emit(tmp_path, id="Juliet")


@needs_corpus
def test_apply_appends_a_new_hero_to_the_versiondef_hero_vector():
    """A herodef registered only in UsedRscList never loads (12 live in game,
    2026-09-24): heroes load through the versiondef's hero vector."""
    from rsmm.cli import apply_mods as A
    from rsmm.engine import cooked

    rel = "Heroes\\Zz_Piper_Clone.herodef.ot"
    assert A._hero_versiondef_path(
        "Definitions/Heroes/Zz_Piper_Clone.herodef.ot.DtHeroDefinition.gen") == rel
    assert A._hero_versiondef_path("Definitions/Heroes/Piper.herodef.UsedRscCache.ot") is None
    vd = EP.corpus_read("Definitions/Versions/LiveOps5.versiondef.ot.rsionDefinition.gen")
    co, _, cnt = A._find_hero_vector(vd)
    assert cnt == 12
    out = A._patch_versiondef_heroes(vd, [rel])
    co2, _, cnt2 = A._find_hero_vector(out)
    entries = [e[2] for e in A._mo_vector_entries(out, co2, cnt2)]
    assert cnt2 == 13 and entries[-1] == rel and entries[:12] == [
        e[2] for e in A._mo_vector_entries(vd, co, cnt)]
    assert A._patch_versiondef_heroes(out, [rel]) == out      # idempotent
    cooked.parse(out)
