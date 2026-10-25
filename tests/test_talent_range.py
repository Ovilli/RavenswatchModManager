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


def comp(raw: bytes, name: str) -> EG.Component:
    return next(c for c in EG.parse(raw).components if c.name == name)


def test_melusines_power_radius_is_a_multiply(caster):
    # Default radius x (1 + extra): the operator id is the game's multiply.
    assert TR.how_scaled(caster, "Primary Ability Radius Operation") == "multiply"
    assert TR.how_scaled(caster, "Primary Ability Default Radius") == "value"


def test_a_factor_is_one_plus_the_amount_while_owned(mel):
    out, fac = TR.add_factor(mel, talent="Trait Dash", values=[0.2, 0.3, 0.4, 0.5],
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


def test_a_plain_number_becomes_base_times_factor_and_keeps_its_name(mel):
    out, fac = TR.add_factor(mel, talent="Trait Dash", values=0.3, tag="W")
    node = "Secondary Ability Attack Width"
    before = comp(mel, node)
    out = TR.scale_node(out, node=node, factor=fac.name)
    after = comp(out, node)
    assert after.guid == before.guid                          # every reader still finds it
    assert [r.path.rsplit("\\", 1)[-1] for r in after.refs] == [f"{node} Scaled"]
    assert [r.path.rsplit("\\", 1)[-1] for r in comp(out, f"{node} Scaled").refs] == [
        f"{node} Base", fac.name]
    base = next(t for t in EG.tokens(comp(out, f"{node} Base")) if t.kind == "value")
    assert base.text == "f32 3"                               # the old number
    assert EC.check(out, mel, name="Hero_Melusine") == []


def test_a_multiply_gets_the_factor_as_one_more_operand(mel, caster):
    hero, fac = TR.add_factor(mel, talent="Trait Dash", values=0.5, tag="R")
    fg = comp(hero, fac.name)
    out = TR.reader(caster, factor_guid=fg.guid,
                    factor_label=f"[Value] Hero_Melusine\\{fg.group}\\{fg.name}",
                    owner_resource="Heroes\\Hero_Melusine\\Hero_Melusine.entity.ot",
                    name="Owner Factor")
    out = TR.scale_node(out, node="Primary Ability Radius Operation",
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


def test_the_look_can_be_left_alone(tmp_path):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import talents

    entity("Melusine")
    defn = ContentDef(kind="talent", id="b", fields={"hero": "Melusine", "scale": [
        {"talent": "Trait Dash", "node": "Primary Ability Radius Operation",
         "values": 0.5, "visual": False}]})
    paths = {p.name.split(".")[0]: p.read_bytes() for p in talents.emit("t", defn, tmp_path)}
    root = comp(paths["Hero_Melusine_Power_Caster_Model"], "Root Node")
    assert root.refs == comp(entity("Melusine", "Hero_Melusine_Power_Caster_Model"),
                             "Root Node").refs


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
    assert order[0] == get.name           # first: the root node below reads it too
    assert order.index("Root Node") < order.index("Primary Ability Radius Operation")
    # What the caster draws grows with the radius: its root node's ground scale
    # (X, Z) reads the factor, its height (Y) stays 1.
    root = comp(paths["Hero_Melusine_Power_Caster_Model"], "Root Node")
    toks = EG.tokens(root)
    k = next(i for i, t in enumerate(toks)
             if t.kind == "object" and t.text == "oCEntity3dTransformPicker")
    vps = [i for i, t in enumerate(toks[k:], k)
           if t.kind == "object" and t.text == "oCEntityCpntValuePicker"][:11]
    assert [toks[vps[s] + 2].text.rsplit("\\", 1)[-1] for s in (8, 10)] == [get.name] * 2
    assert toks[vps[9] + 1].text.startswith("00")


def test_a_shots_lifetime_is_offered_as_its_range():
    # Snow Queen's ATTACK is a projectile: its range is speed x how long it flies.
    files = [(f.name.split(".")[0], f.read_bytes())
             for f in corpus.files("EntitySettings/Heroes/Hero_Snow_Queen") if f.name.endswith(GEN)]
    if not files:
        pytest.skip("no game data")
    got = {c["node"]: c for c in TR.candidates(files, "Snow_Queen") if c["where"] is None}
    assert got["Basic Attack Lifetime Duration Default"]["ability"] == "ATTACK"
    assert got["Ability Defense Frost Radius Default"]["ability"] == "DEFENSE"   # her spelling


def test_range_modifiers_classification():
    files_mel = [(f.name.split(".")[0], f.read_bytes())
                 for f in corpus.files("EntitySettings/Heroes/Hero_Melusine")
                 if f.name.endswith(GEN)]
    if not files_mel:
        pytest.skip("no game data")
    mods_mel = TR.range_modifiers(files_mel, "Melusine")
    by_name_mel = {(m["ability"], m["name"]): m for m in mods_mel}
    assert ("SPECIAL", "Rectangle attack range") in by_name_mel
    rect_nodes = [n["node"] for n in by_name_mel[("SPECIAL", "Rectangle attack range")]["nodes"]]
    assert "Secondary Ability Attack Max Length" in rect_nodes
    assert "Secondary Ability Attack Min Length" in rect_nodes
    assert "Secondary Ability Attack Width" in rect_nodes
    assert ("POWER", "Circular attack range") in by_name_mel

    files_red = [(f.name.split(".")[0], f.read_bytes())
                 for f in corpus.files("EntitySettings/Heroes/Hero_Red") if f.name.endswith(GEN)]
    mods_red = TR.range_modifiers(files_red, "Red")
    by_name_red = {(m["ability"], m["name"]): m for m in mods_red}
    assert ("ATTACK", "Melee attack range") in by_name_red
    melee_nodes = [n["node"] for n in by_name_red[("ATTACK", "Melee attack range")]["nodes"]]
    assert "Human Basic Attack Default Length" in melee_nodes
    assert "Human Basic Attack Default Width" in melee_nodes
    assert "Wolf Basic Attack Default Radius" in melee_nodes

    files_sq = [(f.name.split(".")[0], f.read_bytes())
                for f in corpus.files("EntitySettings/Heroes/Hero_Snow_Queen")
                if f.name.endswith(GEN)]
    mods_sq = TR.range_modifiers(files_sq, "Snow_Queen")
    by_name_sq = {(m["ability"], m["name"]): m for m in mods_sq}
    assert ("ATTACK", "Ranged attack range") in by_name_sq
    assert ("POWER", "Circular attack range") in by_name_sq


def test_the_talent_kind_scales_multiple_nodes(tmp_path):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import talents

    files_mel = [(f.name.split(".")[0], f.read_bytes())
                 for f in corpus.files("EntitySettings/Heroes/Hero_Melusine")
                 if f.name.endswith(GEN)]
    if not files_mel:
        pytest.skip("no game data")
    defn = ContentDef(kind="talent", id="tidal_wave", fields={"hero": "Melusine", "scale": [
        {"talent": "Special Large Waves", "range_type": "Rectangle attack range",
         "nodes": [
             {"node": "Secondary Ability Attack Max Length", "file": "Hero_Melusine"},
             {"node": "Secondary Ability Attack Min Length", "file": "Hero_Melusine"},
             {"node": "Secondary Ability Attack Width", "file": "Hero_Melusine"},
         ],
         "values": [0.2, 0.25, 0.3, 0.35]}]})
    paths = {p.name.split(".")[0]: p.read_bytes() for p in talents.emit("t", defn, tmp_path)}
    assert "Hero_Melusine" in paths
    raw = paths["Hero_Melusine"]
    fac = comp(raw, "Skill Special Large Waves Range Rectangle attack range Factor")
    assert fac is not None
    # All 3 nodes scaled
    assert comp(raw, "Secondary Ability Attack Max Length Scaled") is not None
    assert comp(raw, "Secondary Ability Attack Min Length Scaled") is not None
    assert comp(raw, "Secondary Ability Attack Width Scaled") is not None



def test_beowulf_melee_range_scale_auto_resolves(tmp_path):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import talents
    if not list(corpus.files("EntitySettings/Heroes/Hero_Beowulf")):
        pytest.skip("no game data")

    defn = ContentDef(kind="talent", id="beowulf_talents_builder",
        fields={"hero": "Beowulf", "scale": [
        {"talent": "Attack Wide", "node": "Melee attack range",
         "values": [0.1, 0.2, 0.3, 0.4]}]})
    paths = {p.name.split(".")[0]: p.read_bytes() for p in talents.emit("b", defn, tmp_path)}
    assert "Hero_Beowulf" in paths
    raw = paths["Hero_Beowulf"]
    assert comp(raw, "Skill Attack Wide Range Melee attack range Factor") is not None
    assert comp(raw, "Basic Attack Length Scaled") is not None
    assert comp(raw, "Basic Attack Width Scaled") is not None


def test_snow_queen_power_and_defense_range_scaling(tmp_path):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import talents

    files_sq = [(f.name.split(".")[0], f.read_bytes())
                for f in corpus.files("EntitySettings/Heroes/Hero_Snow_Queen")
                if f.name.endswith(GEN)]
    if not files_sq:
        pytest.skip("no game data")

    # 1. Power Hold (Frost Surge) auto-infers ability POWER and scales cleanly
    # without double scaling
    defn_pwr = ContentDef(kind="talent", id="sq_pwr", fields={"hero": "Snow_Queen", "scale": [
        {"talent": "Power Hold", "node": "Circular attack range", "values": [0.1, 0.2, 0.3, 0.4]}
    ]})
    paths_pwr = {p.name.split(".")[0]: p.read_bytes()
                 for p in talents.emit("p", defn_pwr, tmp_path)}
    raw_pwr = paths_pwr["Hero_Snow_Queen"]
    pwr_op = comp(raw_pwr, "Ability Primary Radius Operation")
    refs_pwr = [t.text for t in EG.tokens(pwr_op) if t.kind == "ref"]
    assert any("Skill Power Hold Range Circular attack range Factor" in r for r in refs_pwr)
    assert not any(c.name == "Ability Primary Radius Scaled" for c in EG.parse(raw_pwr).components)

    # 2. Defense Vulnerable scales Ability Defense Frost Radius Operation AND Defense Traverser
    defn_def = ContentDef(kind="talent", id="sq_def", fields={"hero": "Snow_Queen", "scale": [
        {"talent": "Defense Vulnerable", "node": "Circular attack range",
         "values": [0.1, 0.2, 0.3, 0.4]}
    ]})
    paths_def = {p.name.split(".")[0]: p.read_bytes()
                 for p in talents.emit("d", defn_def, tmp_path)}
    raw_def = paths_def["Hero_Snow_Queen"]
    def_op = comp(raw_def, "Ability Defense Frost Radius Operation")
    refs_def = [t.text for t in EG.tokens(def_op) if t.kind == "ref"]
    assert any("Skill Defense Vulnerable Range Circular attack range Factor" in r for r in refs_def)
    assert not any(c.name == "Ability Defense Frost Radius Default Scaled"
                   for c in EG.parse(raw_def).components)
    # The DEFENSE hits (characters and props) grow from their OWN 0.6, by the
    # same factor: never replaced by the frost's number, which would change the
    # vanilla hitbox before the talent is taken.
    from rsmm.engine.entity_graph_edit import EntityFile
    ef = EntityFile(raw_def)
    for c_name in ("Ability Defense Traverser", "Ability Defense Traverser Props"):
        [(p_around, at, _u)] = list(TR._radius_slots(ef, c_name))
        assert p_around[at] == 1                                  # sourced now
        assert f"{c_name} Radius Scaled".encode() in p_around
        base = comp(raw_def, f"{c_name} Radius Base")
        from rsmm.engine import entity_parts as P
        value = struct.unpack("<f", P.decode(base)["value"].value)[0]
        assert value == pytest.approx(0.6)
    # A traverser that already follows a node is left alone.
    assert b"Abililty Primary Traverser Radius Scaled" not in raw_def


def test_a_talent_names_its_ability_by_its_first_word():
    assert TR.talent_ability("Dash Attack") == "DASH"         # not ATTACK
    assert TR.talent_ability("Basic Big Shots") == "ATTACK"
    assert TR.talent_ability("Secondary Chill") == "SPECIAL"
    assert TR.talent_ability("Passive Enchantment Damage") is None


def test_a_spawned_entity_takes_the_ability_that_spawns_it():
    files = [(f.name.split(".")[0], f.read_bytes())
             for f in corpus.files("EntitySettings/Heroes/Hero_Geppetto") if f.name.endswith(GEN)]
    if not files:
        pytest.skip("no game data")
    got = TR._spawned_abilities(files, "Hero_Geppetto")
    assert got["Hero_Geppetto_Cogsbomb"] == "SPECIAL"       # Secondary Abillity Spawner
    assert got["Hero_Geppetto_Dummy"] == "TRAIT"            # Trait Ability Dummy Spawner


def test_a_range_the_ability_lacks_is_refused_not_borrowed(tmp_path):
    from rsmm.sdk.content import ContentDef, ContentError
    from rsmm.sdk.kinds import talents
    if not list(corpus.files("EntitySettings/Heroes/Hero_Beowulf")):
        pytest.skip("no game data")
    # Beowulf's ATTACK has no projectile; his POWER does. The old fallback
    # scaled POWER's range for an ATTACK talent.
    defn = ContentDef(kind="talent", id="b", fields={"hero": "Beowulf", "scale": [
        {"talent": "Attack Wide", "node": "Ranged attack range",
         "values": [0.1, 0.2, 0.3, 0.4]}]})
    with pytest.raises(ContentError, match="no Ranged attack range for ATTACK"):
        talents.emit("b", defn, tmp_path)


def test_snow_queen_special_cone_range_scaling(tmp_path):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import talents

    files_sq = [(f.name.split(".")[0], f.read_bytes())
                for f in corpus.files("EntitySettings/Heroes/Hero_Snow_Queen")
                if f.name.endswith(GEN)]
    if not files_sq:
        pytest.skip("no game data")

    mods = TR.range_modifiers(files_sq, "Snow_Queen")
    spec = next((m for m in mods if m["ability"] == "SPECIAL"), None)
    assert spec is not None
    assert spec["name"] == "Circular attack range"

    defn = ContentDef(kind="talent", id="sq_spec", fields={"hero": "Snow_Queen", "scale": [
        {"talent": "Special Double", "node": "Circular attack range", "ability": "SPECIAL",
         "values": [0.1, 0.2, 0.3, 0.4]}
    ]})
    paths = {p.name.split(".")[0]: p.read_bytes() for p in talents.emit("s", defn, tmp_path)}
    raw = paths["Hero_Snow_Queen"]
    assert comp(raw, "Ability Secondary Attack Length Scaled") is not None
    assert comp(raw, "Ability Secondary Attack Extra Length Scaled") is not None
