"""Tests for talent value discovery + patching.

The node shape these exercise is documented in :mod:`rsmm.engine.talent_values`:
a value is an ``oCEntityCpntValuePicker`` -> ``oCEntityValueUnion`` pair whose
classes are named by an index into *the file's own class table*, carrying an
explicit type code (0 f32 / 1 int32 / 2 bool; everything else is an asset
reference or string, not a number).

Three of these are regressions for defects found on 2026-09-12:

* the class index is per-file, so hardcoding the indices that happen to be
  right for one file made shadow detection inert everywhere else;
* an int32 node holding ``0`` is bit-identical to an f32 holding ``0.0``, so
  the type has to be read, not guessed;
* a label that merely looks like a value name is usually an entry in a name
  list with no value node at all, and writing to it corrupts a neighbour.
"""

import struct
from pathlib import Path

import pytest
from _cooked_fixtures import (
    PICKER_IDX,
    UNION_IDX,
    entity,
    lstr,
    name_list,
    selector_node,
    value_node,
)

from rsmm.engine.talent_values import (
    TYPE_BOOL,
    TYPE_F32,
    TYPE_INT32,
    clear_value_override,
    is_label_overridden,
    list_talent_values,
    list_union_values,
    set_talent_value,
    set_union_value,
)

#: An asset-reference union (``Weapon Material Value`` and friends) — a type
#: code we must refuse to read as a number.
_TYPE_RESOURCE = 9


def _sample(*, picker_idx: int = PICKER_IDX, union_idx: int = UNION_IDX) -> bytes:
    return entity(
        value_node("Crit Chance Value", 0.4,
                   picker_idx=picker_idx, union_idx=union_idx),
        value_node("Damage Value", 0.2, shadowed=True,
                   picker_idx=picker_idx, union_idx=union_idx),
        picker_idx=picker_idx, union_idx=union_idx,
    )


# --------------------------------------------------------------------------
# shadowed values
# --------------------------------------------------------------------------

def test_detects_shadowed_value():
    vals = {v.label: v for v in list_talent_values(_sample())}
    assert vals["Crit Chance Value"].is_overridden is False
    assert vals["Damage Value"].is_overridden is True
    # the shadowed node's inline float is still *read* (for display), just dead
    assert vals["Damage Value"].value == pytest.approx(0.2)
    assert is_label_overridden(_sample(), "Damage Value") is True


def test_set_refuses_shadowed_value():
    raw = _sample()
    out = set_talent_value(raw, "Crit Chance Value", 0.1)
    assert {v.label: v.value
            for v in list_talent_values(out)}["Crit Chance Value"] == pytest.approx(0.1)
    with pytest.raises(ValueError, match="shadowed"):
        set_talent_value(raw, "Damage Value", 0.5)
    forced = set_talent_value(raw, "Damage Value", 0.5, allow_shadowed=True)
    assert len(forced) == len(raw)


@pytest.mark.parametrize("picker_idx,union_idx",
                         [(0x0E, 0x0F), (0x44, 0x45), (0x3F, 0x40)])
def test_class_index_is_per_file(picker_idx, union_idx):
    """The picker/union are identified by class NAME, so a file that happens to
    put them at different table indices reads identically.

    Regression: the indices 0x0e/0x0f were hardcoded from one magical-object
    file. In every hero entity 0x0e is ``oCEntityCpntTimerSettings``, so shadow
    detection silently never fired on a talent.
    """
    vals = {v.label: v
            for v in list_talent_values(_sample(picker_idx=picker_idx,
                                                union_idx=union_idx))}
    assert vals["Crit Chance Value"].value == pytest.approx(0.4)
    assert vals["Damage Value"].is_overridden is True


# --------------------------------------------------------------------------
# union type codes
# --------------------------------------------------------------------------

