"""Giving a talent a stat it does not have (`rsmm.engine.talent_add_stat`).

The recipe was proven in game on 2026-10-05 (Fiery Dragon also reducing TRAIT
cooldown); these tests pin the general form against the shipped hero files and
skip when the game data is not on disk.
"""

from __future__ import annotations

import struct

import pytest

from rsmm.engine import corpus
from rsmm.engine import entity_append as EA
from rsmm.engine import entity_check as EC
from rsmm.engine import entity_graph as EG
from rsmm.engine import talent_add_stat as TA
from rsmm.engine import talent_values as TV

GEN = ".entity.ot.EntitySettingsResource.gen"


def hero_file(hero: str) -> bytes:
    for f in corpus.files(f"EntitySettings/Heroes/Hero_{hero}"):
        if f.name == f"Hero_{hero}{GEN}":
            return f.read_bytes()
    pytest.skip(f"Hero_{hero} entity not available (no mirror or game install)")


@pytest.fixture(scope="module")
def wukong() -> bytes:
    return hero_file("SunWukong")


@pytest.fixture(scope="module")
def beowulf() -> bytes:
    return hero_file("Beowulf")


def comp(raw: bytes, name: str, cls_suffix: str = "") -> EG.Component:
    return next(c for c in EG.parse(raw).components
                if c.name == name and c.cls.endswith(cls_suffix))


def test_fiery_dragon_gets_trait_cooldown(wukong, beowulf):
    out, added = TA.add_stat(wukong, beowulf, talent="Trait Fire", stat="CD reduce trait",
                             values=[0.10, 0.15, 0.20, 0.25])

    state = comp(out, "Skill Trait Fire", "StateSettings")
    assert [r.path.rsplit("\\", 1)[-1] for r in state.refs] == [added.modifier]

    modifier = comp(out, added.modifier)
    assert [r.path.rsplit("\\", 1)[-1] for r in modifier.refs] == [added.selector]
    assert EA.modifier_stat(out, added.modifier) == TA.stat_key_bytes("CD reduce trait")

    tiers = {t: round(v[1], 4) for t, v in TV.tier_values(out, added.selector).items()}
    assert tiers == {"Common": 0.10, "Rare": 0.15, "Epic": 0.20, "Legendary": 0.25}

    card = comp(out, "Skill String Desc Trait Fire")
    assert added.slot == 1
    assert card.refs[-1].path.endswith(added.selector)

    assert EC.check(out, wukong, name="Hero_SunWukong") == []


def test_a_talent_that_already_runs_modifiers_keeps_them(beowulf):
    before = comp(beowulf, "Skill Attack Fire Cone", "StateSettings")
    assert before.refs, "fixture: this talent's state must already have children"

    out, added = TA.add_stat(beowulf, beowulf, talent="Attack Fire Cone",
                             stat="Attack power trait", values=0.1)

    after = comp(out, "Skill Attack Fire Cone", "StateSettings")
    assert [r.guid for r in after.refs[:-1]] == [r.guid for r in before.refs]
    assert after.refs[-1].path.endswith(added.modifier)
    assert EC.check(out, beowulf, name="Hero_Beowulf") == []


def test_ultimates_are_refused_with_a_reason(wukong, beowulf):
    graph = EG.parse(wukong)
    ultimate = next(c.name[len("Skill Controller "):] for c in graph.components
                    if c.name.startswith("Skill Controller Ultimate"))
    with pytest.raises(TA.AddStatError, match="no state|no per-rarity"):
        TA.add_stat(wukong, beowulf, talent=ultimate, stat="CD reduce trait", values=0.1)


def test_unknown_talent_and_stat_are_refused(wukong, beowulf):
    with pytest.raises(TA.AddStatError, match="no talent"):
        TA.add_stat(wukong, beowulf, talent="No Such Talent", stat="CD reduce trait", values=0.1)
    with pytest.raises(TA.AddStatError):
        TA.add_stat(wukong, beowulf, talent="Trait Fire", stat="not a stat at all", values=0.1)


def test_the_same_stat_twice_is_refused(wukong, beowulf):
    out, _ = TA.add_stat(wukong, beowulf, talent="Trait Fire", stat="CD reduce trait", values=0.1)
    with pytest.raises(TA.AddStatError, match="already"):
        TA.add_stat(out, beowulf, talent="Trait Fire", stat="CD reduce trait", values=0.2)


def test_two_different_stats_stack(wukong, beowulf):
    out, a = TA.add_stat(wukong, beowulf, talent="Trait Fire", stat="CD reduce trait", values=0.1)
    out, b = TA.add_stat(out, beowulf, talent="Trait Fire", stat="Crit damage", values=0.2)
    assert (a.slot, b.slot) == (1, 2)
    state = comp(out, "Skill Trait Fire", "StateSettings")
    assert len(state.refs) == 2
    assert EC.check(out, wukong, name="Hero_SunWukong") == []


