"""The pre-apply checks on an edited entity: they judge the EDIT.

The shipped game carries dangling and cross-entity references of its own, so
every check compares the edited file with the one it started from. The two
properties that matter are both tested: the game itself passes, and each kind
of mistake an editor makes is caught."""

from __future__ import annotations

import pytest

from rsmm.engine import corpus
from rsmm.engine import entity_check as CK
from rsmm.engine import entity_graph_edit as EE

PIPER = "EntitySettings/Heroes/Hero_Piper/Hero_Piper.entity.ot.EntitySettingsResource.gen"
JULIET = "EntitySettings/Heroes/Hero_Juliet/Hero_Juliet.entity.ot.EntitySettingsResource.gen"
REF = "Heroes\\Hero_Piper\\Hero_Piper.entity.ot"
needs = pytest.mark.skipif(corpus.read(PIPER) is None or corpus.read(JULIET) is None,
                           reason="no hero corpus")


def _check(ef: EE.EntityFile) -> list[CK.Issue]:
    return CK.check(ef.to_bytes(), corpus.read(PIPER), name="Hero_Piper", cache_ref=REF)


@needs
def test_an_ability_copied_inside_its_own_hero_passes():
    ef = EE.EntityFile(corpus.read(PIPER), "Hero_Piper")
    names = [c.name for c in ef.graph().groups()["Ability Secondary"]]
    ef.clone(names, rename={n: n + " B" for n in names},
             group={"Ability Secondary": "Ability Secondary B"}, seed="t")
    assert _check(ef) == []


@needs
def test_a_copy_from_another_hero_is_held_to_what_this_hero_carries():
    """Juliet's secondary links into Hero_Romeo_Juliet_Common, which Piper does
    not inherit, and names effects Piper's preload caches never list."""
    ef = EE.EntityFile(corpus.read(PIPER), "Hero_Piper")
    jul = EE.EntityFile(corpus.read(JULIET), "Hero_Juliet")
    names = [c.name for c in jul.graph().groups()["Ability Secondary"]]
    ef.clone(names, group={"Ability Secondary": "Juliet Secondary"}, seed="j", source=jul)
    errs = [str(i) for i in CK.errors(_check(ef))]
    assert any("Hero_Romeo_Juliet_Common" in e for e in errs)
    assert any("herodef.UsedRscCache.ot" in e for e in errs)
    # Hero_Common and Character_Common are reachable to Piper (her own
    # secondary binds into them), so links there are not errors.
    assert not any("in Hero_Common," in e or "in Character_Common," in e for e in errs)


@needs
def test_a_link_to_a_component_that_exists_nowhere_is_an_error():
    ef = EE.EntityFile(corpus.read(PIPER), "Hero_Piper")
    c = ef.component("Primary Ability Shoot Timer")
    obj = ef.objects[c.index - 1]
    obj[:] = obj.replace(c.refs[0].guid, b"\x13" * 16, 1)
    assert any("exists nowhere" in i.message for i in CK.errors(_check(ef)))


@needs
def test_a_sub_object_nothing_owns_is_an_error():
    ef = EE.EntityFile(corpus.read(PIPER), "Hero_Piper")
    owned, _ = ef.pointers()
    ef.objects.append(bytearray(ef.objects[min(owned)]))     # a copy nothing points at
    assert any("owned by nothing" in i.message for i in CK.errors(_check(ef)))


def test_bytes_that_are_not_an_entity_are_an_error():
    issues = CK.check(b"not an entity", None)
    assert issues and issues[0].error


@pytest.mark.slow
@needs
def test_the_shipped_game_passes_its_own_checks():
    for rel in corpus.rels("EntitySettings/"):
        if rel.endswith(".EntitySettingsResource.gen"):
            raw = corpus.read(rel)
            assert CK.check(raw, raw) == [], rel


@needs
def test_the_preload_caches_are_found_on_a_players_install(install_only):
    """A player has no mirror, and caches cannot be listed from an install."""
    CK._cache_index.cache_clear()
    try:
        hits = [k for k, v in CK._cache_index().items() if REF in v]
        assert "Definitions/Heroes/Piper.herodef.UsedRscCache.ot" in hits
    finally:
        CK._cache_index.cache_clear()