def test_int32_zero_is_not_mistaken_for_a_float():
    """An int32 holding 0 is bit-identical to an f32 holding 0.0, so the type
    must come from the union's type code, not from the bit pattern.

    Regression: writing an f32 into an int32 slot turned a requested ``3`` into
    ``1077936128`` in game.
    """
    raw = entity(value_node("Created Count", 0, type_code=TYPE_INT32))
    tv = {v.label: v for v in list_talent_values(raw)}["Created Count"]
    assert tv.is_int is True and tv.type_code == TYPE_INT32 and tv.value == 0

    out = set_talent_value(raw, "Created Count", 3)
    assert len(out) == len(raw)
    assert {v.label: v.value for v in list_talent_values(out)}["Created Count"] == 3
    # the bytes are a real int32, not an f32 that merely prints as 3
    off = tv.offset
    assert struct.unpack_from("<i", out, off)[0] == 3


def test_bool_value_round_trips():
    raw = entity(value_node("Skill Swirling Value", 1, type_code=TYPE_BOOL))
    tv = {v.label: v for v in list_talent_values(raw)}["Skill Swirling Value"]
    assert tv.type_code == TYPE_BOOL and tv.value == 1
    out = set_talent_value(raw, "Skill Swirling Value", 0)
    assert len(out) == len(raw)
    assert {v.label: v.value
            for v in list_talent_values(out)}["Skill Swirling Value"] == 0


def test_asset_reference_is_not_a_number():
    """A type-9 union holds a resource path. It must not surface as a magnitude
    (301 of them do in the shipped hero corpus)."""
    raw = entity(value_node("Weapon Material Value", 0,
                            type_code=_TYPE_RESOURCE))
    assert [v.label for v in list_talent_values(raw)] == []
    with pytest.raises(ValueError, match="not found"):
        set_talent_value(raw, "Weapon Material Value", 1.0)


# --------------------------------------------------------------------------
# labels that are not value nodes
# --------------------------------------------------------------------------

def test_bare_label_is_not_reported_as_a_value():
    """Most strings matching the value-name shape are entries in a name list
    with no value node behind them. Reporting them as ``0.0`` invited a write
    that landed on an unrelated node's field."""
    raw = entity(
        name_list("Red_ImpactCount", "Distance"),
        value_node("Real Radius", 4.0),
    )
    labels = [v.label for v in list_talent_values(raw)]
    assert labels == ["Real Radius"]
    for phantom in ("Red_ImpactCount", "Distance"):
        with pytest.raises(ValueError, match="not found"):
            set_talent_value(raw, phantom, 3.0)


def test_scope_string_does_not_claim_its_node_twice():
    """A node is ``<own name> <header> <scope name> <header> picker union``, and
    a scope name can itself look like a value name. Both resolve to the same
    field, so the first (the node's own name) keeps it — 'Skill Power Range' is
    the shipped case, riding on 'Skill Power Range Move Speed Increase Ratio'."""
    raw = entity(value_node("Skill Power Range Move Speed Increase Ratio", 0.25,
                            prefix=lstr("Skill Power Range") + b"\x00" * 4))
    vals = list_talent_values(raw)
    assert [v.label for v in vals] == ["Skill Power Range Move Speed Increase Ratio"]
    assert vals[0].value == pytest.approx(0.25)


def test_unparseable_container_yields_nothing():
    """Without a class table no node can be identified, so fail closed."""
    assert list_talent_values(b"not a cooked file at all") == []
    assert is_label_overridden(b"not a cooked file at all", "Whatever") is False


# --------------------------------------------------------------------------
# shipped corpus
# --------------------------------------------------------------------------

#: Real vanilla item whose "Damage Value" node is shadowed by the card-count
#: selector — the case that motivated the shadow guard.
_VANILLA = (Path(__file__).resolve().parents[1] / "data" / "uncooked"
            / "EntitySettings" / "Objects" / "Magical_Objects" / "Rare"
            / "Damage_Power.entity.ot.EntitySettingsResource.gen")

