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
from rsmm.engine import entity_fields as EF
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


# --- stats the game only puts on whoever is hit ---------------------------------

def test_on_hit_stats_are_the_debuffs_not_the_buffs(wukong):
    on_hit = TA.applied_on_hit()
    for debuff in ("Ignite", "Bleed", "Chilled", "Vulnerable", "Weak", "Marked", "Rooted"):
        assert TA.resolve_stat(debuff) in on_hit, debuff
    for own in ("Strength", "Regeneration", "Shield", "Attack power", "CD reduce trait",
                "Crit damage", "Armour"):
        assert TA.resolve_stat(own) not in on_hit, own


def test_an_on_hit_stat_is_refused_because_it_would_debuff_the_hero(wukong, beowulf):
    with pytest.raises(TA.AddStatError, match="debuff its own hero"):
        TA.add_stat(wukong, beowulf, talent="Trait Fire", stat="Vulnerable", values=0.2)


# --- conditions: "for N s after <ability>" --------------------------------------

def _refs(raw: bytes, name: str, field: str) -> list[str]:
    c = comp(raw, name)
    f = next(f for f in EF.fields(c) if f.name == field)
    items = f.items if f.kind == "ref[]" else [f]
    return [i.text.rsplit("\\", 1)[-1] for i in items if i.text and "(none)" not in i.text]


def test_after_builds_a_window_the_ability_restarts(wukong, beowulf, aladdin):
    out, added = TA.add_stat(wukong, beowulf, talent="Trait Fire", stat="Attack power",
                             values=0.3, after="DEFENSE", seconds=4, during_donor_raw=aladdin)
    tag = "Skill Trait Fire Added 15a486c4 After DEFENSE"
    # Using DEFENSE fires the restart event, which switches the window off and on...
    assert _refs(out, "State Defensive Ability", "activates")[-1] == f"Event {tag} Window Restart"
    assert _refs(out, f"Event {tag} Window Restart", "activates") == [f"{tag} Window"]
    assert _refs(out, f"Event {tag} Window Restart", "deactivates?") == [f"{tag} Window"]
    # ...the window runs only its timer, and the timer ENDS the window after 4 s
    # (a timer's `state` never switches a state on: the first build relied on
    # that and the window never came on in game)...
    assert _refs(out, f"{tag} Window", "while_active") == [f"{tag} Window Timer"]
    assert _refs(out, f"{tag} Window Timer", "state") == [f"{tag} Window"]
    timer = comp(out, f"{tag} Window Timer")
    assert next(f for f in EF.fields(timer) if f.name == "duration").text == "f32 4"
    # ...and the amount is "window on -> the per-rarity number, else 0".
    assert [r.path.rsplit("\\", 1)[-1] for r in comp(out, f"{tag} Condition Selector").refs] \
        == [f"{tag} Window", added.selector]
    assert EC.check(out, wukong, name="Hero_SunWukong") == []


def test_after_accepts_an_ability_that_only_signals_its_start(beowulf, aladdin):
    merlin = hero_file("Merlin")
    out, _ = TA.add_stat(merlin, beowulf, talent="Trait Quest Gain Charge", stat="Crit chance",
                         values=0.1, after="DEFENSE", seconds=2, during_donor_raw=aladdin)
    assert EC.check(out, merlin, name="Hero_Merlin") == []


@pytest.mark.parametrize("seconds", [None, 0, -1, True, "3"])
def test_after_needs_a_positive_number_of_seconds(wukong, beowulf, aladdin, seconds):
    with pytest.raises(TA.AddStatError, match="seconds"):
        TA.add_stat(wukong, beowulf, talent="Trait Fire", stat="Attack power", values=0.3,
                    after="DEFENSE", seconds=seconds, during_donor_raw=aladdin)


def test_during_and_after_together_are_refused(wukong, beowulf, aladdin):
    with pytest.raises(TA.AddStatError, match="not both"):
        TA.add_stat(wukong, beowulf, talent="Trait Fire", stat="Attack power", values=0.3,
                    during="POWER", after="DEFENSE", seconds=3, during_donor_raw=aladdin)


