"""`kind = "entity"`: graph steps written over ONE shipped entity file, in place."""

from __future__ import annotations

import pytest

from rsmm.engine import corpus
from rsmm.engine import entity_fields as EF
from rsmm.engine import entity_graph as EG
from rsmm.sdk.content import ContentDef, ContentError, ContentRegistry
from rsmm.sdk.kinds import entities

_ENTITY = "Objects/Map_Boss_Spawner/Map_Boss_Spawner_Graph_Model"
_REL = f"EntitySettings/{_ENTITY}.entity.ot.EntitySettingsResource.gen"

needs_corpus = pytest.mark.skipif(corpus.read(_REL) is None, reason="no entity corpus")


def _emit(tmp_path, *steps, id="Tint", entity=_ENTITY):
    return entities.emit("m", ContentDef(
        kind="entity", id=id, fields={"entity": entity, "steps": list(steps)}), tmp_path)


def _links(blob, part, field):
    g = EG.parse(blob, "x")
    c = next(x for x in g.components if x.name == part)
    return next(f for f in EF.fields(c) if f.name == field).text


@needs_corpus
def test_the_edit_lands_at_the_vanilla_path_and_the_original_is_untouched(tmp_path):
    written = _emit(tmp_path, {"remove_link": "State FX PreOvertime.while_active[1]"})
    assert [p.relative_to(tmp_path).as_posix() for p in written] == [_REL]
    new = _links(written[0].read_bytes(), "State FX PreOvertime", "while_active")
    old = _links(corpus.read(_REL), "State FX PreOvertime", "while_active")
    assert "Pre Overtime WARNING Render Settings" in old
    assert "Pre Overtime WARNING Render Settings" not in new
    assert "Pre Overtime Warning Curve" in new          # its neighbour stays


@needs_corpus
@pytest.mark.parametrize("entity", [
    _ENTITY, _ENTITY + ".entity.ot", _ENTITY.replace("/", "\\"),
    "EntitySettings/" + _ENTITY,
])
def test_the_path_is_accepted_in_every_spelling(tmp_path, entity):
    written = _emit(tmp_path, {"remove_link": "Event FX Overtime Warning.activates[0]"},
                    entity=entity)
    assert [p.relative_to(tmp_path).as_posix() for p in written] == [_REL]


@needs_corpus
def test_two_blocks_editing_one_file_both_land(tmp_path):
    _emit(tmp_path, {"remove_link": "State FX PreOvertime.while_active[1]"}, id="A")
    written = _emit(tmp_path, {"remove_link": "Event FX Overtime Warning.activates[0]"}, id="B")
    blob = written[0].read_bytes()
    assert "WARNING Render Settings" not in _links(blob, "State FX PreOvertime", "while_active")
    assert "Cinematic" not in _links(blob, "Event FX Overtime Warning", "activates")


@needs_corpus
def test_a_packed_mods_shipped_output_is_rebuilt_not_edited_again(tmp_path):
    """A packed mod ships its emitted file without .rsmm_emitted.json, so the
    player's apply finds last build's output on disk. Re-running the steps over
    it cut while_active[2] from a two-element list (IndexError, 2026-10-09)."""
    steps = [{"remove_link": "State FX PreOvertime.while_active[1]"},
             {"remove_link": "Event FX Overtime Warning.activates[0]"},
             {"remove_link": "State FX Overtime.while_active[2]"}]

    def registry_emit():
        cr = ContentRegistry(mod_id="m")
        cr.register("entity", id="Tint", entity=_ENTITY, steps=steps)
        return cr.emit(tmp_path)

    first = registry_emit()[0].read_bytes()
    again = registry_emit()                     # the shipped file is still there
    assert again[0].read_bytes() == first


def test_an_out_of_range_link_names_the_list(tmp_path):
    from rsmm.engine.ability_edit import AbilityEditError, apply
    if corpus.read(_REL) is None:
        pytest.skip("no entity corpus")
    with pytest.raises(AbilityEditError, match=r"while_active\[9\].*element"):
        apply({"x": corpus.read(_REL)},
              [{"remove_link": "State FX Overtime.while_active[9]"}], main="x", seed="s")


@pytest.mark.parametrize("fields,msg", [
    ({"steps": [{"remove_link": "A.b[0]"}]}, "needs 'entity'"),
    ({"entity": _ENTITY, "steps": "oops"}, "needs 'steps'"),
    ({"entity": _ENTITY, "steps": [{"clone": "X", "as": "Y"}]}, "clone steps"),
    ({"entity": "Objects/Nope/Nothing_Here", "steps": [{"remove_link": "A.b[0]"}]},
     "no shipped entity"),
])
def test_bad_blocks_are_refused_with_the_reason(tmp_path, fields, msg):
    with pytest.raises(ContentError, match=msg):
        entities.emit("m", ContentDef(kind="entity", id="Bad", fields=fields), tmp_path)
