"""`kind = "stat"` patches against the shipped global-value corpus.

`oCGlobalEntityValueSettings` is a tagged union and the patcher used to treat
it as a fixed float layout. That was wrong twice over: the 57 bool globals were
silently dropped for having the "wrong" body size (so `Start_Revealed_Map`
could not be patched at all), and the 83 int globals passed the size check and
had a float written into them. These pin both halves.

The mirrored `data/uncooked/**.gen` files ARE the cooked bytes, so `patch_field`
can be exercised without a game install.
"""

from __future__ import annotations

import struct

import pytest

from rsmm.engine.paths import DATA_DIR
from rsmm.engine.stat_schemas import MARK_BEGIN, MARK_END, SCHEMAS, patch_field

_GLOBALS = DATA_DIR / "uncooked" / "GlobalValues" / "GlobalValues_Common"

needs_corpus = pytest.mark.skipif(
    not _GLOBALS.is_dir(),
    reason="uncooked corpus absent (run scripts/extract_uncooked.py)")

_SCHEMA = next(s for s in SCHEMAS if s.cls == "oCGlobalEntityValueSettings")


def _cooked(name: str) -> bytes:
    return (_GLOBALS / f"{name}.globalvalue.ot.GlobalEntityValueSettings.gen").read_bytes()


def _read_value(data: bytes, fmt: str):
    """Unpack the union payload the way the engine would: body+0x0c."""
    body = data[data.rfind(MARK_BEGIN) + 4:data.rfind(MARK_END)]
    return struct.unpack_from(fmt, body, 0x0c)[0]


@needs_corpus
def test_a_bool_global_can_be_patched_at_all():
    """The reveal-all switch. Ships false, and used to be unreachable."""
    before = _cooked("Start_Revealed_Map")
    assert _read_value(before, "<?") is False

    after = patch_field(before, _SCHEMA, "value", True)
    assert _read_value(after, "<?") is True
    # One byte, in place: the container must not move.
    assert len(after) == len(before)
    assert sum(a != b for a, b in zip(after, before, strict=True)) == 1


@needs_corpus
def test_an_int_global_is_written_as_an_int():
    """The silent-corruption half: 0x40e00000 is what `<f` used to leave here."""
    before = _cooked("Invasion_Max_Level")
    assert _read_value(before, "<i") == 5

    after = patch_field(before, _SCHEMA, "value", 7)
    assert _read_value(after, "<i") == 7
    assert _read_value(after, "<f") != 7.0, "written as a float again"


@needs_corpus
def test_the_float_case_did_not_move():
    before = _cooked("Card_Attack_Damage")
    assert _read_value(before, "<f") == pytest.approx(0.2)

    after = patch_field(before, _SCHEMA, "value", 1.5)
    assert _read_value(after, "<f") == pytest.approx(1.5)
    assert len(after) == len(before)


@needs_corpus
def test_a_vector_global_is_refused_not_guessed():
    """Three floats, no single `value` to aim at — fail closed."""
    with pytest.raises(ValueError, match="refusing to guess"):
        patch_field(_cooked("Altar_Of_Heroes_Pos"), _SCHEMA, "value", 1.0)


@needs_corpus
def test_a_float_aimed_at_an_int_global_is_reported_not_packed():
    """`merge` catches ValueError per field; struct.error would escape it."""
    with pytest.raises(ValueError, match="does not fit"):
        patch_field(_cooked("Invasion_Max_Level"), _SCHEMA, "value", 0.5)