def test_the_talent_kind_passes_after_and_seconds(tmp_path, wukong):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import talents

    defn = ContentDef(kind="talent", id="dragon_after", fields={
        "hero": "SunWukong",
        "add_stats": [{"talent": "Trait Fire", "stat": "Attack power", "values": 0.3,
                       "after": "DEFENSE", "seconds": 4}],
    })
    [path] = talents.emit("test-mod", defn, tmp_path)
    timer = comp(path.read_bytes(), "Skill Trait Fire Added 15a486c4 After DEFENSE Window Timer")
    assert next(f for f in EF.fields(timer) if f.name == "duration").text == "f32 4"


# --- "at most once every M s": Romeo's Love Shield gate ----------------------------

@pytest.fixture(scope="module")
def romeo_juliet() -> bytes:
    for f in corpus.files("EntitySettings/Heroes/Hero_Juliet"):
        if f.name == f"{TA.DONOR_LIMITER_FILE}{GEN}":
            return f.read_bytes()
    pytest.skip(f"{TA.DONOR_LIMITER_FILE} entity not available (no mirror or game install)")


def test_cooldown_gates_the_window_restart(wukong, beowulf, aladdin, romeo_juliet):
    out, _ = TA.add_stat(wukong, beowulf, talent="Trait Fire", stat="Attack power",
                         values=0.3, after="DEFENSE", seconds=3, cooldown=8,
                         during_donor_raw=aladdin, limiter_donor_raw=romeo_juliet)
    tag = "Skill Trait Fire Added 15a486c4 After DEFENSE"
    # DEFENSE fires the gate's tester, not the restart event directly...
    acts = _refs(out, "State Defensive Ability", "activates")
    assert acts[-1] == f"{tag} Cooldown Tester"
    assert f"Event {tag} Window Restart" not in acts
    # ...which switches the Cooldown state on; it restarts the window, and its
    # timer ends it after 8 s...
    assert _refs(out, f"{tag} Cooldown Tester", "on_true") == [f"{tag} Cooldown"]
    assert _refs(out, f"{tag} Cooldown", "activates") == [f"{tag} Cooldown Timer",
                                                          f"Event {tag} Window Restart"]
    assert _refs(out, f"{tag} Cooldown Timer", "state") == [f"{tag} Cooldown"]
    timer = comp(out, f"{tag} Cooldown Timer")
    assert next(f for f in EF.fields(timer) if f.name == "duration").text == "f32 8"
    # ...Available is held on by the owned state, and none of Romeo's shield
    # (invincibility, FX, his cooldown timer) or his file's name came along.
    assert f"{tag} Cooldown Available" in _refs(out, "Skill Trait Fire", "while_active")
    for state in (f"{tag} Cooldown", f"{tag} Cooldown Available"):
        assert _refs(out, state, "while_active") == []
    assert b"Romeo_Juliet" not in out and b"Invulnerable" not in out
    assert EC.check(out, wukong, name="Hero_SunWukong") == []


def test_cooldown_tests_its_own_copies(wukong, beowulf, aladdin, romeo_juliet):
    from rsmm.engine import entity_edit as EE
    out, _ = TA.add_stat(wukong, beowulf, talent="Trait Fire", stat="Attack power",
                         values=0.3, after="DEFENSE", seconds=3, cooldown=8,
                         during_donor_raw=aladdin, limiter_donor_raw=romeo_juliet)
    tag = "Skill Trait Fire Added 15a486c4 After DEFENSE"
    ed = EE.EntityEdit(out)
    tested = sorted(b.decode() for a, z in ed._subtest_ranges(f"{tag} Cooldown Tester")
                    for b in [ed.concat[a:z].split(b"\\")[-1].split(b'"')[0]])
    assert tested == [f"{tag} Cooldown", f"{tag} Cooldown Available"]


@pytest.mark.parametrize("cooldown", [0, -2, True, "8"])
def test_cooldown_needs_a_positive_number(wukong, beowulf, aladdin, romeo_juliet, cooldown):
    with pytest.raises(TA.AddStatError, match="cooldown"):
        TA.add_stat(wukong, beowulf, talent="Trait Fire", stat="Attack power", values=0.3,
                    after="DEFENSE", seconds=3, cooldown=cooldown,
                    during_donor_raw=aladdin, limiter_donor_raw=romeo_juliet)


