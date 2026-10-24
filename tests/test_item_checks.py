"""Item build checks: the traps that each cost a playtest on Little Thumb
Pebbles (an Increase_Shield copy made into "+30% crit for 5 s after a hit",
2026-10-20), plus the copy identity default and links removed by name."""

from __future__ import annotations

import struct

import pytest

from rsmm.engine import corpus
from rsmm.engine import entity_fields as EF
from rsmm.engine import magic_item_cook as C
from rsmm.engine.entity_graph_edit import EntityFile
from rsmm.engine.item_checks import item_warnings

_SHIELD = ("EntitySettings/Objects/Magical_Objects/Rare/"
           "Increase_Shield.entity.ot.EntitySettingsResource.gen")


def _shield() -> bytes:
    data = corpus.read(_SHIELD)
    if data is None:
        pytest.skip("shipped items not available (no mirror, no install)")
    return data


def _build(**kw) -> bytes:
    files = C.build_magic_item(new_id="Increase_Crit_M", base_id="Increase_Shield",
                               base_cooked=_shield(), corpus=[], rarity="Rare", **kw)
    return next(b for p, b in files.items() if p.endswith(".gen"))


def _warns(**kw) -> list[str]:
    return item_warnings(_build(**kw), _shield(), set(kw.get("modifier_stats") or {}))


def test_the_original_pebbles_manifest_warns_of_stacking_and_level_scaling():
    ws = _warns(value_patches=[("Shield Value", 1.0, 0.3, False)],
                modifier_stats={"Modifier": "Crit chance"})
    assert len(ws) == 2
    assert "granted for good" in ws[0] and "'On Damage Received'" in ws[0]
    assert "'Level Healing Selector'" in ws[1] and "Level Healing" in ws[1]


def test_a_fraction_on_a_plain_card_slot_is_flagged():
    """Increase_Shield's amount slot prints the number as it is: 0.3 read "+0%"."""
    ws = _warns(value_patches=[("Shield Value", 1.0, 0.3, False)],
                modifier_stats={"Modifier": "Crit chance"},
                steps=[{"link": "Modifier.amount", "to": "Shield Value"},
                       {"link": "Descripton Format.obj_4[0]", "to": "Shield Value"}])
    assert any("plain number" in w and 'percent = "Descripton Format.obj_4"' in w for w in ws)
    ws = _warns(value_patches=[("Shield Value", 1.0, 0.3, False)],
                modifier_stats={"Modifier": "Crit chance"},
                steps=[{"link": "Modifier.amount", "to": "Shield Value"},
                       {"link": "Descripton Format.obj_4[0]", "to": "Shield Value"},
                       {"percent": "Descripton Format.obj_4", "value": True}])
    assert not any("plain number" in w for w in ws)


def test_an_untouched_copy_is_quiet():
    """The shield's own permanent grant is what the shipped item intends."""
    assert _warns(value_patches=[("Shield Value", 1.0, 0.3, False)]) == []


def test_copies_left_pointing_into_their_donor_are_refused():
    with pytest.raises(ValueError, match=r"Dash_Crit_Chance\\Crit Chance Duration Value"):
        _build(steps=[{"clone": ["Crit Chance Modifier Timer"],
                       "from": "Objects/Magical_Objects/Common/Dash_Crit_Chance",
                       "suffix": " P"}])


def test_a_link_is_removed_by_what_it_points_at():
    ent = _build(steps=[{"remove_link": "On Damage Received.activates", "to": "Modifier"}])
    acts = next(f for f in EF.fields(EntityFile(ent, "x").component("On Damage Received"))
                if f.name == "activates")
    assert [i.text.rsplit("\\", 1)[-1] for i in acts.items] == ["Shield Reload Timer"]
    with pytest.raises(ValueError, match=r"links to 'Nope' 0 times \(it links to: "
                                         r"Shield Reload Timer, Modifier\)"):
        _build(steps=[{"remove_link": "On Damage Received.activates", "to": "Nope"}])


