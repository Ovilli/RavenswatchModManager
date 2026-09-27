"""Which stat an item's effects give, and its super-effect text.

The stat is a 4-byte key inside each modifier record; changing it must touch
those 4 bytes and nothing else. Needs the shipped items (mirror or install)
for everything but the catalog lookups.
"""

from __future__ import annotations

import pytest

from rsmm.engine import corpus
from rsmm.engine import item_modifier as IM
from rsmm.engine import magic_item_cook as C

_MO = "EntitySettings/Objects/Magical_Objects"
_SUFFIX = ".entity.ot.EntitySettingsResource.gen"


def _item(rarity: str, item_id: str) -> bytes:
    data = corpus.read(f"{_MO}/{rarity}/{item_id}{_SUFFIX}")
    if data is None:
        pytest.skip("shipped items not available (no mirror, no install)")
    return data


# --- the catalog ---------------------------------------------------------------

def test_a_stat_resolves_by_name_any_case_or_by_key():
    assert IM.resolve_stat("Crit chance") == IM.resolve_stat("CRIT CHANCE")
    assert IM.resolve_stat("0x15c7d482") == 0x15C7D482
    assert IM.resolve_stat(0x15C7D482) == 0x15C7D482


def test_armour_keeps_its_zero_key():
    """The Lua table drops key 0; items store exactly 0 for armour."""
    assert IM.resolve_stat("Armour") == 0
    assert IM.stat_name(0) == "Armour"


@pytest.mark.parametrize("bad", ["Crit chanse", "0xnope", "0x1ffffffff", True, -1])
def test_an_unknown_stat_is_refused(bad):
    with pytest.raises(IM.ItemModifierError):
        IM.resolve_stat(bad)


# --- reading and writing an item -----------------------------------------------------

def test_an_items_effects_and_super_effect_are_listed():
    mods = IM.list_modifiers(_item("Common", "Damage_Per_Vitality"))
    assert [(m.name, m.stat, m.super_effect) for m in mods] == [
        ("Damage Modifier", "Attack power", False),
        ("Super Effect Modifier", "Crit chance", True),
    ]


def test_changing_a_stat_touches_only_its_four_bytes():
    data = _item("Common", "Damage_Per_Vitality")
    out = IM.set_modifier_stat(data, "Super Effect Modifier", "Crit damage")
    assert len(out) == len(data)
    assert sum(a != b for a, b in zip(data, out, strict=True)) <= 4
    stats = {m.name: m.stat for m in IM.list_modifiers(out)}
    assert stats == {"Damage Modifier": "Attack power", "Super Effect Modifier": "Crit damage"}


def test_a_missing_modifier_names_the_ones_there_are():
    with pytest.raises(IM.ItemModifierError, match="'Damage Modifier'"):
        IM.set_modifier_stat(_item("Common", "Damage_Per_Vitality"), "Nope", "Armour")


def test_the_super_text_key_is_found_and_repointed():
    data = _item("Common", "Damage_Per_Vitality")
    assert IM.super_text_key(data) == "Crit_Chance_SuperEffect"
    out = IM.set_super_text_key(data, "Zz_Own_Item_SuperEffect")
    assert IM.super_text_key(out) == "Zz_Own_Item_SuperEffect"
    assert b"Crit_Chance_SuperEffect" not in out


def test_an_item_without_super_text_says_so():
    data = _item("Powerups", "Power_Up_Damage")
    assert IM.super_text_key(data) is None
    with pytest.raises(IM.ItemModifierError):
        IM.set_super_text_key(data, "X_SuperEffect")


def test_every_shipped_modifier_can_be_retargeted():
    files = corpus.files(f"{_MO}/Common", _SUFFIX)
    if not files:
        pytest.skip("shipped items not available (no mirror, no install)")
    for rarity in ("Common", "Rare", "Epic", "Legendary", "Cursed", "Powerups"):
        for f in corpus.files(f"{_MO}/{rarity}", _SUFFIX):
            data = f.read_bytes()
            for m in IM.list_modifiers(data):
                out = IM.set_modifier_stat(data, m.name, "Vitality")
                assert len(out) == len(data), (f, m.name)


# --- the item copy -------------------------------------------------------------------

def _copy(base_rarity: str, base_id: str, new_id: str, **kw) -> bytes:
    files = C.build_magic_item(new_id=new_id, base_id=base_id,
                               base_cooked=_item(base_rarity, base_id), corpus=[],
                               rarity=base_rarity, **kw)
    [ent] = [b for p, b in files.items() if p.endswith(_SUFFIX)]
    return ent


def test_a_copy_gets_its_new_stats():
    ent = _copy("Common", "Damage_Per_Vitality", "Damage_Per_Vitality2",
                modifier_stats={"Super Effect Modifier": "Armour"})
    assert {m.name: m.stat for m in IM.list_modifiers(ent)}["Super Effect Modifier"] == "Armour"


def test_a_copy_keeps_the_bases_super_text_when_it_has_none_of_its_own():
    """`Defense_To_Damage_SuperEffect` embeds the base id; the id rename used to
    turn it into a key no bank holds, so the copy showed blank text."""
    ent = _copy("Common", "Defense_To_Damage", "Defense_To_Damag2")
    assert IM.super_text_key(ent) == "Defense_To_Damage_SuperEffect"


def test_a_copy_with_super_text_reads_its_own_key():
    ent = _copy("Common", "Defense_To_Damage", "Defense_To_Damag2",
                super_description="Gain armour.")
    assert IM.super_text_key(ent) == "Defense_To_Damag2_SuperEffect"


def test_super_text_on_an_item_without_a_super_effect_is_refused():
    with pytest.raises(ValueError, match="no super effect text"):
        _copy("Powerups", "Power_Up_Damage", "Power_Up_Damag2", super_description="x")
