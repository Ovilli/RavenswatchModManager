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


@needs
def test_a_component_body_reads_as_typed_tokens():
    g = EG.parse(corpus.read(PIPER), "Hero_Piper")
    delay = next(c for c in g.components if c.name == "Primary Ability Shots Delay")
    assert [t.text for t in EG.tokens(delay) if t.kind == "value"] == ["f32 0.05"]
    timer = next(c for c in g.components if c.name == "Ability Secondary Active Timer")
    toks = EG.tokens(timer)
    assert "bool False" in [t.text for t in toks]          # a bool is ONE byte
    assert any(t.kind == "ref" and t.text.endswith("Duration Selector") for t in toks)
    # Tokens tile the body exactly: an edit can address any of them by offset.
    assert sum(t.size for t in toks) == len(timer.body)


def _rel(name: str) -> str | None:
    return next((r for r in corpus.rels("EntitySettings/")
                 if r.endswith(f"/{name}.entity.ot.EntitySettingsResource.gen")), None)


@needs
@pytest.mark.parametrize("name", ["Hero_Piper", "Mordred_Quest_Manager"])
def test_the_reader_finds_every_component_the_engine_instantiates(name):
    """The file's component vector is what the engine instantiates. Override
    records often have an EMPTY group, which a string scan cannot see; reading
    the header by position is what makes these counts agree."""
    from rsmm.engine import cooked
    from rsmm.engine.entity_append import component_vector
    raw = corpus.read(_rel(name))
    _off, ids = component_vector(cooked.parse(raw).sections[-1].payload)
    g = EG.parse(raw, name)
    assert len(g.components) == len(ids)
    if name == "Mordred_Quest_Manager":
        despawn = next(c for c in g.components if c.name == "Despawn Timer")
        assert despawn.group == ""


@needs
def test_named_fields_cover_the_body_and_read_as_the_timer_it_is():
    from rsmm.engine import entity_fields as EF
    g = EG.parse(corpus.read(PIPER), "Hero_Piper")
    timer = next(c for c in g.components if c.name == "Primary Ability Shoot Timer")
    fs = {f.name: f for f in EF.fields(timer)}
    assert fs["duration"].text.endswith("Primary Ability Shots Delay")
    assert fs["on_tick"].text.endswith("Event Primary Ability Shoot")
    assert fs["state"].text.endswith("State Primary Ability")
    state = next(c for c in g.components if c.name == "State Secondary Ability")
    lists = {f.name: f for f in EF.fields(state) if f.kind == "ref[]"}
    assert len(lists) == 7 and lists["while_active"].items
    for c in g.components:
        got = EF.fields(c)
        assert sum(f.size for f in got) == len(c.body)
        assert all(a.offset + a.size == b.offset for a, b in zip(got, got[1:], strict=False))


@pytest.mark.slow
@needs
def test_every_schema_fits_every_shipped_component_of_its_class():
    """A schema is only a name table if it matches ALL shipped instances. One
    that fits most of them is a guess about the rest, and the editor would
    write fields where the engine reads something else."""
    from rsmm.engine import entity_fields as EF
    misses: dict[str, int] = {}
    for rel in corpus.rels("EntitySettings/"):
        if not rel.endswith(".EntitySettingsResource.gen"):
            continue
        for c in EG.parse(corpus.read(rel)).components:
            if c.cls in EF.SCHEMAS:
                spec = EF.BASE + EF.SCHEMAS[c.cls]
                if EF._apply(c, EF._items(c), spec) is None:
                    misses[c.cls] = misses.get(c.cls, 0) + 1
            for t in EG.tokens(c):                 # every value union ends on its END
                if t.kind == "value":
                    assert c.body[t.offset + t.size - 4:t.offset + t.size] == EG._END
    assert misses == {}