def _emit(tmp_path, **fields) -> bytes:
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import items
    _shield()
    paths = items.emit("m", ContentDef("item", "Increase_Crit_M",
                                       {"base": "Increase_Shield", **fields}), tmp_path)
    return next(p.read_bytes() for p in paths if p.name.endswith(".gen"))


def test_a_copy_gets_its_own_identity_unless_it_opts_out(tmp_path):
    """Without one, a grant handed out the vanilla 30 s shield (2026-10-20)."""
    shipped = C.find_identity_guid(_shield(), "Increase_Shield")
    own = _emit(tmp_path / "a")
    assert C.find_identity_guid(own, "Increase_Crit_M") != shipped
    shared = _emit(tmp_path / "b", unique_identity=False)
    assert C.find_identity_guid(shared, "Increase_Crit_M") == shipped


# --- effect = { stat, amount, seconds, on } -------------------------------------------

def _effect(**kw) -> dict:
    return {"stat": "Crit chance", "amount": 0.3, "seconds": 5, "on": "damage_taken"} | kw


def _slots(ent: bytes) -> list[tuple[str, int]]:
    from rsmm.cli.editor.content import _built_slots
    return [(s["node"], s["mode"]) for s in _built_slots(ent, "Descripton Format")]


def test_an_effect_builds_the_proven_timed_bonus_and_cuts_the_bases_own():
    """The Pebbles recipe (2026-10-20), on any base: the copied trigger restarts
    the copied timer, the copied tester holds the copied modifier on, and the
    shield's permanent grant is gone."""
    from rsmm.engine import item_modifier as IM
    ent = _build(effect=_effect())
    eq = next(f for f in EF.fields(EntityFile(ent, "x").component("State Picked Up"))
              if f.name == "while_active").text
    assert "On Damage Received Event Listener Effect" in eq
    assert "Crit Chance Modifier Active Tester Effect" in eq
    hit = {f.name: f.text for f in EF.fields(EntityFile(ent, "x").component("On Damage Received"))}
    assert "Modifier" not in hit["activates"].rsplit("\\", 1)[-1]
    stats = {m.name: m.stat for m in IM.list_modifiers(ent)}
    assert stats["Crit Chance Modifier Effect"] == "Crit chance"
    assert _slots(ent) == [("Crit Chance Value Operation Effect", 1),
                           ("Crit Chance Duration Value Effect", 0)]
    assert b"Dash_Crit_Chance\\" not in ent and item_warnings(ent, _shield(), set()) == []


def test_an_effect_on_dash_and_without_percent():
    ent = _build(effect=_effect(on="dash", percent=False, refresh=False))
    state = {f.name: f.text for f in EF.fields(EntityFile(ent, "x").component("On Trigger Effect"))}
    assert state["activates"].endswith("Crit Chance Modifier Timer Effect")
    assert "Timer" not in (state.get("deactivates?") or "")        # no restart
    assert _slots(ent)[0] == ("Crit Chance Value Operation Effect", 0)


@pytest.mark.parametrize("on", sorted(__import__("rsmm.engine.item_effect",
                                                     fromlist=["TRIGGERS"]).TRIGGERS))
def test_every_trigger_points_its_copied_listener_at_the_trigger_state(on):
    """Every trigger is the listener of a shipped item that reacts to it (23
    listeners surveyed, 2026-10-20); copied, it must reach the effect's own
    trigger state and nothing of its donor."""
    from rsmm.engine.item_effect import TRIGGERS
    ent = _build(effect=_effect(on=on))
    t = TRIGGERS[on]
    hop = EntityFile(ent, "x").component((t.target or t.listener) + " Effect")
    targets = [f.text for f in EF.fields(hop)
               if f.name in ("ref_3", "ref_4", "ref_5", "on_event", "on_true")
               and f.text and "<-" in f.text]
    assert targets and all(x.endswith("\\On Trigger Effect") for x in targets)
    assert item_warnings(ent, _shield(), set()) == []


