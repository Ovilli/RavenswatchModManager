"""Graph edits on an entity file: the ability editor's primitives.

Every test works on Piper, whose file has 787 components and 468 owned
sub-objects: the case where a copy that forgot its sub-objects, or remapped a
number that was not a pointer, would load and misbehave silently."""

from __future__ import annotations

import pytest

from rsmm.engine import corpus
from rsmm.engine import entity_fields as EF
from rsmm.engine import entity_graph_edit as EE

PIPER = "EntitySettings/Heroes/Hero_Piper/Hero_Piper.entity.ot.EntitySettingsResource.gen"
JULIET = "EntitySettings/Heroes/Hero_Juliet/Hero_Juliet.entity.ot.EntitySettingsResource.gen"
needs = pytest.mark.skipif(corpus.read(PIPER) is None, reason="no hero corpus")


def _piper() -> EE.EntityFile:
    return EE.EntityFile(corpus.read(PIPER), "Hero_Piper")


def _field(ef: EE.EntityFile, comp: str, name: str) -> EF.Field:
    return next(f for f in EF.fields(ef.component(comp)) if f.name == name)


@needs
def test_an_unedited_file_writes_back_byte_identical():
    raw = corpus.read(PIPER)
    assert EE.EntityFile(raw).to_bytes() == raw


@needs
def test_every_sub_object_in_piper_has_one_known_owner():
    owned, ambiguous = _piper().pointers()
    assert len(owned) == 468 and ambiguous == {}


@needs
def test_a_cloned_ability_links_to_its_copies_and_owns_its_own_sub_objects():
    ef = _piper()
    n0 = len(ef.objects)
    names = [c.name for c in ef.graph().groups()["Ability Secondary"]]
    ef.clone(names, rename={n: n + " B" for n in names},
             group={"Ability Secondary": "Ability Secondary B"}, seed="t")
    g = ef.graph()
    idx = g.by_guid()
    new = [c for c in g.components if c.group == "Ability Secondary B"]
    assert len(new) == len(names)
    targets = [idx[r.guid].group for c in new for r in c.refs if r.guid in idx]
    assert "Ability Secondary B" in targets and "Ability Secondary" not in targets
    for c in new:                                    # paths name the copies too
        for r in c.refs:
            if r.guid in idx and idx[r.guid].group == "Ability Secondary B":
                assert "\\Ability Secondary B\\" in r.path and r.path.endswith(" B")
    owned, ambiguous = ef.pointers()
    copied = [x for x in owned if x >= n0]
    assert copied and all(owned[x].owner >= n0 for x in copied)
    assert not [x for x in owned if x < n0 and owned[x].owner >= n0]
    assert ambiguous == {}
    # The copy can itself be copied: nothing about it is special.
    again = [c.name for c in new]
    ef.clone(again, rename={n: n + "2" for n in again},
             group={"Ability Secondary B": "Ability Secondary C"}, seed="t2")
    assert len(ef.graph().groups()["Ability Secondary C"]) == len(names)


@needs
def test_literals_and_references_are_edited_by_field_name():
    ef = _piper()
    ef.set_value("Primary Ability Shots Delay", "value", 0.2)
    assert _field(ef, "Primary Ability Shots Delay", "value").text == "f32 0.2"
    ef.set_ref("Primary Ability Shoot Timer", "on_end", "State Secondary Ability")
    assert _field(ef, "Primary Ability Shoot Timer", "on_end").text.endswith(
        "\\Ability Secondary\\State Secondary Ability")
    ef.add_ref("State Secondary Ability", "activates", "Primary Ability Shoot Timer")
    assert len(_field(ef, "State Secondary Ability", "activates").items) == 1
    ef.remove_ref("State Secondary Ability", "activates", 0)
    assert _field(ef, "State Secondary Ability", "activates").items == []
    ef.set_ref("Primary Ability Shoot Timer", "on_end", None)
    assert _field(ef, "Primary Ability Shoot Timer", "on_end").text == "(none)"


@needs
def test_a_value_repoint_that_would_misread_its_target_is_refused_and_undone():
    """An int count re-pointed at an f32 value would read the float's bits as
    a count (the ~22-rats bug). The edit is refused and the file untouched."""
    raw = corpus.read(PIPER)
    ef = EE.EntityFile(raw, "Hero_Piper")
    with pytest.raises(EE.EntityEditError):
        ef.set_ref("Primary Ability Shoot Timer", "count", "Primary Ability Shots Delay")
    assert ef.to_bytes() == raw