@pytest.mark.parametrize("values, want", [
    (0.25, {"Common": 0.25, "Rare": 0.25, "Epic": 0.25, "Legendary": 0.25}),
    ([1, 2, 3, 4], {"Common": 1.0, "Rare": 2.0, "Epic": 3.0, "Legendary": 4.0}),
    ({"legendary": 4, "Epic": 3, "rare": 2, "COMMON": 1},
     {"Common": 1.0, "Rare": 2.0, "Epic": 3.0, "Legendary": 4.0}),
])
def test_values_forms(values, want):
    assert TA.normalise_values(values) == want


@pytest.mark.parametrize("bad", [[1, 2, 3], {"Common": 1}, "a lot", True])
def test_bad_values_are_refused(bad):
    with pytest.raises(TA.AddStatError):
        TA.normalise_values(bad)


def test_the_talent_kind_applies_add_stats(tmp_path, wukong):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import talents

    defn = ContentDef(kind="talent", id="dragon_cd", fields={
        "hero": "SunWukong",
        "add_stats": [{"talent": "Trait Fire", "stat": "CD reduce trait",
                       "values": [0.10, 0.15, 0.20, 0.25]}],
    })
    written = talents.emit("test-mod", defn, tmp_path)

    assert len(written) == 1
    out = written[0].read_bytes()
    state = comp(out, "Skill Trait Fire", "StateSettings")
    assert len(state.refs) == 1
    assert struct.unpack("<I", EA.modifier_stat(out, state.refs[0].path.rsplit("\\", 1)[-1]))[0] \
        == struct.unpack("<I", TA.stat_key_bytes("CD reduce trait"))[0]


# --- the talent builder: rebuild a talent from scratch -----------------------

def test_rebuild_turns_the_talents_own_effect_off(beowulf):
    before = EG.parse(beowulf)
    old_state = next(c for c in before.components
                     if c.name == "Skill Attack Fire Cone" and c.cls.endswith("StateSettings"))

    out, cleared = TA.rebuild_talent(beowulf, talent="Attack Fire Cone")

    g = EG.parse(out)
    ctl = next(c for c in g.components if c.name == "Skill Controller Attack Fire Cone")
    # The controller switches on the new, empty state, never the old one.
    assert not any(r.guid == old_state.guid for r in ctl.refs)
    new = next(c for c in g.components if c.name == TA.rebuilt_name("Attack Fire Cone"))
    assert any(r.guid == new.guid for r in ctl.refs)
    assert new.refs == []
    # Its card's old numbers are gone, so the rebuilt card numbers from {0}.
    assert cleared >= 1
    _s, _sel, fmt = TA.talent_parts(g, "Attack Fire Cone")
    assert fmt.refs == []
    assert EC.check(out, beowulf, name="Hero_Beowulf") == []


def test_stats_added_after_a_rebuild_attach_to_the_new_state(beowulf):
    out, _ = TA.rebuild_talent(beowulf, talent="Attack Fire Cone")
    out, added = TA.add_stat(out, beowulf, talent="Attack Fire Cone",
                             stat="Crit chance primary", values=[0.05, 0.1, 0.15, 0.2])

    assert added.slot == 0
    new = comp(out, TA.rebuilt_name("Attack Fire Cone"))
    assert [r.path.rsplit("\\", 1)[-1] for r in new.refs] == [added.modifier]
    old = comp(out, "Skill Attack Fire Cone", "StateSettings")
    assert all(not r.path.endswith(added.modifier) for r in old.refs)
    assert EC.check(out, beowulf, name="Hero_Beowulf") == []


def test_rebuilding_twice_is_refused(beowulf):
    out, _ = TA.rebuild_talent(beowulf, talent="Attack Fire Cone")
    with pytest.raises(TA.AddStatError, match="already rebuilt"):
        TA.rebuild_talent(out, talent="Attack Fire Cone")


def test_the_talent_kind_rebuilds_before_adding(tmp_path, beowulf):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import talents

    defn = ContentDef(kind="talent", id="keen_eye", fields={
        "hero": "Beowulf",
        "rebuild": ["Attack Fire Cone"],
        "add_stats": [{"talent": "Attack Fire Cone", "stat": "Crit chance primary",
                       "values": 0.1}],
    })
    out = talents.emit("test-mod", defn, tmp_path)[0].read_bytes()

    new = comp(out, TA.rebuilt_name("Attack Fire Cone"))
    assert len(new.refs) == 1