def test_an_effect_disarms_the_bases_own_listeners():
    """Only the shield's modifier was cut: its damage listener still ran the
    30 s reload, so 14 shield copies all showed a cooldown after any hit."""
    def armed(ent):
        return next(f for f in EF.fields(EntityFile(ent, "x").component(
            "Shield Protection Up State")) if f.name == "while_active").text
    assert "On Damage Received Event Listener" not in armed(_build(effect=_effect(on="dash")))
    assert "On Damage Received Event Listener" in armed(
        _build(effect=_effect(on="dash", keep_base_effect=True)))


def test_keep_base_effect_leaves_the_shield_working():
    ent = _build(effect=_effect(keep_base_effect=True))
    hit = next(f for f in EF.fields(EntityFile(ent, "x").component("On Damage Received"))
               if f.name == "activates")
    assert any(i.text.rstrip().endswith("\\Modifier") for i in hit.items)


@pytest.mark.parametrize("bad, msg", [
    ({"stat": "Crit chanse"}, "stat"), ({"on": "jump"}, "damage_taken, dash"),
    ({"seconds": 0}, "above 0"), ({"amount": "lots"}, "number"), ({"color": 1}, "no field"),
])
def test_a_bad_effect_says_what_is_wrong(bad, msg):
    with pytest.raises(ValueError, match=msg):
        _build(effect=_effect(**bad))


def test_the_editor_preview_reads_the_built_card():
    """The card preview guessed percent from a "%" in the text; the game goes by
    the slot's display mode (a shield's 0.3 read "+0%")."""
    from rsmm.cli.editor.content import item_preview
    _shield()
    req = {"mode": "clone", "base": "Increase_Shield", "id": "Increase_Shie_M"}
    out = item_preview(req | {"effect": _effect()})
    assert out["description"] == [
        {"node": "Crit Chance Value Operation Effect", "value": 0.3, "mode": 1},
        {"node": "Crit Chance Duration Value Effect", "value": 5.0, "mode": 0}]
    assert out["warnings"] == []
    out = item_preview(req | {"values": [{"label": "Shield Value", "old": 1.0, "new": 0.3,
                                          "shadowed": False}],
                              "stats": [{"modifier": "Modifier", "stat": "Crit chance"}]})
    assert len(out["warnings"]) == 2 and out["description"][0]["mode"] == 2
    assert "error" in item_preview(req | {"id": "Inc M"})     # not an id
    assert "error" not in item_preview(req | {"id": "Inc"})   # any length is


def test_copies_get_their_own_type_id_too(tmp_path):
    """The Dt node's body id is unique per shipped item (114/114). Shared by 14
    Increase_Shield copies, picking Goldilocks' Porridge took one of them away."""
    a = _emit(tmp_path / "a")
    assert C.find_type_guid(a) != C.find_type_guid(_shield())
    shared = _emit(tmp_path / "b", unique_identity=False)
    assert C.find_type_guid(shared) == C.find_type_guid(_shield())


