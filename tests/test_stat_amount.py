"""Stat bonus numbers that say what they do (engine/stat_amount.py): a value
is ADDED to the stat; text like "+40%" / "-60%" / "+10" reads one way only, and
a multiplier is refused with the value to write instead."""

from __future__ import annotations

import pytest

from rsmm.engine import stat_amount as SA


@pytest.mark.parametrize("text,want", [
    ("+40%", 0.4), ("40%", 0.4), ("-60%", -0.6), (" - 12.5 % ", -0.125),
    ("+10", 10.0), ("-5", -5.0), ("3", 3.0), (0.25, 0.25), (7, 7.0),
])
def test_a_value_reads_one_way(text, want):
    assert SA.parse(text) == pytest.approx(want)


@pytest.mark.parametrize("text,equivalent", [("x0.4", "-60%"), ("×1.5", "+50%"),
                                             ("*0.5", "-50%"), ("0.4x", "-60%")])
def test_a_multiplier_is_refused_with_what_to_write(text, equivalent):
    with pytest.raises(SA.AmountError, match="ADD") as e:
        SA.parse(text)
    assert repr(equivalent) in str(e.value)


@pytest.mark.parametrize("bad", ["forty", "40%%", True, None, float("nan"), [1]])
def test_anything_else_is_refused(bad):
    with pytest.raises(SA.AmountError):
        SA.parse(bad)


def test_the_read_back_says_what_each_rarity_does():
    line = SA.describe("Attack power", {"Common": 0.4, "Rare": 0.43, "Epic": 0.46,
                                        "Legendary": 0.5}, True)
    assert "+40% / +43% / +46% / +50%" in line and "added to the hero's Attack power" in line
    assert "at every rarity" in SA.describe("Armour", dict.fromkeys("ABCD", 10.0), False)
    assert "LESS" in SA.describe("CD reduce trait", dict.fromkeys("ABCD", 0.25), True)
    assert "penalty" in SA.describe("Attack power", dict.fromkeys("ABCD", -0.6), True)


def test_talent_values_take_the_same_text():
    from rsmm.engine import talent_add_stat as TA
    assert TA.normalise_values(["+40%", "+43%", 0.46, "+50%"]) == pytest.approx(
        {"Common": 0.4, "Rare": 0.43, "Epic": 0.46, "Legendary": 0.5})
    assert TA.normalise_values("-60%") == pytest.approx(dict.fromkeys(TA.TIERS, -0.6))
    assert TA.normalise_values({"common": "+10", "rare": 12, "epic": "+14", "legendary": 16})
    with pytest.raises(TA.AddStatError, match="multiplier"):
        TA.normalise_values(["x0.4", "x0.43", "x0.46", "x0.5"])


def test_item_amounts_take_the_same_text():
    from rsmm.engine import item_effect as IE
    assert IE.Effect.parse({"stat": "Crit chance", "amount": "+10%"}).amount == pytest.approx(0.1)
    with pytest.raises(IE.ItemEffectError, match="multiplier"):
        IE.Effect.parse({"stat": "Crit chance", "amount": "x1.1"})