_HEROES = (Path(__file__).resolve().parents[1] / "data" / "uncooked"
           / "EntitySettings" / "Heroes")


def test_clear_override_then_set_takes_effect():
    if not _VANILLA.is_file():
        pytest.skip("vanilla Damage_Power corpus file not present")
    raw = _VANILLA.read_bytes()
    before = {v.label: v for v in list_talent_values(raw)}
    assert before["Damage Value"].is_overridden is True

    cleared = clear_value_override(raw, "Damage Value")
    dmg = {v.label: v for v in list_talent_values(cleared)}["Damage Value"]
    assert dmg.is_overridden is False
    assert len(cleared) < len(raw)

    with pytest.raises(ValueError, match="shadowed"):
        set_talent_value(raw, "Damage Value", 0.5)
    out = set_talent_value(cleared, "Damage Value", 0.5)
    assert {v.label: v.value
            for v in list_talent_values(out)}["Damage Value"] == pytest.approx(0.5)

    with pytest.raises(ValueError, match="not overridden"):
        clear_value_override(cleared, "Damage Value")


def test_shipped_hero_values_all_resolve_to_a_typed_node():
    """Every value the CLI offers for editing must be backed by a real numeric
    union, and patching it must be length-preserving."""
    if not _HEROES.is_dir():
        pytest.skip("hero corpus not present")
    checked = 0
    for gen in sorted(_HEROES.glob("Hero_*/*.entity.ot.EntitySettingsResource.gen")):
        raw = gen.read_bytes()
        for v in list_talent_values(raw):
            assert v.type_code in (TYPE_F32, TYPE_INT32, TYPE_BOOL)
            if v.is_overridden:
                continue
            out = set_talent_value(raw, v.label, v.value, expect=v.value)
            assert len(out) == len(raw)
            checked += 1
    assert checked > 500, f"only {checked} hero talent values resolved"


# --------------------------------------------------------------------------
# value selectors — several unions in one node
# --------------------------------------------------------------------------

def test_union_walk_is_bounded_by_the_node():
    """A selector holds one union per rarity tier. The walk has to stop at the
    END that closes the node; a byte-window bound runs into the NEXT selector
    and every index after that silently means something else."""
    raw = entity(
        selector_node("Damage Multiplier Selector", [0.7, 0.6, 0.5, 0.4]),
        selector_node("Other Selector", [9.1, 9.2]),
    )
    got = list_union_values(raw, "Damage Multiplier Selector")
    # one enabled-bool + one f32 per tier, and nothing from the sibling node
    assert [round(v, 3) for _o, v, t in got if t == TYPE_F32] == [0.7, 0.6, 0.5, 0.4]
    assert len(got) == 8
    other = list_union_values(raw, "Other Selector")
    assert [round(v, 3) for _o, v, t in other if t == TYPE_F32] == [9.1, 9.2]


def test_set_union_value_patches_one_tier():
    raw = entity(selector_node("Damage Multiplier Selector", [0.7, 0.6, 0.5, 0.4]))
    out = set_union_value(raw, "Damage Multiplier Selector", 1, 0.6, expect=0.7)
    assert len(out) == len(raw)
    assert [round(v, 3) for _o, v, t in
            list_union_values(out, "Damage Multiplier Selector")
            if t == TYPE_F32] == [0.6, 0.6, 0.5, 0.4]


def test_set_union_value_guards_index_and_old_value():
    raw = entity(selector_node("Damage Multiplier Selector", [0.7, 0.6]))
    with pytest.raises(ValueError, match="out of range"):
        set_union_value(raw, "Damage Multiplier Selector", 99, 0.6)
    with pytest.raises(ValueError, match="expected"):
        set_union_value(raw, "Damage Multiplier Selector", 1, 0.6, expect=0.4)
    with pytest.raises(ValueError, match="not found"):
        set_union_value(raw, "No Such Selector", 0, 1.0)