@pytest.mark.parametrize("base_rel, base_id", [
    ("Rare/Increase_Shield", "Increase_Shield"),      # had a countdown: re-pointed
    ("Common/Dash_Crit_Chance", "Dash_Crit_Chance"),  # had none: made to read the timer
])
def test_the_item_icon_counts_down_the_effect(base_rel, base_id):
    """The icon showed no countdown: the shield's link reads its timer with a key no
    Timer answers. value_4 = full time, value_5 = the timer's elapsed time."""
    raw = corpus.read(f"EntitySettings/Objects/Magical_Objects/{base_rel}"
                      ".entity.ot.EntitySettingsResource.gen")
    if raw is None:
        pytest.skip("shipped items not available")
    files = C.build_magic_item(new_id=base_id[:-2] + "_M", base_id=base_id, base_cooked=raw,
                               corpus=[], rarity="Rare", effect=_effect(seconds=7))
    ent = next(b for p, b in files.items() if p.endswith(".gen"))
    data = EntityFile(ent, "x").component("Dt Magical Object Data")
    d = {f.name: f.text for f in EF.fields(data)}
    assert d["value_4"].startswith("f32 7")
    assert d["value_5"].endswith("\\Crit Chance Modifier Timer Effect")
    # Read as ELAPSED time (0x1683197e), as the one working shipped countdown
    # does; the shield's 0x0fd2c964 is a key no Timer answers.
    lab = b"[Timer] " + base_id[:-2].encode() + b"_M\\Crit Chance Modifier Timer Effect"
    i = ent.find(lab, ent.find(b"Dt Magical Object Data"))
    j = ent.find(b'""\xbb\xaa', i)
    assert ent[j + 4:j + 8] == (0x1683197E).to_bytes(4, "little")


_BALOR = ("EntitySettings/Objects/Magical_Objects/Cursed/"
          "Charge_To_Damage.entity.ot.EntitySettingsResource.gen")


def _balor_warns(stats: dict[str, str]) -> list[str]:
    base = corpus.read(_BALOR)
    if base is None:
        pytest.skip("shipped items not available (no mirror, no install)")
    files = C.build_magic_item(new_id="Charge_To_Damagf", base_id="Charge_To_Damage",
                               base_cooked=base, corpus=[], rarity="Cursed",
                               modifier_stats=stats)
    return item_warnings(next(b for p, b in files.items() if p.endswith(".gen")), base,
                         set(stats))


def test_a_stat_nothing_in_the_game_changes_is_flagged():
    """Svalinn (2026-10-22): Balor's Eye moved to Defense and Ultimate did
    nothing; only Power and Special have the hero-side charge-to-damage logic."""
    ws = _balor_warns({"Power charge to damage Modifier": "Defensive charge to damage",
                       "Special charge to damage Modifier": "Ultimate charge to damage"})
    assert len(ws) == 2 and all("no item, talent or hero" in w for w in ws)
    assert "'Defensive charge to damage'" in ws[0]


def test_a_swap_between_stats_the_game_uses_is_quiet():
    assert _balor_warns({"Power charge to damage Modifier": "Secondary charge to damage"}) == []


# --- several effects, and items with no base ----------------------------------

def test_an_effect_without_seconds_is_always_on_and_one_with_needs_both():
    from rsmm.engine import item_effect as IE
    assert not IE.Effect.parse({"stat": "Crit chance", "amount": 0.1}).timed
    assert IE.Effect.parse({"stat": "Crit chance", "amount": 0.1, "seconds": 3}).on == \
        "damage_taken"
    with pytest.raises(IE.ItemEffectError, match="needs 'seconds'"):
        IE.Effect.parse({"stat": "Crit chance", "amount": 0.1, "on": "dash"})


def test_the_card_text_numbers_every_effect_in_order():
    from rsmm.engine import item_effect as IE
    text = IE.describe(IE.parse_effects([
        {"stat": "Crit chance", "amount": 0.1},
        {"stat": "Armour", "amount": 5, "percent": False},
        {"stat": "Attack power", "amount": 0.2, "seconds": 4, "on": "dash"}]))
    assert text.splitlines() == [
        "• #+{0}%@ #Crit chance@", "• #+{1}@ #Armour@",
        "• After dashing, gain #+{2}%@ #Attack power@ for #{3}@ seconds"]


