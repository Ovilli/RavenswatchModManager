"""Every number an item's effects use is reachable: in the editor beside the
stat it sets, and through ``value_patches`` by part.

The label scanner behind ``list_value_fields`` sees none of Dreamcatcher's or
Goldilocks' Porridge's numbers ("Price Reduction", "Shield Gain", "Super Effect
Damage Gain" do not look like value labels to it), and a modifier holding its
own amount (Dreamcatcher's super effect: one free purchase) had no label at all.
"""

from __future__ import annotations

import pytest

from rsmm.cli.cmd_items import _find_item
from rsmm.engine import entity_fields as EF
from rsmm.engine import entity_graph as EG
from rsmm.engine import item_modifier as IM
from rsmm.engine import magic_item_cook as cook

pytestmark = pytest.mark.skipif(_find_item("Reduce_All_DS_Price") is None,
                                reason="no item corpus")


def _raw(item: str) -> bytes:
    return _find_item(item)[2].read_bytes()


def _text(raw: bytes, part: str, field: str) -> str:
    c = next(c for c in EG.parse(raw, "x").components if c.name == part)
    return next(f.text for f in EF.fields(c) if f.name == field)


def test_a_number_part_and_a_modifiers_own_amount_are_patched_by_part():
    raw = _raw("Reduce_All_DS_Price")
    assert cook.part_literal(raw, "Price Reduction") == pytest.approx(0.1)
    out = cook.apply_value_patch(raw, "Price Reduction", 0.1, 0.5)
    out = cook.apply_value_patch(out, "Super Effect Modifier.amount", 1.0, 3.0)
    assert _text(out, "Price Reduction", "value") == "f32 0.5"
    assert _text(out, "Super Effect Modifier", "amount") == "f32 3"


def test_a_patch_written_against_another_value_is_refused():
    with pytest.raises(ValueError, match="holds 0.5, not 0.7"):
        cook.apply_value_patch(_raw("Gain_Shield_From_Orbs"), "Shield Gain", 0.7, 2.0)


def test_a_label_the_scanner_knows_still_takes_the_label_path():
    out = cook.apply_value_patch(_raw("Armor_Per_Object"), "Armor per Object Value", 2.0, 5.0)
    assert _text(out, "Armor per Object Value", "value") == "f32 5"


def test_a_modifier_named_super_effect_is_one():
    # Dreamcatcher's hangs off a state the super-effect state turns on.
    mods = {m.name: m.super_effect for m in IM.list_modifiers(_raw("Reduce_All_DS_Price"))}
    assert mods == {"Modifier": False, "Super Effect Modifier": True}


def test_the_editor_puts_each_modifiers_number_beside_it():
    from rsmm.cli.editor import content as C
    d = C.item_detail("Reduce_All_DS_Price")
    amount = {m["name"]: m["amount"] for m in d["modifiers"]}
    # Through a math part whose steps live in sub-objects.
    assert amount["Modifier"] == {"label": "Price Reduction", "via": "Scalable Value Operation"}
    assert amount["Super Effect Modifier"] == {"label": "Super Effect Modifier.amount"}
    assert {"Price Reduction", "Super Effect Modifier.amount"} <= {v["label"] for v in d["values"]}
    # The card's {0} reads the same number, so the preview can fill it in.
    assert d["card"]["description"]["entries"][0]["sources"] == ["Price Reduction"]
    g = C.item_detail("Gain_Shield_From_Orbs")
    assert {m["name"]: m["amount"]["label"] for m in g["modifiers"]} == {
        "Shield On Heal Globe Modifier": "Shield Gain",
        "Super Effect Modifier": "Super Effect Damage Gain"}


def test_every_shipped_item_opens_in_the_editor():
    from rsmm.cli.editor import content as C
    for it in C.items():
        C.item_detail(it["id"])