def test_cooldown_without_after_is_refused(wukong, beowulf, romeo_juliet):
    with pytest.raises(TA.AddStatError, match="give 'after' too"):
        TA.add_stat(wukong, beowulf, talent="Trait Fire", stat="Attack power", values=0.3,
                    cooldown=8, limiter_donor_raw=romeo_juliet)


def test_the_talent_kind_passes_cooldown(tmp_path, wukong, romeo_juliet):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import talents

    defn = ContentDef(kind="talent", id="dragon_gated", fields={
        "hero": "SunWukong",
        "add_stats": [{"talent": "Trait Fire", "stat": "Attack power", "values": 0.3,
                       "after": "DEFENSE", "seconds": 3, "cooldown": 8}],
    })
    [path] = talents.emit("test-mod", defn, tmp_path)
    timer = comp(path.read_bytes(),
                 "Skill Trait Fire Added 15a486c4 After DEFENSE Cooldown Timer")
    assert next(f for f in EF.fields(timer) if f.name == "duration").text == "f32 8"


# --- "your next X after Y": the window ends when X's use ends ----------------------

def test_next_ends_the_window_as_that_ability_finishes(wukong, beowulf, aladdin):
    out, _ = TA.add_stat(wukong, beowulf, talent="Trait Fire", stat="Attack power",
                         values=0.5, after="DEFENSE", seconds=4, next_ability="ATTACK",
                         during_donor_raw=aladdin)
    tag = "Skill Trait Fire Added 15a486c4 After DEFENSE Next ATTACK"
    attack = TA.ability_state(EG.parse(out), "ATTACK").name
    # ATTACK's on-exit list fires an event that only switches the window off...
    assert _refs(out, attack, "disables_while_active?") == [f"Event {tag} Window Used Up"]
    assert _refs(out, f"Event {tag} Window Used Up", "activates") == []
    assert _refs(out, f"Event {tag} Window Used Up", "deactivates?") == [f"{tag} Window"]
    # ...and DEFENSE still restarts it as before.
    assert _refs(out, "State Defensive Ability", "activates")[-1] == f"Event {tag} Window Restart"
    assert EC.check(out, wukong, name="Hero_SunWukong") == []


@pytest.mark.parametrize(("kw", "msg"), [
    ({"next_ability": "ATTACK"}, "give 'after' too"),
    ({"after": "DEFENSE", "seconds": 3, "next_ability": "DEFENSE"}, "starts the window"),
])
def test_a_bad_next_is_refused(wukong, beowulf, aladdin, kw, msg):
    with pytest.raises(TA.AddStatError, match=msg):
        TA.add_stat(wukong, beowulf, talent="Trait Fire", stat="Attack power", values=0.3,
                    during_donor_raw=aladdin, **kw)


def test_next_refuses_an_ability_that_only_signals_its_start(beowulf, aladdin):
    merlin = hero_file("Merlin")
    with pytest.raises(TA.AddStatError, match="only signals its start"):
        TA.add_stat(merlin, beowulf, talent="Trait Quest Gain Charge", stat="Crit chance",
                    values=0.1, after="ATTACK", seconds=2, next_ability="DEFENSE",
                    during_donor_raw=aladdin)


def test_next_and_cooldown_combine(wukong, beowulf, aladdin, romeo_juliet):
    out, _ = TA.add_stat(wukong, beowulf, talent="Trait Fire", stat="Attack power",
                         values=0.5, after="DEFENSE", seconds=4, next_ability="ATTACK",
                         cooldown=10, during_donor_raw=aladdin, limiter_donor_raw=romeo_juliet)
    assert EC.check(out, wukong, name="Hero_SunWukong") == []


def test_the_talent_kind_passes_next(tmp_path, wukong):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import talents

    defn = ContentDef(kind="talent", id="dragon_next", fields={
        "hero": "SunWukong",
        "add_stats": [{"talent": "Trait Fire", "stat": "Attack power", "values": 0.5,
                       "after": "DEFENSE", "seconds": 4, "next": "ATTACK"}],
    })
    [path] = talents.emit("test-mod", defn, tmp_path)
    comp(path.read_bytes(),
         "Event Skill Trait Fire Added 15a486c4 After DEFENSE Next ATTACK Window Used Up")