def test_several_effects_build_on_one_item_with_no_issues():
    from rsmm.engine import entity_check as CK
    from rsmm.engine import item_modifier as IM
    eff = [{"stat": "Crit chance", "amount": 0.1},
           {"stat": "Armour", "amount": 5, "percent": False},
           {"stat": "Attack power", "amount": 0.2, "seconds": 4, "on": "dash"},
           {"stat": "Crit chance", "amount": 0.15, "seconds": 3, "on": "damage_taken"}]
    files = C.build_magic_item(new_id="Wanderers_Charm", base_id="Increase_Shield",
                               base_cooked=_shield(), corpus=[], rarity="Rare",
                               effect=eff, super_effect=False)
    ent = next(b for p, b in files.items() if p.endswith(".gen"))
    stats = {m.name: m.stat for m in IM.list_modifiers(ent)}
    assert stats["Crit Chance Modifier Effect 2"] == "Armour"
    assert stats["Crit Chance Modifier Effect 4"] == "Crit chance"
    assert CK.check(ent, _shield(), name="Wanderers_Charm") == []


def test_an_item_with_no_base_is_built_from_its_effects(tmp_path):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import items
    _shield()
    out = tmp_path / "mod" / "assets"
    files = items.emit("m", ContentDef("item", "Charm", {
        "name": "Charm", "effects": [{"stat": "Crit chance", "amount": 0.1}]}), out)
    ent = next(f for f in files if f.name.endswith(".EntitySettingsResource.gen"))
    assert ent.parent.name == "Common" and ent.name.startswith("Charm.")


def test_an_item_with_no_base_and_no_effects_says_what_it_needs(tmp_path):
    from rsmm.sdk.content import ContentDef, ContentError
    from rsmm.sdk.kinds import items
    with pytest.raises(ContentError, match="built from its 'effects'"):
        items.emit("m", ContentDef("item", "Charm", {"name": "Charm"}), tmp_path / "a")


def test_day_and_night_effects_build_and_describe():
    from rsmm.engine import entity_check as CK
    from rsmm.engine import item_effect as IE
    effs = [{"stat": "Crit chance", "amount": 0.15, "during": "day"},
            {"stat": "Armour", "amount": 8, "percent": False, "during": "night"}]
    parsed = IE.parse_effects(effs)
    assert [e.during for e in parsed] == ["day", "night"]
    assert IE.Effect.parse({"stat": "Crit chance", "amount": 0.1, "on": "day"}).during == "day"
    assert IE.describe(parsed).splitlines() == [
        "• During the day, #+{0}%@ #Crit chance@",
        "• During the night, #+{1}@ #Armour@",
    ]
    with pytest.raises(IE.ItemEffectError, match="during"):
        IE.Effect.parse({"stat": "Crit chance", "amount": 0.1, "during": "dusk"})
    files = C.build_magic_item(new_id="Solar_Lunar_Charm", base_id="Increase_Shield",
                               base_cooked=_shield(), corpus=[], rarity="Rare",
                               effect=effs, super_effect=False)
    ent = next(b for p, b in files.items() if p.endswith(".gen"))
    eq = next(f for f in EF.fields(EntityFile(ent, "x").component("State Picked Up"))
              if f.name == "while_active").text
    assert "Crit Chance Modifier Active Tester Effect" in eq
    assert "Crit Chance Modifier Active Tester Effect 2" in eq
    assert item_warnings(ent, _shield(), set()) == []
    assert CK.check(ent, _shield(), name="Solar_Lunar_Charm") == []


