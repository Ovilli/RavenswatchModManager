"""Text-key resolution for the `skill` kind.

A hero's herodef rows are named after the INPUT SLOT while its text keys are
named after the ABILITY, and only some heroes differ:

    Aladdin   Skill Controller Attack Dive      -> Skill_Attack_Dive_Name
    Red       Skill Controller Primary Bleed    -> Skill_Power_Bleed_Name

Assuming the row name IS the key worked until a hero using the second
convention was touched, where it asked the bank for `Skill_Primary_Bleed_Name`
and was told the hero has no such skill.
"""

import pytest

from rsmm.sdk.content import ContentError
from rsmm.sdk.kinds.skills import _key_base_candidates, _text_key_base


def test_ability_named_row_needs_no_alias():
    assert _key_base_candidates("Attack Dive")[0] == "Skill_Attack_Dive"
    assert _text_key_base("Attack Dive", ["Skill_Attack_Dive_Name"]) == "Skill_Attack_Dive"


@pytest.mark.parametrize("source,key", [
    ("Primary Finisher", "Skill_Power_Finisher"),
    ("Secondary Quick Bombs", "Skill_Special_Quick_Bombs"),
    ("Basic Cleave", "Skill_Attack_Cleave"),
    ("Defensive Mark", "Skill_Defense_Mark"),
])
def test_slot_named_row_maps_to_the_ability_key(source, key):
    assert _text_key_base(source, [f"{key}_Name"]) == key


def test_prefixes_without_an_alias_are_left_alone():
    for source, key in [("Passive Combo Chain", "Skill_Passive_Combo_Chain"),
                        ("Dash Attack", "Skill_Dash_Attack"),
                        ("Trait Active", "Skill_Trait_Active")]:
        assert _text_key_base(source, [f"{key}_Name"]) == key


def test_already_qualified_key_passes_through():
    assert _text_key_base("Skill_Power_Bleed", ["Skill_Power_Bleed_Name"]) == "Skill_Power_Bleed"
    assert _text_key_base("Skill Controller Attack Dive",
                          ["Skill_Attack_Dive_Name"]) == "Skill_Attack_Dive"


def test_unknown_key_names_what_it_looked_for():
    """A wrong controller name must not silently pick a candidate the bank does
    not have — the write would land on nothing."""
    with pytest.raises(ContentError) as e:
        _text_key_base("Primary Nonexistent", ["Skill_Power_Bleed_Name"])
    msg = str(e.value)
    assert "Skill_Primary_Nonexistent_Name" in msg
    assert "Skill_Power_Nonexistent_Name" in msg


def test_without_a_bank_it_still_guesses():
    """`bank_keys=None` keeps the old best-guess behaviour for callers that have
    no bank to check against."""
    assert _text_key_base("Primary Finisher") == "Skill_Primary_Finisher"