# --- conditions: "during <ability>" -------------------------------------------

@pytest.fixture(scope="module")
def aladdin() -> bytes:
    return hero_file("Aladdin")


def test_ability_states_come_from_the_buttons_controllers():
    beowulf = EG.parse(hero_file("Beowulf"))
    assert TA.ability_state(beowulf, "DEFENSE").name == "State Ability Defensive"
    assert TA.ability_state(beowulf, "ATTACK").name == "State Basic Attack"
    assert TA.ability_state(beowulf, "DASH").name == "Child State Dash Ability"
    # Snow Queen's DEFENSE controller runs a state named "Secondary": the
    # controller decides, not the name.
    snow = EG.parse(hero_file("Snow_Queen"))
    assert TA.ability_state(snow, "DEFENSE").name == "State Ability Secondary"


def test_a_momentary_event_state_is_refused_for_during():
    merlin = EG.parse(hero_file("Merlin"))
    with pytest.raises(TA.AddStatError, match="only signals its start"):
        TA.ability_state(merlin, "DEFENSE")


def test_during_makes_the_amount_conditional(beowulf, aladdin):
    out, added = TA.add_stat(beowulf, beowulf, talent="Attack Flurry",
                             stat="Attack power basic", values=[0.1, 0.15, 0.2, 0.25],
                             during="DEFENSE", during_donor_raw=aladdin)

    g = EG.parse(out)
    modifier = comp(out, added.modifier)
    cond = next(c for c in g.components if c.guid == modifier.refs[0].guid)
    # "DEFENSE's state active -> the per-rarity number, else 0".
    assert [r.path.rsplit("\\", 1)[-1] for r in cond.refs] == \
        ["State Ability Defensive", added.selector]
    # The card still shows the per-rarity number itself.
    tiers = {t: round(v[1], 4) for t, v in TV.tier_values(out, added.selector).items()}
    assert tiers["Legendary"] == 0.25
    assert EC.check(out, beowulf, name="Hero_Beowulf") == []


def test_the_same_stat_can_be_added_always_and_during(beowulf, aladdin):
    out, _ = TA.add_stat(beowulf, beowulf, talent="Attack Flurry",
                         stat="Attack power basic", values=0.1)
    out, _ = TA.add_stat(out, beowulf, talent="Attack Flurry", stat="Attack power basic",
                         values=0.2, during="DEFENSE", during_donor_raw=aladdin)
    assert EC.check(out, beowulf, name="Hero_Beowulf") == []


def test_unknown_ability_is_refused(beowulf, aladdin):
    with pytest.raises(TA.AddStatError, match="unknown ability"):
        TA.add_stat(beowulf, beowulf, talent="Attack Flurry", stat="Attack power basic",
                    values=0.1, during="JUMP", during_donor_raw=aladdin)


# --- card slots must be read the way card slots read -------------------------

def _slot_accessors(raw: bytes, fmt_name: str) -> list[tuple[str, str]]:
    from rsmm.engine import entity_graph_edit as GE

    ef = GE.EntityFile(raw)
    c = ef.component(fmt_name)
    out = []
    for f in ef._format_slots(c)[0]:
        toks = EG.tokens(EG.Component(0, c.cls, "", "", b"", None,
                                      body=c.body[f.offset:f.offset + f.size], classes=c.classes))
        i = next(i for i, t in enumerate(toks) if t.kind == "ref")
        out.append((toks[i].text.rsplit("\\", 1)[-1], toks[i + 1].text))
    return out


def test_a_new_card_slot_reads_its_selector_like_the_games_slots_do(wukong, beowulf):
    # Copied from Fiery Dragon's own slot (which reads a calculation), the new
    # slot kept the calculation's accessor and the card showed +0% in game.
    out, added = TA.add_stat(wukong, beowulf, talent="Trait Fire",
                             stat="CD reduce trait", values=0.25)
    slots = dict(_slot_accessors(out, "Skill String Desc Trait Fire"))
    assert slots[added.selector] == "64 c9 d2 0f"
    assert slots["Skill Trait Fire Supposed Damage Operation"] == "11 78 ae 17"  # untouched


def test_a_rebuilt_card_slot_reads_its_selector_correctly(aladdin, beowulf):
    out, _ = TA.rebuild_talent(aladdin, talent="Attack Dive")
    out, added = TA.add_stat(out, beowulf, talent="Attack Dive", stat="Attack power basic",
                             values=[0.2, 0.3, 0.4, 0.5], during="DEFENSE",
                             during_donor_raw=aladdin)
    assert _slot_accessors(out, "Skill String Desc Attack Dive") == \
        [(added.selector, "64 c9 d2 0f")]