def test_item_effects_scale_with_duplicate_count():
    """Always-on and timed effects multiply their amount by Amount Selector,
    so duplicate item copies held in-game stack additively."""
    from rsmm.engine import entity_check as CK
    from rsmm.engine import entity_graph as EG
    from rsmm.engine import entity_parts as P
    _shield()
    effs = [
        {"stat": "Crit chance", "amount": 0.1},
        {"stat": "Attack power", "amount": 0.2, "seconds": 5.0, "on": "dash"},
    ]
    files = C.build_magic_item(new_id="Stacking_Item", base_id="Increase_Shield",
                               base_cooked=_shield(), corpus=[], rarity="Rare",
                               effect=effs, super_effect=False)
    ent = next(b for p, b in files.items() if p.endswith(".gen"))
    g = EG.parse(ent)
    comps = {c.name: c for c in g.components}

    # Effect 1: Always-on bonus
    op1 = comps["Crit Chance Value Operation Effect"]
    assert op1.cls == "oCEntityCpntValueOperationsSettings"
    op1_refs = [r.path for r in op1.refs]
    assert "[Value] Stacking_Item\\Crit Chance Value Effect" in op1_refs
    assert r"[Value Selector] Magical_Objects_Model\Amount Selector" in op1_refs
    mod1 = comps["Crit Chance Modifier Effect"]
    d1 = P.decode(mod1)
    op_path = "[Multi values operations] Stacking_Item\\Crit Chance Value Operation Effect"
    assert d1["amount"].source.path == op_path
    assert d1["amount"].key == 0x17ae7811
    assert struct.unpack("<f", d1["amount"].value)[0] == pytest.approx(0.1)

    # Effect 2: Timed bonus after trigger
    op2 = comps["Crit Chance Value Operation Effect 2"]
    assert op2.cls == "oCEntityCpntValueOperationsSettings"
    op2_refs = [r.path for r in op2.refs]
    assert "[Value] Stacking_Item\\Crit Chance Value Effect 2" in op2_refs
    assert r"[Value Selector] Magical_Objects_Model\Amount Selector" in op2_refs
    mod2 = comps["Crit Chance Modifier Effect 2"]
    d2 = P.decode(mod2)
    op_path2 = "[Multi values operations] Stacking_Item\\Crit Chance Value Operation Effect 2"
    assert d2["amount"].source.path == op_path2
    assert d2["amount"].key == 0x17ae7811
    assert struct.unpack("<f", d2["amount"].value)[0] == pytest.approx(0.2)

    # Description format slots point to the operations
    slots = _slots(ent)
    assert slots[0] == ("Crit Chance Value Operation Effect", 1)
    assert slots[1] == ("Crit Chance Value Operation Effect 2", 1)
    assert slots[2] == ("Crit Chance Duration Value Effect 2", 0)

    assert item_warnings(ent, _shield(), set()) == []
    assert CK.check(ent, _shield(), name="Stacking_Item") == []


def test_super_effects_do_not_scale_with_duplicate_count():
    """Super effects only activate when reaching target copies, so they must NOT
    scale their amount by Amount Selector."""
    from rsmm.cli.editor.content import _built_slots
    from rsmm.engine import entity_check as CK
    from rsmm.engine import entity_graph as EG
    from rsmm.engine import entity_parts as P
    _shield()
    supers = [
        {"stat": "Crit chance", "amount": 0.05},
        {"stat": "Attack power", "amount": 0.1, "seconds": 3.0, "on": "dash"},
    ]
    files = C.build_magic_item(new_id="Super_Item", base_id="Increase_Shield",
                               base_cooked=_shield(), corpus=[], rarity="Rare",
                               super_effects=supers)
    ent = next(b for p, b in files.items() if p.endswith(".gen"))
    g = EG.parse(ent)
    comps = {c.name: c for c in g.components}

    # Super effect components should NOT have Value Operation
    assert "Crit Chance Value Operation Super Effect" not in comps
    assert "Crit Chance Value Operation Super Effect 2" not in comps

    # Modifiers should not have an external operation source
    mod1 = comps["Crit Chance Modifier Super Effect"]
    d1 = P.decode(mod1)
    assert d1["amount"].source is None
    assert struct.unpack("<f", d1["amount"].value)[0] == pytest.approx(0.05)

    # Slots in Super Effect Descripton Format point directly to Values, not Operations
    super_slots = [(s["node"], s["mode"])
                   for s in _built_slots(ent, "Super Effect Descripton Format")]
    assert super_slots[0] == ("Crit Chance Value Super Effect", 1)
    assert super_slots[1] == ("Crit Chance Value Super Effect 2", 1)
    assert super_slots[2] == ("Crit Chance Duration Value Super Effect 2", 0)

    assert item_warnings(ent, _shield(), set()) == []
    assert CK.check(ent, _shield(), name="Super_Item") == []


