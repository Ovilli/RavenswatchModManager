"""Growing an ability's number from a talent (`rsmm.engine.talent_range`).

Skips when the game data is not on disk."""

from __future__ import annotations

import struct

import pytest

from rsmm.engine import corpus
from rsmm.engine import entity_check as EC
from rsmm.engine import entity_graph as EG
from rsmm.engine import talent_range as TR
from rsmm.engine import talent_values as TV

GEN = ".entity.ot.EntitySettingsResource.gen"


def entity(hero: str, stem: str | None = None) -> bytes:
    stem = stem or f"Hero_{hero}"
    for f in corpus.files(f"EntitySettings/Heroes/Hero_{hero}"):
        if f.name == stem + GEN:
            return f.read_bytes()
    pytest.skip(f"{stem} not available (no mirror or game install)")


@pytest.fixture(scope="module")
def mel() -> bytes:
    return entity("Melusine")


@pytest.fixture(scope="module")
def caster() -> bytes:
    return entity("Melusine", "Hero_Melusine_Power_Caster_Model")


@pytest.fixture(scope="module")
def donors() -> tuple[bytes, bytes]:
    return entity("Aladdin"), entity("Carmilla")


def comp(raw: bytes, name: str) -> EG.Component:
    return next(c for c in EG.parse(raw).components if c.name == name)


def test_melusines_power_radius_is_a_multiply(caster):
    # Default radius x (1 + extra): the operator id is the game's multiply.
    assert TR.how_scaled(caster, "Primary Ability Radius Operation") == "multiply"
    assert TR.how_scaled(caster, "Primary Ability Default Radius") == "value"


def test_a_factor_is_one_plus_the_amount_while_owned(mel, donors):
    aladdin, _carmilla = donors
    out, fac = TR.add_factor(mel, aladdin, mel, talent="Trait Dash", values=[0.2, 0.3, 0.4, 0.5],
                             tag="T")
    tiers = {t: round(v[1], 4) for t, v in TV.tier_values(out, f"{fac.name} Selector").items()}
    assert tiers == {"Common": 1.2, "Rare": 1.3, "Epic": 1.4, "Legendary": 1.5}
    shown = {t: round(v[1], 4) for t, v in TV.tier_values(out, fac.selector).items()}
    assert shown == {"Common": 0.2, "Rare": 0.3, "Epic": 0.4, "Legendary": 0.5}
    cond = comp(out, "Skill Trait Dash Range T Condition Selector")
    assert [r.path.rsplit("\\", 1)[-1] for r in cond.refs] == [
        "Skill Trait Dash", f"{fac.name} Selector"]
    assert [r.path.rsplit("\\", 1)[-1] for r in comp(out, fac.name).refs] == [cond.name]
    assert fac.slot is not None
    assert EC.check(out, mel, name="Hero_Melusine") == []


def test_a_plain_number_becomes_base_times_factor_and_keeps_its_name(mel, donors):
    aladdin, carmilla = donors
    out, fac = TR.add_factor(mel, aladdin, mel, talent="Trait Dash", values=0.3, tag="W")
    node = "Secondary Ability Attack Width"
    before = comp(mel, node)
    out = TR.scale_node(out, carmilla, node=node, factor=fac.name)
    after = comp(out, node)
    assert after.guid == before.guid                          # every reader still finds it
    assert [r.path.rsplit("\\", 1)[-1] for r in after.refs] == [f"{node} Scaled"]
    assert [r.path.rsplit("\\", 1)[-1] for r in comp(out, f"{node} Scaled").refs] == [
        f"{node} Base", fac.name]
    base = next(t for t in EG.tokens(comp(out, f"{node} Base")) if t.kind == "value")
    assert base.text == "f32 3"                               # the old number
    assert EC.check(out, mel, name="Hero_Melusine") == []


