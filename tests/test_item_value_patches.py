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


# --- typed writes ------------------------------------------------------------
# A value node declares its type: f32, int32, or a ONE-byte bool ("Unique
# Value", "Sell By Sandman Value"). The writer used to put an f32 on every
# node, so turning a bool off overran three bytes into the node's closing
# marker and the entity no longer parsed — on all 41 bool nodes the item
# editor offered as plain numbers.

def _typed_nodes(type_code):
    from rsmm.engine import corpus
    from rsmm.engine import magic_items as MI
    out = []
    for item in MI.list_ids():
        raw = corpus.read(MI.get(item).entity_decoded_path)
        if raw is None:
            continue
        out += [(item, raw, tv) for tv in list_talent_values(raw)
                if tv.type_code == type_code]
    if not out:
        pytest.skip("no item corpus")
    return out


def test_flipping_a_bool_value_writes_one_byte_and_still_parses():
    from rsmm.engine import cooked
    from rsmm.engine.magic_item_cook import apply_value_patch
    from rsmm.engine.talent_values import TYPE_BOOL
    for item, raw, tv in _typed_nodes(TYPE_BOOL):
        out = apply_value_patch(raw, tv.label, tv.value, 1.0 - tv.value)
        changed = [i for i in range(len(raw)) if raw[i] != out[i]]
        assert changed == [tv.offset], (item, tv.label)
        cooked.parse(out)
        now = {t.label: t.value for t in list_talent_values(out)}
        assert now[tv.label] == 1.0 - tv.value, (item, tv.label)


def test_a_bool_value_takes_only_zero_or_one():
    from rsmm.engine.magic_item_cook import apply_value_patch
    from rsmm.engine.talent_values import TYPE_BOOL
    _item, raw, tv = _typed_nodes(TYPE_BOOL)[0]
    with pytest.raises(ValueError, match="on/off value"):
        apply_value_patch(raw, tv.label, tv.value, 3.0)


def test_the_typed_packer_matches_each_node_width():
    from rsmm.engine.magic_item_cook import _pack_typed
    from rsmm.engine.talent_values import TYPE_BOOL, TYPE_F32, TYPE_INT32
    assert _pack_typed("x", TYPE_BOOL, 1.0) == b"\x01"
    assert _pack_typed("x", TYPE_BOOL, 0.0) == b"\x00"
    assert _pack_typed("x", TYPE_INT32, 5.0) == b"\x05\x00\x00\x00"
    assert _pack_typed("x", TYPE_F32, 1.0) == b"\x00\x00\x80\x3f"
    with pytest.raises(ValueError, match="whole number"):
        _pack_typed("x", TYPE_INT32, 2.5)