BEOWULF = "EntitySettings/Heroes/Hero_Beowulf/Hero_Beowulf.entity.ot.EntitySettingsResource.gen"


@pytest.mark.skipif(corpus.read(BEOWULF) is None, reason="no Beowulf")
def test_a_scalar_inside_an_object_field_is_set_by_index():
    # A spawner's transform: position (0-2), a vec3, rotation in radians
    # (4-6, yaw = 5), a vec3, scale (8-10). Turning the shockwave sideways is
    # its yaw, and nothing else in the file may move.
    raw = corpus.read(BEOWULF)
    ef = EE.EntityFile(raw, "Hero_Beowulf")
    spawner = "Primary Ability Effect Spawner"
    ef.set_value(spawner, "transform[5]", 1.5707964)
    lits = _field(ef, spawner, "transform").text.split("  ")
    assert lits[5] == "f32 1.5708"
    assert lits[4] == "f32 0" and lits[6] == "f32 0" and lits[8] == "f32 1"
    out = ef.to_bytes()
    assert len(out) == len(raw)
    assert sum(a != b for a, b in zip(out, raw, strict=True)) <= 4   # one f32
    ef = EE.EntityFile(raw, "Hero_Beowulf")
    # The yaw a hero's ability spawn honours is the one in `position`.
    ef.set_value(spawner, "position[8]", -1.5707964)
    pos = _field(ef, spawner, "position").text.split("  ")
    assert pos[8] == "f32 -1.5708" and pos[7] == "f32 0" and pos[9] == "f32 0"
    # A vector inside an object: position's `vec3 0 0 1` (its local forward).
    ef.set_value(spawner, "position[1]", [1, 0, 0])
    assert _field(ef, spawner, "position").text.split("  ")[1] == "vec3 1 0 0"
    with pytest.raises(EE.EntityEditError, match="give 3 numbers"):
        ef.set_value(spawner, "position[1]", 1.0)
    with pytest.raises(EE.EntityEditError, match="no index 11"):
        ef.set_value(spawner, "transform[11]", 1.0)


@needs
def test_a_reference_and_a_string_inside_an_object_field_are_edited_by_index():
    # How a spawn is turned in the shipped data: the spawner reads a 3D node
    # whose Y angle comes from a value (reference 5 inside obj_4), and the
    # spawner's template says what it spawns (string 1).
    ef = _piper()
    node, spawner = "Attack Shoot 3d Node 02", "Attack Shoot Projectile Spawner 02"
    ef.set_ref(node, "obj_4[5]", "Primary Ability Shots Delay")
    assert _field(ef, node, "obj_4").text.endswith("\\Primary Ability Shots Delay")
    shock = "Heroes\\Hero_Beowulf\\Hero_Beowulf_Shockwave.entity.ot"
    ef.set_value(spawner, "template[1]", shock)
    assert repr(shock) in _field(ef, spawner, "template").text
    again = EE.EntityFile(ef.to_bytes(), "Hero_Piper")      # re-framed file parses
    assert repr(shock) in _field(again, spawner, "template").text
    with pytest.raises(EE.EntityEditError, match="no index 9"):
        ef.set_ref(node, "obj_4[9]", "Primary Ability Shots Delay")


@needs
@pytest.mark.skipif(corpus.read(JULIET) is None, reason="no Juliet")
def test_components_copy_across_entities_with_the_classes_they_need():
    ef = _piper()
    jul = EE.EntityFile(corpus.read(JULIET), "Hero_Juliet")
    names = [c.name for c in jul.graph().groups()["Ability Secondary"]]
    before = {c.name for c in ef.cf.classes}
    ef.clone(names, group={"Ability Secondary": "Juliet Secondary"}, seed="j", source=jul)
    assert len(ef.graph().groups()["Juliet Secondary"]) == len(names)
    assert {c.name for c in ef.cf.classes} > before     # e.g. her two-speed animatic


@pytest.mark.slow
@needs
def test_every_shipped_entity_round_trips_through_the_editor():
    for rel in corpus.rels("EntitySettings/"):
        if rel.endswith(".EntitySettingsResource.gen"):
            raw = corpus.read(rel)
            assert EE.EntityFile(raw).to_bytes() == raw, rel