# --- talents built in a file the hero inherits ------------------------------------

def test_an_inherited_talent_is_built_in_the_file_that_holds_it(tmp_path, romeo_juliet):
    # Romeo's own file only overrides Love Shield's controller; its state, numbers
    # and card text live in the Romeo/Juliet common file, written back there.
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import talents

    defn = ContentDef(kind="talent", id="shield", fields={
        "hero": "Romeo",
        "add_stats": [{"talent": "Special Invulnerable", "stat": "Armour",
                       "values": [5, 10, 15, 20], "percent": False}],
    })
    [path] = talents.emit("test-mod", defn, tmp_path)
    assert path.relative_to(tmp_path).as_posix() == (
        f"EntitySettings/Heroes/Hero_Juliet/{TA.DONOR_LIMITER_FILE}{GEN}")
    out = path.read_bytes()
    owned = comp(out, "Skill Special Invulnerable", "StateSettings")
    assert any("Added" in r.path and r.path.endswith("Modifier") for r in owned.refs)
    assert EC.check(out, romeo_juliet, name=TA.DONOR_LIMITER_FILE) == []


def test_rebuilding_an_overridden_inherited_talent_is_refused(tmp_path, romeo_juliet):
    from rsmm.sdk.content import ContentDef, ContentError
    from rsmm.sdk.kinds import talents

    defn = ContentDef(kind="talent", id="rb", fields={
        "hero": "Romeo", "rebuild": ["Special Invulnerable"]})
    with pytest.raises(ContentError, match="cannot turn an inherited talent off"):
        talents.emit("test-mod", defn, tmp_path)


def test_two_stats_on_one_talent_in_one_block_get_their_own_guids(tmp_path, wukong):
    # The kind passes one seed for the whole block; the second entry used to
    # mint the first one's GUIDs and fail ("a minted GUID collides").
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import talents

    defn = ContentDef(kind="talent", id="two", fields={
        "hero": "SunWukong",
        "add_stats": [{"talent": "Trait Fire", "stat": "CD reduce trait", "values": 0.1},
                      {"talent": "Trait Fire", "stat": "Crit chance", "values": 0.05}],
    })
    [path] = talents.emit("test-mod", defn, tmp_path)
    assert len(comp(path.read_bytes(), "Skill Trait Fire", "StateSettings").refs) == 2


# --- game state is not a stat ---------------------------------------------------

def test_game_state_is_told_apart_from_stats(wukong):
    from rsmm.engine import item_modifier as IM
    state = IM.game_state_keys()
    for flag in ("Is in cinematic", "Is in book scene", "Is day", "Current map id",
                 "Is Session Host", "Cheat version"):
        assert TA.resolve_stat(flag) in state, flag
    for stat in ("Armour", "Attack power", "CD reduce trait", "Strength", "Vulnerable",
                 "Ability_Charge_Trait", "Basic Attack Speed"):
        assert TA.resolve_stat(stat) not in state, stat


def test_a_game_state_flag_is_refused(wukong, beowulf):
    with pytest.raises(TA.AddStatError, match="game state"):
        TA.add_stat(wukong, beowulf, talent="Trait Fire", stat="Is in cinematic", values=1)


# --- include another talent's effect --------------------------------------------

@pytest.fixture(scope="module")
def red() -> bytes:
    return hero_file("Red")


def test_shapeshifter_can_include_short_wicks_instant_bomb(red):
    # Short Wick's "explodes on landing" is a bool wired to its state, read by
    # Hero_Red_Bomb; owning Shapeshifter now switches that state on too.
    out = TA.include_talent(red, talent="Trait Active", other="Secondary Quick Bombs")
    assert _refs(out, "Skill Trait Active", "while_active") == [
        "Skill Trait Active Max Health Modifier", "Skill Secondary Quick Bombs"]
    assert EC.check(out, red, name="Hero_Red") == []


