"""The entity-graph reader: components, their identities and their links.

The ability editor rewires these graphs, so the reader has to agree with the
engine about what a component is (its own GUID) and what it points at (a
picker's target GUID)."""

from __future__ import annotations

import pytest

from rsmm.engine import corpus
from rsmm.engine import entity_graph as EG
from rsmm.engine import prop_cook as PC

PIPER = "EntitySettings/Heroes/Hero_Piper/Hero_Piper.entity.ot.EntitySettingsResource.gen"
needs = pytest.mark.skipif(corpus.read(PIPER) is None, reason="no hero corpus")


@needs
def test_every_component_parses_with_the_identity_the_engine_uses():
    raw = corpus.read(PIPER)
    g = EG.parse(raw, "Hero_Piper")
    assert len(g.components) > 700
    assert {c.guid for c in g.components} == set(PC.component_guids(raw))


@needs
def test_a_picker_points_at_its_target_by_the_targets_own_guid():
    g = EG.parse(corpus.read(PIPER), "Hero_Piper")
    index = g.by_guid()
    op = next(c for c in g.components if c.name == "Primary Ability Shoot Delay Operation")
    ref = next(r for r in op.refs if r.path.endswith("\\Primary Ability Shots Delay"))
    assert index[ref.guid].name == "Primary Ability Shots Delay"
    assert ref.kind == "Value" and ref.scope == "Hero_Piper"


@needs
def test_an_abilitys_closure_reaches_its_talents():
    g = EG.parse(corpus.read(PIPER), "Hero_Piper")
    got = {c.group for c in g.closure(g.groups()["Ability Secondary"])}
    assert "Ability Secondary" in got and any(x.startswith("Skill") for x in got)
