"""Byte-stable round-trip test for the cooked container codec.

Samples shipped .yqz / .tpi / .zux files from the local Steam install (if
present) and asserts emit(parse(data)) == data for each. Skipped at collection
time when the game isn't installed locally, so CI without the game can still
run unit-level tests.
"""

from __future__ import annotations

import os
import random
from pathlib import Path

import pytest

from rsmm.engine.cooked import emit, parse

_COOKING = Path.home() / (
    ".var/app/com.valvesoftware.Steam/.local/share/Steam/"
    "steamapps/common/Ravenswatch/DarkTalesResources/_Cooking"
)
_EXTS = (".yqz", ".tpi", ".zux")
_SAMPLES_PER_EXT = int(os.environ.get("RSMM_ROUNDTRIP_SAMPLES", "150"))


def _gather() -> list[Path]:
    if not _COOKING.is_dir():
        return []
    rng = random.Random(0xC00CED)
    sampled: list[Path] = []
    for ext in _EXTS:
        files = list(_COOKING.rglob(f"*{ext}"))
        rng.shuffle(files)
        sampled.extend(files[:_SAMPLES_PER_EXT])
    return sampled


_FILES = _gather()


@pytest.mark.slow  # up to 450 real cooked files; local-only (needs game install)
@pytest.mark.skipif(not _FILES, reason="Ravenswatch _Cooking dir not present")
@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name)
def test_roundtrip_byte_stable(path: Path) -> None:
    data = path.read_bytes()
    cf = parse(data)
    out = emit(cf)
    assert out == data, (
        f"{path.name}: round-trip diverged "
        f"(orig={len(data)}B, emit={len(out)}B)"
    )


def _synthetic_type_b() -> bytes:
    """A minimal type-B container, the shape the ENGINE's own writer emits."""
    from rsmm.engine.cooked import ClassDef, CookedFile, Section

    cf = CookedFile(variant="B", hdr_a=0x10, flags=0)
    cf.classes.append(ClassDef("oCDtEnemyDefinition", 0x176DEBB7, 1, 0, 0x1768CE8E))
    cf.sections.append(Section(payload=b"\x01\x02\x03\x04"))
    return emit(cf)


def test_promote_to_cooked_matches_retail_header():
    """Engine output is one header promotion away from the retail shape.

    ``Object_SaveToFile`` hardcodes the saver's flag byte to 0, so it always
    writes type B — no ``uNbFlags=1`` / ``"Cooked"`` / ``"1"`` block. Measured
    2026-08-23 on a live ``oCDtEnemyDefinition``: engine output was identical to
    the shipped cooked file for all 523 body bytes and differed only by that
    15-byte block, so promoting the header is the whole conversion.
    """
    from rsmm.engine.cooked import promote_to_cooked

    src = parse(_synthetic_type_b())
    assert src.variant == "B"

    out = emit(promote_to_cooked(src))
    assert out[:4] == b"\x10\x00\x00\x00"
    assert out[4:8] == b"\x01\x00\x00\x00"          # uNbFlags = 1
    assert out[8:18] == b"\x06\x00\x00\x00Cooked"   # the tag, length-prefixed
    assert out[18:22] == b"\x01\x00\x00\x00"        # extra
    assert out[22:23] == b"1"                       # type tag

    # The promotion is header-only: the class table and payload survive, and
    # the file is exactly 15 bytes longer than the type-B form it came from.
    again = parse(out)
    assert again.variant == "A"
    assert [c.name for c in again.classes] == [c.name for c in src.classes]
    assert [s.payload for s in again.sections] == [s.payload for s in src.sections]
    assert len(out) == len(_synthetic_type_b()) + 15

    # Idempotent: promoting an already-type-A file changes nothing.
    assert emit(promote_to_cooked(again)) == out