def test_a_multiply_gets_the_factor_as_one_more_operand(mel, caster, donors):
    aladdin, carmilla = donors
    hero, fac = TR.add_factor(mel, aladdin, mel, talent="Trait Dash", values=0.5, tag="R")
    fg = comp(hero, fac.name)
    out = TR.reader(caster, caster, factor_guid=fg.guid,
                    factor_label=f"[Value] Hero_Melusine\\{fg.group}\\{fg.name}",
                    owner_resource="Heroes\\Hero_Melusine\\Hero_Melusine.entity.ot",
                    name="Owner Factor")
    out = TR.scale_node(out, carmilla, node="Primary Ability Radius Operation",
                        factor="Owner Factor")
    op = comp(out, "Primary Ability Radius Operation")
    assert op.refs[-1].path == "[Entity Get Value] Hero_Melusine_Power_Caster_Model\\Owner Factor"
    get = comp(out, "Owner Factor")
    assert [r.guid for r in get.refs] == [fg.guid]            # reads the factor in the hero file
    toks = EG.tokens(op)
    node = next(i for i, t in enumerate(toks) if t.kind == "object"
                and t.text == "oCEntityCpntNodeSettings")
    assert struct.unpack("<II", bytes.fromhex(toks[node + 1].text.replace(" ", ""))[:8]) == (
        0x17B29BE2, 3)                                         # still a multiply, now of 3


def test_other_operations_and_non_numbers_are_refused(caster):
    with pytest.raises(TR.RangeError, match="not a number|decimal"):
        TR.how_scaled(caster, "Skill Power Chill Modifier")


def test_candidates_name_the_ability_and_keep_to_entities_that_read_the_hero():
    files = [(f.name.split(".")[0], f.read_bytes())
             for f in corpus.files("EntitySettings/Heroes/Hero_Melusine") if f.name.endswith(GEN)]
    if not files:
        pytest.skip("no game data")
    got = {(c["file"], c["node"]): c for c in TR.candidates(files, "Melusine")}
    assert got[("Hero_Melusine", "Secondary Ability Attack Width")]["ability"] == "SPECIAL"
    radius = got[("Hero_Melusine_Power_Caster_Model", "Primary Ability Radius Operation")]
    assert (radius["ability"], radius["where"]) == ("POWER", "Power_Caster_Model")
    assert ("Hero_Melusine_Power_Caster_Model", "Primary Ability Radius Operation") in got
    owner = "Heroes\\Hero_Melusine\\Hero_Melusine.entity.ot"
    assert all(c["file"] == "Hero_Melusine" or TR.reads_owner(dict(files)[c["file"]], owner)
               for c in got.values())


def test_the_talent_kind_scales_across_files(tmp_path):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import talents

    entity("Melusine")
    defn = ContentDef(kind="talent", id="bigger", fields={"hero": "Melusine", "scale": [
        {"talent": "Trait Dash", "node": "Primary Ability Radius Operation",
         "values": [0.2, 0.3, 0.4, 0.5]}]})
    paths = {p.name.split(".")[0]: p.read_bytes() for p in talents.emit("t", defn, tmp_path)}
    assert set(paths) == {"Hero_Melusine", "Hero_Melusine_Power_Caster_Model"}
    fac = comp(paths["Hero_Melusine"],
               "Skill Trait Dash Range Primary Ability Radius Operation Factor")
    get = comp(paths["Hero_Melusine_Power_Caster_Model"], f"Owner {fac.name}")
    assert [r.guid for r in get.refs] == [fac.guid]
    # A spawned entity's nodes run only once its start-up state switches them on,
    # in order: the reader must be switched on just before the radius it feeds
    # (playtest 2026-10-09: without it the radius did not change).
    init = comp(paths["Hero_Melusine_Power_Caster_Model"], "Event Initialize Power Caster")
    from rsmm.engine import entity_fields as EF
    order = [i.text.rsplit("\\", 1)[-1] for i in next(
        f for f in EF.fields(init) if f.name == "activates").items]
    k = order.index("Primary Ability Radius Operation")
    assert order[k - 1] == get.name