def test_free_reroll_effect_encodes_as_integer_and_not_percent():
    """Free Reroll is an integer stat: amount must be encoded as P.INT (type 1),
    percent defaults to False so display mode is 0 (plain, not x100), and it
    does not scale through float operations."""
    from rsmm.cli.editor.content import _built_slots
    from rsmm.engine import entity_check as CK
    from rsmm.engine import entity_graph as EG
    from rsmm.engine import entity_parts as P
    from rsmm.engine.item_effect import Effect, describe

    # 1. Parsing defaults percent to False and amount to int
    e = Effect.parse({"stat": "Free Reroll", "amount": 1.0})
    assert e.amount == 1
    assert isinstance(e.amount, int)
    assert e.percent is False
    assert describe([e]) == "• #+{0}@ #Free Reroll@"

    # 2. Super effect encoding (as Lucky Coin provides natively)
    files = C.build_magic_item(new_id="Reroll_Super_Item", base_id="Increase_Shield",
                               base_cooked=_shield(), corpus=[], rarity="Common",
                               super_effects=[{"stat": "Free Reroll", "amount": 1}])
    ent = next(b for p, b in files.items() if p.endswith(".gen"))
    g = EG.parse(ent)
    comps = {c.name: c for c in g.components}
    mod = comps["Crit Chance Modifier Super Effect"]
    d = P.decode(mod)
    assert d["modifier_id"] == 0x1AA49D8D
    assert d["amount"].type == P.INT
    assert d["amount"].value == struct.pack("<i", 1)
    assert d["amount"].unit == 0
    assert d["amount"].source is None

    slots = [(s["node"], s["mode"])
             for s in _built_slots(ent, "Super Effect Descripton Format")]
    assert slots[0] == ("Crit Chance Value Super Effect", 0)

    assert item_warnings(ent, _shield(), set()) == []
    assert CK.check(ent, _shield(), name="Reroll_Super_Item") == []

    # 3. Always-on effect encoding scales by duplicate copies via integer operation
    files2 = C.build_magic_item(new_id="Reroll_Passive_Item", base_id="Increase_Shield",
                                base_cooked=_shield(), corpus=[], rarity="Common",
                                effect=[{"stat": "Free Reroll", "amount": 2}])
    ent2 = next(b for p, b in files2.items() if p.endswith(".gen"))
    g2 = EG.parse(ent2)
    comps2 = {c.name: c for c in g2.components}
    op2 = comps2["Crit Chance Value Operation Effect"]
    assert op2.cls == "oCEntityCpntValueOperationsSettings"
    mod2 = comps2["Crit Chance Modifier Effect"]
    d2 = P.decode(mod2)
    assert d2["modifier_id"] == 0x1AA49D8D
    assert d2["amount"].type == P.INT
    assert d2["amount"].value == struct.pack("<i", 2)
    op_path = r"[Multi values operations] Reroll_Passive_Item\Crit Chance Value Operation Effect"
    assert d2["amount"].source.path == op_path
    assert d2["amount"].key == 0x17AE780B

    slots2 = _slots(ent2)
    assert slots2[0] == ("Crit Chance Value Operation Effect", 0)
    built2 = _built_slots(ent2, "Descripton Format")
    assert built2[0]["value"] == 2.0
    assert built2[0]["mode"] == 0
    from rsmm.engine.entity_graph_edit import EntityFile
    ef2 = EntityFile(ent2, "Reroll_Passive_Item")
    c_fmt = ef2.component("Descripton Format")
    fmt_slot = ef2._format_slots(c_fmt)[0][0]
    assert struct.unpack("<I", c_fmt.body[fmt_slot.offset + 8:fmt_slot.offset + 12])[0] == 1

    assert item_warnings(ent2, _shield(), set()) == []
    assert CK.check(ent2, _shield(), name="Reroll_Passive_Item") == []
