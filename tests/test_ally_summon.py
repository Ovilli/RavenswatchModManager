"""An enemy summoned as an ally (engine/ally_summon.py): Blood Wolf's wolf."""

from __future__ import annotations

import struct

import pytest

from rsmm.engine import corpus

_TIMBER = "Enemies\\Wolves\\Standard_Wolf_Timber.entity.ot"
needs_corpus = pytest.mark.skipif(
    corpus.read("EntitySettings/Enemies/Wolves/Wolves_Model.entity.ot"
                ".EntitySettingsResource.gen") is None, reason="no enemy corpus")


def _filters(raw: bytes) -> list[tuple[int, tuple, tuple]]:
    """(layer, list A, list B) of every attack filter in ``raw``."""
    from rsmm.engine import cooked
    cf = cooked.parse(raw)
    names = [c.name for c in cf.classes]
    tester = names.index("oCEntityGpnFlagMaskTesterSettings")
    tag = cooked.MARK_BEGIN + struct.pack("<I", names.index("oCGpnFilter"))
    out = []
    for sec in cf.sections:
        p = sec.payload
        if len(p) < 4 or struct.unpack_from("<I", p, 0)[0] != tester:
            continue
        o = p.find(tag) + len(tag)
        layer, n = struct.unpack_from("<II", p, o)
        a = struct.unpack_from(f"<{n}I", p, o + 8)
        m = struct.unpack_from("<I", p, o + 8 + 4 * n)[0]
        out.append((layer, a, struct.unpack_from(f"<{m}I", p, o + 12 + 4 * n)))
    return out


@needs_corpus
def test_a_summoned_wolf_fights_for_the_heroes():
    """Its model layer moves to Ally_Model and every attack filter is
    mirrored: a wolf bite hits ANY[Ally, Neutral]; the copy's hits ANY[Neutral,
    Enemy], the monkey clone's pattern. Identities are its own, under one
    mapping, so the variant still overrides the copied model's parts."""
    from rsmm.engine import ally_summon as AS
    from rsmm.engine import entity_components as EC
    from rsmm.engine import prop_cook as PC
    model, variant = "Heroes\\Hero_Red\\Hero_T_Summon1_Model.entity.ot", \
        "Heroes\\Hero_Red\\Hero_T_Summon1.entity.ot"
    out = AS.build(_TIMBER, model, variant, "t")
    assert EC.parents(out[model]) == [AS.ALLY_MODEL]
    assert EC.parents(out[variant]) == [model]
    filters = _filters(out[model])
    assert filters
    for layer, a, b in filters:
        for lst in (a, b):
            assert len(lst) < 3 or lst[AS.ALLY] in (0, 2), "an attack still targets heroes"
        assert layer != AS.HERO_LAYER
    assert any(len(a) > 2 and a[AS.ENEMY] == 1 for _l, a, _b in filters)
    shipped = corpus.read("EntitySettings/Enemies/Wolves/Wolves_Model.entity.ot"
                          ".EntitySettingsResource.gen")
    assert not set(PC.component_guids(out[model])) & set(PC.component_guids(shipped))


@needs_corpus
def test_a_hero_kit_summon_block_builds(tmp_path):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import heros
    files = heros.emit("m", ContentDef(kind="hero", id="Caller", fields={
        "base": "Red", "kit": {"special": {"steps": [
            {"summon": "Enemies/Wolves/Standard_Wolf_Timber"}]}}}), tmp_path)
    names = {p.name for p in files}
    assert "Hero_Caller_Summon1.entity.ot.EntitySettingsResource.gen" in names
    assert "Hero_Caller_Summon1_Model.entity.ot.EntitySettingsResource.gen" in names


@needs_corpus
def test_a_kit_pets_block_follows_piper_and_takes_the_trait(tmp_path):
    """Pam's Blood Wolf design: one dire wolf on Hero_Pet_Model spawns at start,
    the trait (no cooldown) sends the attack order, leaving combat recalls."""
    from rsmm.engine import ally_summon as AS
    from rsmm.engine import entity_components as EC
    from rsmm.engine import entity_fields as EF
    from rsmm.engine.entity_graph_edit import EntityFile
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import heros
    files = heros.emit("m", ContentDef(kind="hero", id="Packer", fields={
        "base": "Red", "kit": {"pets": {"entity": "Enemies/Wolves/Standard_Wolf_Dire"}}}),
        tmp_path)
    by = {p.name: p for p in files}
    model = by["Hero_Packer_Summon1_Model.entity.ot.EntitySettingsResource.gen"].read_bytes()
    assert EC.parents(model) == [AS.PET_MODEL]
    hero = EntityFile(by["Hero_Packer.entity.ot.EntitySettingsResource.gen"].read_bytes(), "h")

    def refs(part, fld):
        f = next(x for x in EF.fields(hero.component(part)) if x.name == fld)
        return [i.text.strip().rsplit("\\", 1)[-1] for i in f.items]
    assert refs("State Trait Ability", "activates") == ["Kit Pet Attack Order"]
    assert "Kit Pet Spread Pos" in refs("Child Event Initialize", "activates")
    assert "Kit Pet Recall Order" in refs("Child State Is In Combat", "disables_while_active?")
    assert next(f.text for f in EF.fields(hero.component("Trait Ability Controller"))
                if f.name == "value_4") == "f32 0"
