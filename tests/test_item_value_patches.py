"""The manifest item path (build_magic_item / value_patches) must not silently
no-op on a shadowed value — it refuses, and clears the override when asked.

Runs against the real vanilla Damage_Power (its "Damage Value" is shadowed by a
card-count selector; "Power Crit Chance Value" is a normal inline value).
"""

from pathlib import Path

import pytest

from rsmm.engine.magic_item_cook import build_magic_item
from rsmm.engine.talent_values import is_label_overridden, list_talent_values

_VANILLA = (Path(__file__).resolve().parents[1] / "data" / "uncooked"
            / "EntitySettings" / "Objects" / "Magical_Objects" / "Rare"
            / "Damage_Power.entity.ot.EntitySettingsResource.gen")
_ENTITY_KEY = ("EntitySettings/Objects/Magical_Objects/Rare/"
               "Damage_Power.entity.ot.EntitySettingsResource.gen")


def _base() -> bytes:
    if not _VANILLA.is_file():
        pytest.skip("vanilla Damage_Power corpus file not present")
    return _VANILLA.read_bytes()


def _build(value_patches):
    files = build_magic_item(
        new_id="Damage_Power", base_id="Damage_Power", base_cooked=_base(),
        corpus=[], rarity="Rare", value_patches=value_patches)
    return files[_ENTITY_KEY]


def test_refuses_shadowed_patch():
    with pytest.raises(ValueError, match="shadowed"):
        _build([("Damage Value", 0.2, 0.5)])


def test_clear_override_flag_applies_inline_value():
    ent = _build([("Damage Value", 0.2, 0.5, True)])
    assert is_label_overridden(ent, "Damage Value") is False
    vals = {t.label: t.value for t in list_talent_values(ent)}
    assert vals["Damage Value"] == 0.5


def test_unshadowed_patch_unaffected():
    ent = _build([("Power Crit Chance Value", 0.4, 0.1)])
    vals = {t.label: t.value for t in list_talent_values(ent)}
    assert vals["Power Crit Chance Value"] == 0.1