@pytest.mark.parametrize(("talent", "other", "msg"), [
    ("Trait Active", "Trait Active", "itself"),
    ("Trait Active", "Nope", "no talent"),
])
def test_a_bad_include_is_refused(red, talent, other, msg):
    with pytest.raises(TA.AddStatError, match=msg):
        TA.include_talent(red, talent=talent, other=other)


def test_including_twice_is_refused(red):
    out = TA.include_talent(red, talent="Trait Active", other="Secondary Quick Bombs")
    with pytest.raises(TA.AddStatError, match="already includes"):
        TA.include_talent(out, talent="Trait Active", other="Secondary Quick Bombs")


def test_the_talent_kind_applies_include(tmp_path, red):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import talents

    defn = ContentDef(kind="talent", id="wick", fields={
        "hero": "Red",
        "include": [{"talent": "Trait Active", "from": "Secondary Quick Bombs"}],
    })
    [path] = talents.emit("test-mod", defn, tmp_path)
    assert "Skill Secondary Quick Bombs" in _refs(path.read_bytes(), "Skill Trait Active",
                                                  "while_active")


# --- include another HERO's talent ----------------------------------------------

def hero_readers(hero: str) -> list[bytes]:
    return [f.read_bytes() for f in corpus.files(f"EntitySettings/Heroes/Hero_{hero}")
            if f.name.endswith(GEN) and f.name != f"Hero_{hero}{GEN}"]


@pytest.fixture(scope="module")
def piper() -> bytes:
    return hero_file("Piper")


def test_piper_can_borrow_wukongs_power_hold(piper, wukong):
    out = TA.borrow_talent(piper, wukong, talent="Attack Move Speed", other="Power Hold",
                           hero="SunWukong", readers=hero_readers("SunWukong"))
    assert _refs(out, "Skill Attack Move Speed", "while_active")[-1] == \
        "Skill Power Hold From SunWukong"
    assert _refs(out, "Skill Power Hold From SunWukong", "while_active") == [
        "Skill Power Hold AP Modifier From SunWukong"]
    # The numbers are keyed on PIPER's card now, and keep Wukong's per-rarity check.
    sel = comp(out, "Skill Power Hold AP Selector From SunWukong")
    assert {r.path for r in sel.refs} == {
        "[Dt Skill Controller] Hero_Piper\\Skills\\Skill Controller Attack Move Speed"}
    assert TV.tier_values(out, sel.name) == TV.tier_values(wukong, "Skill Power Hold AP Selector")
    assert EC.check(out, piper, name="Hero_Piper") == []


@pytest.mark.parametrize(("hero", "other", "msg"), [
    ("Aladdin", "Defense Tornado", "inside its hero's abilities"),
    ("Geppetto", "Passive Create Objects", "does not load"),
    ("Melusine", "Ultimate 2 Spawn More", "only numbers"),
])
def test_a_talent_bound_to_its_hero_is_not_borrowed(piper, hero, other, msg):
    with pytest.raises(TA.AddStatError, match=msg):
        TA.borrow_talent(piper, hero_file(hero), talent="Attack Move Speed", other=other,
                         hero=hero, readers=hero_readers(hero))


def test_borrowing_twice_is_refused(piper, wukong):
    out = TA.borrow_talent(piper, wukong, talent="Attack Move Speed", other="Power Hold",
                           hero="SunWukong", readers=hero_readers("SunWukong"))
    with pytest.raises(TA.AddStatError, match="already includes"):
        TA.borrow_talent(out, wukong, talent="Attack Move Speed", other="Power Hold",
                         hero="SunWukong", readers=hero_readers("SunWukong"))


def test_the_talent_kind_includes_from_another_hero(tmp_path, piper):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import talents

    defn = ContentDef(kind="talent", id="borrow", fields={
        "hero": "Piper",
        "include": [{"talent": "Attack Move Speed", "from": "Power Hold", "hero": "SunWukong"}],
    })
    [path] = talents.emit("test-mod", defn, tmp_path)
    assert "Skill Power Hold From SunWukong" in _refs(path.read_bytes(),
                                                      "Skill Attack Move Speed", "while_active")
