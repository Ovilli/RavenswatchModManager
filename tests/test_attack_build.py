"""Custom attacks: a declared attack becomes a projectile entity of the hero's
own plus the steps that fire it, and those steps pass the ability editor's
checks on the base's real entity (a link into nothing would stop the apply)."""

from __future__ import annotations

import pytest

from rsmm.engine import ability_edit as AE
from rsmm.engine import attack_build as AB
from rsmm.engine import corpus
from rsmm.engine import entity_fields as EF
from rsmm.engine import entity_strings as ES
from rsmm.engine.entity_graph_edit import EntityFile

PIPER = "EntitySettings/Heroes/Hero_Piper/Hero_Piper.entity.ot.EntitySettingsResource.gen"
needs = pytest.mark.skipif(corpus.read(PIPER) is None or corpus.read(AB.TEMPLATE_REL) is None,
                           reason="no hero corpus")

SPEC = {"id": "Crescent", "slot": "special", "model": "m.glb", "albedo": "a.png",
        "speed": 16, "lifetime": 0.9, "beats": [[0, 180], [90, -90]], "delay": 0.4,
        "animation": "cast.glb"}


def _build(spec=SPEC):
    return AB.build(dict(spec), hero="Nyx", base="Piper", base_main=corpus.read(PIPER),
                    mesh=lambda donor, model, tag, what, tr: f"Characters\\X\\{tag}_GEO.fbx",
                    material=lambda donor, maps, tag, what: f"Characters\\X\\M_{tag}.mat.ot")


def _field(ef, comp, name):
    return next(f for f in EF.fields(ef.component(comp)) if f.name == name).text


@needs
def test_the_projectile_is_its_own_entity_on_the_generic_model():
    b = _build()
    assert b.entity_ref == "Heroes\\Hero_Piper\\Hero_Nyx_Crescent.entity.ot"
    strings = {t for _s, _o, t in ES.list_strings(b.entity)}
    assert "Characters\\X\\Nyx_Crescent_GEO.fbx" in strings
    assert "Characters\\X\\M_Nyx_Crescent.mat.ot" in strings
    assert "Projectile_Model\\Hero_Projectile_Model.entity.ot" in strings
    # Nothing of the template's hero stays in play.
    assert not [t for t in strings if "Red" in t and t.endswith((".fbx", ".mat.ot", ".vfx.ot"))]
    ef = EntityFile(b.entity, "Hero_Nyx_Crescent")
    assert _field(ef, "Lifetime Duration", "value") == "f32 0.9"
    assert b.animation == ("Piper_Skill_Secondary_Static_Zone",
                           {"source": "cast.glb", "clip": "cast"})


@needs
def test_its_steps_wire_a_cross_that_passes_the_editors_checks():
    b = _build()
    res = AE.apply({"Hero_Piper": corpus.read(PIPER)}, b.steps, main="Hero_Piper", seed="t")
    ef = EntityFile(res.files["Hero_Piper"], "Hero_Piper")
    angles = {}
    for bi, k in ((0, 0), (0, 1), (1, 0), (1, 1)):
        sp = f"Attack Shoot Projectile Spawner 02 Crescent B{bi} {k}"
        assert b.entity_ref.replace("\\", "\\\\") in _field(ef, sp, "template")
        assert _field(ef, sp, "spawner_values") == "(empty)"
        angles[(bi, k)] = _field(ef, f"Primary Ability Shots Delay Crescent B{bi} {k} Angle",
                                 "value")
    assert angles == {(0, 0): "f32 0", (0, 1): "f32 3.14159",
                      (1, 0): "f32 1.5708", (1, 1): "f32 -1.5708"}
    trigger = _field(ef, "Event Secondary Ability Activate", "activates")
    assert "Spawn Zone Selector" not in trigger                 # the slot is replaced
    assert "Crescent B0 0" in trigger and "Crescent B0 1" in trigger
    assert "Active Timer Crescent B1" in trigger
    beat = _field(ef, "Event Secondary Ability Destroy Zone Crescent B1", "activates")
    assert "Crescent B1 0" in beat and "Crescent B1 1" in beat


@needs
@pytest.mark.parametrize("bad, match", [
    ({"id": "no spaces"}, "letters and digits"),
    ({"slot": "ultimate"}, "give a `slot`"),
    ({"beats": [0, 90]}, "list of angle lists"),
    ({"model": None}, "needs a `model`"),
    ({"colour": "red"}, "unsupported field"),
])
def test_a_bad_attack_is_refused_with_a_reason(bad, match):
    spec = {**SPEC, **bad}
    spec = {k: v for k, v in spec.items() if v is not None}
    with pytest.raises(AB.AttackError, match=match):
        _build(spec)


def test_a_base_without_mapped_parts_is_refused():
    with pytest.raises(AB.AttackError, match="not mapped yet"):
        AB.build(dict(SPEC), hero="X", base="Beowulf", base_main=b"",
                 mesh=None, material=None)
