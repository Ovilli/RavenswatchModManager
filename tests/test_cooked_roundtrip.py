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
