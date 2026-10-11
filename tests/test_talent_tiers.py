"""A talent card's per-rarity numbers, its placeholders, and its effect stats.

Needs the shipped heroes (mirror or install) except where noted.
"""

from __future__ import annotations

import pytest

from rsmm.engine import corpus
from rsmm.engine import item_modifier as IM
from rsmm.engine import talent_values as TV

_ALADDIN = "EntitySettings/Heroes/Hero_Aladdin/Hero_Aladdin.entity.ot.EntitySettingsResource.gen"
_DIVE = "Skill Attack Dive Damage Multiplier Selector"


def _aladdin() -> bytes:
    data = corpus.read(_ALADDIN)
    if data is None:
        pytest.skip("shipped heroes not available (no mirror, no install)")
    return data


def test_a_tier_selector_reads_one_number_per_rarity():
    """Three entries keyed to the controller's Rare/Epic/Legendary flags, then
    the default a Common card reads."""
    tiers = TV.tier_values(_aladdin(), _DIVE)
    assert {t: v for t, (_i, v, _tc) in tiers.items()} == {
        "Common": 4.0, "Rare": 5.0, "Epic": 6.0, "Legendary": 7.0}


def test_a_tier_index_is_the_one_union_patches_writes():
    data = _aladdin()
    index, value, _tc = TV.tier_values(data, _DIVE)["Legendary"]
    out = TV.set_union_value(data, _DIVE, index, 9.0, expect=value)
    assert TV.tier_values(out, _DIVE)["Legendary"][1] == 9.0
    assert TV.tier_values(out, _DIVE)["Epic"][1] == 6.0


def test_a_node_that_is_not_a_tier_selector_has_no_tiers():
    assert TV.tier_values(_aladdin(), "No Such Node") == {}


def test_a_talent_text_is_found_by_its_key():
    formats = IM.formats_by_key(_aladdin(), "Hero_Aladdin_Common~GAM.xls")
    dive = formats["Skill_Attack_Dive_Desc"]
    assert dive.entries[0] is None                       # the hero's name, inline
    assert dive.entries[1].node == _DIVE


def test_the_talent_kind_changes_an_effects_stat(tmp_path):
    from rsmm.sdk.content import ContentRegistry
    data = _aladdin()
    mod = IM.list_modifiers(data)[0]
    cr = ContentRegistry(mod_id="StatMod")
    cr.register("talent", id="aladdin_stat", hero="Aladdin", file="Hero_Aladdin.entity",
                stats={mod.name: "Armour"})
    [out] = cr.emit(tmp_path / "assets")
    changed = {m.name: m.stat for m in IM.list_modifiers(out.read_bytes())}
    assert changed[mod.name] == "Armour"
    assert len(out.read_bytes()) == len(data)


def test_talent_stats_need_one_file(tmp_path):
    from rsmm.sdk.content import ContentError, ContentRegistry
    _aladdin()
    cr = ContentRegistry(mod_id="StatMod")
    cr.register("talent", id="aladdin_stat", hero="Aladdin", stats={"X": "Armour"})
    with pytest.raises(ContentError, match="exactly one"):
        cr.emit(tmp_path / "assets")


def test_every_talent_card_finds_the_icon_it_draws():
    """The editor shows, and the skill kind's `icon` overwrites, the texture
    named after the card's controller. Guessing `Skill <source>.png` missed 33
    cards, and Sun Wukong's folder spelling (`Hero_SunWukong` for herodef
    `Sun_Wukong`) hid all 21 of his."""
    from rsmm.cli.editor import content as E
    _aladdin()
    missing = [(h, c["source"]) for h in E.heroes() for c in E.talent_cards(h)
               if not c["icon"]]
    assert missing == []


def test_no_talent_controller_is_dropped_unexplained():
    """A controller that yields no card is listed with a reason. One that names
    a card the text bank lacks is a bug (before the card key was read from the
    controller, Aladdin's `Ultimate 1 Upgrade 1` and 60-odd other cards vanished
    without a trace)."""
    from rsmm.cli.editor import content as E
    _aladdin()
    for h in E.heroes():
        assert [x for x in E.talent_skipped(h) if x["problem"]] == [], h
        assert all(x["reason"] for x in E.talent_skipped(h)), h


def test_a_row_finds_its_card_through_a_string_format_link():
    """`Ultimate Power 1` is the base ultimate: its name and description sit in
    linked String Format parts, so no key is written on the row itself."""
    from rsmm.cli.editor import content as E
    from rsmm.sdk.kinds import skills as S
    _aladdin()
    own = S.controller_key_bases(E._herodefs()["Aladdin"])
    assert "Skill_Ultimate_1" in own["Ultimate Power 1"]
    assert "Skill_Ultimate_1_Better_Wish" in own["Ultimate 1 Upgrade 1"]


def test_a_hero_is_named_with_or_without_underscores():
    from rsmm.sdk.kinds import skills as S
    _aladdin()
    assert S._hero_token("SunWukong") == S._hero_token("Sun_Wukong") == "Sun_Wukong"
    assert S._slot_icon_texture("Sun_Wukong", "Attack Beam").startswith("Ui/Heroes/")
