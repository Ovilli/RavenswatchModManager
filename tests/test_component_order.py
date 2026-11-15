"""New components go where the game's own files put theirs in the vector.

Every shipped entity keeps each class's components in ONE contiguous run of
its component vector; appending at the end split a class in two.
`entity_append.place_new_components` puts a new component in its class's run;
these tests pin the shipped invariant and that every writer keeps it. (Made
while chasing piper-horde-rats' lost right-stick aim; not proven to be its cause.)
"""

from __future__ import annotations

from itertools import groupby

import pytest

from rsmm.engine import cooked, corpus
from rsmm.engine import talent_add_stat as TA
from rsmm.engine.entity_append import _directory, component_vector

GEN = ".entity.ot.EntitySettingsResource.gen"
PIPER = f"EntitySettings/Heroes/Hero_Piper/Hero_Piper{GEN}"


def split_classes(raw: bytes) -> list[int]:
    """Class indexes whose components are not one contiguous run."""
    cf = cooked.parse(raw)
    _o, ids = component_vector(cf.sections[-1].payload)
    _n, directory = _directory(cf)
    runs = [k for k, _ in groupby(directory[i] for i in ids)]
    return sorted({k for k in runs if runs.count(k) > 1})


@pytest.mark.slow
def test_every_shipped_entity_keeps_each_class_together():
    """2026-10-23: 4,769 of 4,769."""
    rels = corpus.rels("EntitySettings/", ".EntitySettingsResource.gen")
    if not rels:
        pytest.skip("shipped entities not available")
    bad = [r for r in rels if (raw := corpus.read(r)) and split_classes(raw)]
    assert bad == []


def piper() -> bytes:
    raw = corpus.read(PIPER)
    if raw is None:
        pytest.skip("Hero_Piper not available (no mirror or game install)")
    return raw


def test_written_parts_join_their_class_run():
    raw = piper()
    out, _ = TA.add_stat(raw, talent="Attack Move Speed", stat="Attack power",
                         values=0.3, on="damage_taken", seconds=4, cooldown=8)
    assert split_classes(out) == []


def test_cloned_components_join_their_class_run(tmp_path):
    """The talent kind's `clone_nodes` (entity_append) and EntityFile.clone."""
    raw = piper()
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import talents
    files = talents.emit("t", ContentDef("talent", "c", {
        "hero": "Piper", "file": "Hero_Piper.entity",
        "clone_nodes": [{"source": "Skill Attack Ghost Notes Requirement Selector",
                         "name": "Order Test Selector"},
                        {"source": "Skill Attack Ghost Notes", "name": "Order Test State"}],
        "rebuild": ["Attack Move Speed"]}), tmp_path)
    out = next(f for f in files if f.name == f"Hero_Piper{GEN}").read_bytes()
    assert split_classes(out) == []
    # The game's own components keep their places: only new ids moved.
    cf, vf = cooked.parse(out), cooked.parse(raw)
    old = component_vector(vf.sections[-1].payload)[1]
    new = component_vector(cf.sections[-1].payload)[1]
    assert [i for i in new if i < len(vf.sections) - 2] == old


def test_grouping_puts_every_class_in_one_run_and_keeps_every_component():
    """A file built over many writes (a hero from scratch) is regrouped as a
    whole: one run per class, the same components, nothing else changed."""
    from rsmm.engine import cooked, corpus
    from rsmm.engine import entity_append as EA
    from rsmm.engine import entity_graph as EG
    raw = corpus.read("EntitySettings/Heroes/Hero_Geppetto/Hero_Geppetto.entity.ot"
                      ".EntitySettingsResource.gen")
    if raw is None:
        import pytest
        pytest.skip("no hero corpus")
    cf = cooked.parse(raw)
    off, ids = EA.component_vector(cf.sections[-1].payload)
    cf.sections[-1].payload = EA._render_vector(off, cf.sections[-1].payload, ids[::2] + ids[1::2])
    scrambled = cooked.emit(cf)
    assert EA.class_runs_split(scrambled)
    fixed = EA.group_class_runs(scrambled)
    assert EA.class_runs_split(fixed) == []
    assert sorted(EA.component_vector(cooked.parse(fixed).sections[-1].payload)[1]) == sorted(ids)
    guids = {c.guid for c in EG.parse(raw).components}
    assert {c.guid for c in EG.parse(fixed).components} == guids
    assert EA.class_runs_split(raw) == []
