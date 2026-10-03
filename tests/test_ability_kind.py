"""`kind = "ability"`: ability steps written over a SHIPPED hero's own files."""

from __future__ import annotations

import pytest

from rsmm.engine import corpus
from rsmm.engine import entity_fields as EF
from rsmm.engine import entity_graph as EG
from rsmm.sdk.content import ContentDef, ContentError
from rsmm.sdk.kinds import hero_abilities

_FIREBALL = "Hero_Beowulf_Ultimate_2_Fireball"
_REL = "EntitySettings/Heroes/Hero_Beowulf/{}.entity.ot.EntitySettingsResource.gen"

needs_corpus = pytest.mark.skipif(corpus.read(_REL.format(_FIREBALL)) is None,
                                  reason="no hero corpus")


def _emit(tmp_path, *steps, id="Fireball", hero="Beowulf"):
    return hero_abilities.emit("m", ContentDef(
        kind="ability", id=id, fields={"hero": hero, "abilities": list(steps)}), tmp_path)


def _entries(blob):
    g = EG.parse(blob, "x")
    c = next(x for x in g.components if x.name == "Stagger Power Selector")
    return next(f for f in EF.fields(c) if f.name == "entries").text


@needs_corpus
def test_a_step_is_written_over_the_shipped_heros_own_file(tmp_path):
    """No second hero: the edited file lands at the vanilla path, so `apply`
    installs it as an asset override, as the talent kind's files are."""
    step = {"set": "Stagger Power Selector.entries[0][1]", "value": 25, "entity": _FIREBALL}
    written = _emit(tmp_path, step)
    assert [p.relative_to(tmp_path).as_posix() for p in written] == [_REL.format(_FIREBALL)]
    assert "f32 25" in _entries(written[0].read_bytes())
    assert "f32 50" in _entries(corpus.read(_REL.format(_FIREBALL)))      # the original


@needs_corpus
def test_two_blocks_editing_one_file_both_land(tmp_path):
    a = {"set": "Stagger Power Selector.entries[0][1]", "value": 25, "entity": _FIREBALL}
    b = {"set": "Stun Duration Selector.entries[0][1]", "value": 2, "entity": _FIREBALL}
    _emit(tmp_path, a, id="A")
    written = _emit(tmp_path, b, id="B")
    g = EG.parse(written[0].read_bytes(), "x")
    names = ("Stagger Power Selector", "Stun Duration Selector")
    texts = {c.name: next(f.text for f in EF.fields(c) if f.name == "entries")
             for c in g.components if c.name in names}
    assert "f32 25" in texts["Stagger Power Selector"]
    assert "f32 2" in texts["Stun Duration Selector"]


@needs_corpus
@pytest.mark.parametrize("fields,msg", [
    ({"hero": "Nobody", "abilities": [{"set": "A.value", "value": 1}]}, "no shipped hero"),
    ({"abilities": [{"set": "A.value", "value": 1}]}, "needs a 'hero'"),
    ({"hero": "Beowulf"}, "needs 'abilities'"),
    ({"hero": "Beowulf", "abilities": [{"clone": "Ability Primary", "as": "X"}]},
     "custom hero"),
    ({"hero": "Beowulf", "abilities": [{"set": "No Such Part.value", "value": 1}]},
     "ability step 1"),
])
def test_bad_ability_blocks_are_refused(tmp_path, fields, msg):
    with pytest.raises(ContentError, match=msg):
        hero_abilities.emit("m", ContentDef(kind="ability", id="X", fields=fields), tmp_path)
