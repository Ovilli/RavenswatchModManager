"""Tests for shadowed-value detection — the guard against silently patching a
value node whose inline float is overridden by a selector/reference (the
Damage_Power "Damage Value" bug).

Builds a synthetic cooked entity with two value nodes that mirror the real
on-disk shapes: one with its ``0e`` override sub-field disabled (``00`` — the
inline float is authoritative, like every working crit/talent node) and one
with it enabled (``01 + ref`` — the inline float is dead, like Damage_Power's
card-count Damage Value).
"""

import struct
from pathlib import Path

import pytest

from rsmm.engine import cooked
from rsmm.engine.talent_values import (
    clear_value_override,
    list_talent_values,
    set_talent_value,
)


def _lstr(s: str) -> bytes:
    b = s.encode("ascii")
    return struct.pack("<I", len(b)) + b


# node header + a 0f value section carrying `val`, with the `0e` sub-section
# either disabled (`00`) or enabled (`01 01 0f7c1b7c`) — copied from real files.
_HDR = bytes.fromhex("010100000000000000000100000000")
_OE_OFF = bytes.fromhex("1111bbaa0e00000000")                 # disabled
_OE_ON = bytes.fromhex("1111bbaa0e00000001010f7c1b7c")        # enabled + ref
_VAL_HDR = bytes.fromhex("1111bbaa0f0000000000000002000000")
_END = b"\x22\x22\xbb\xaa"


def _node(label: str, val: float, *, overridden: bool) -> bytes:
    oe = _OE_ON if overridden else _OE_OFF
    return _lstr(label) + _HDR + oe + _VAL_HDR + struct.pack("<f", val) + _END


def _sample() -> bytes:
    payload = (_node("Crit Chance Value", 0.4, overridden=False)
               + _node("Damage Value", 0.2, overridden=True))
    cf = cooked.CookedFile(
        variant="A", hdr_a=0x10, flags=1, extra=0, type_tag=0x31,
        classes=[cooked.ClassDef("oCEntitySettingsResource", 0x16f5f7a3, 1, 0, 0)],
        sections=[cooked.Section(payload=payload)],
    )
    return cooked.emit(cf)


def test_detects_shadowed_value():
    vals = {v.label: v for v in list_talent_values(_sample())}
    assert vals["Crit Chance Value"].is_overridden is False
    assert vals["Damage Value"].is_overridden is True
    # the shadowed node's inline float is still *read* (for display), just dead
    assert vals["Damage Value"].value == 0.2


def test_set_refuses_shadowed_value():
    raw = _sample()
    # the unshadowed node patches fine
    out = set_talent_value(raw, "Crit Chance Value", 0.1)
    assert {v.label: v.value for v in list_talent_values(out)}["Crit Chance Value"] == 0.1
    # the shadowed node is refused with a pointed message
    with pytest.raises(ValueError, match="shadowed"):
        set_talent_value(raw, "Damage Value", 0.5)
    # ...unless forced
    forced = set_talent_value(raw, "Damage Value", 0.5, allow_shadowed=True)
    assert len(forced) == len(raw)


#: Real vanilla item whose "Damage Value" node is shadowed by the card-count
#: selector — the case that motivated all of this. clear_value_override has to
#: round-trip through cooked.parse, which needs a genuinely valid container, so
#: this leg runs against the shipped corpus file (skipped if it's absent).
_VANILLA = (Path(__file__).resolve().parents[1] / "data" / "uncooked"
            / "EntitySettings" / "Objects" / "Magical_Objects" / "Rare"
            / "Damage_Power.entity.ot.EntitySettingsResource.gen")


def test_clear_override_then_set_takes_effect():
    if not _VANILLA.is_file():
        pytest.skip("vanilla Damage_Power corpus file not present")
    raw = _VANILLA.read_bytes()
    before = {v.label: v for v in list_talent_values(raw)}
    assert before["Damage Value"].is_overridden is True

    cleared = clear_value_override(raw, "Damage Value")
    # node is no longer shadowed and the file shrank by the dropped ref bytes
    dmg = {v.label: v for v in list_talent_values(cleared)}["Damage Value"]
    assert dmg.is_overridden is False
    assert len(cleared) < len(raw)

    # the inline edit was refused before, and applies after clearing
    with pytest.raises(ValueError, match="shadowed"):
        set_talent_value(raw, "Damage Value", 0.5)
    out = set_talent_value(cleared, "Damage Value", 0.5)
    assert {v.label: v.value for v in list_talent_values(out)}["Damage Value"] == 0.5

    # clearing an already-unshadowed node is an error (nothing to do)
    with pytest.raises(ValueError, match="not overridden"):
        clear_value_override(cleared, "Damage Value")
