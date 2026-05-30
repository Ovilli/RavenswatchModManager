"""oCDt*Definition data-table classes — JSON decode/encode round-trip.

Byte-stable across the shipped corpus per implemented class. Skipped when no
Ravenswatch install is reachable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from rsmm.engine import cooked_schemas
from rsmm.engine.cooked import parse
from rsmm.engine.cooked_schemas.definitions import _SPECS, DefinitionHandler

_COOKING_CANDIDATES = [
    Path(os.path.expanduser(
        "~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/"
        "common/Ravenswatch/DarkTalesResources/_Cooking"
    )),
    Path(os.path.expanduser("~/.steam/steam/steamapps/common/Ravenswatch/"
                            "DarkTalesResources/_Cooking")),
]

def _find_cooking_root() -> Path | None:
    for c in _COOKING_CANDIDATES:
        if c.is_dir():
            return c
    return None


@pytest.fixture(scope="module")
def files_by_class() -> dict[str, list[Path]]:
    root = _find_cooking_root()
    if root is None:
        pytest.skip("no Ravenswatch install found")
    targets = set(_SPECS)
    bucket: dict[str, list[Path]] = {}
    for p in root.rglob("*.yqz"):
        try:
            cf = parse(p.read_bytes())
        except Exception:
            continue
        cls = cf.classes[0].name if cf.classes else ""
        if cls in targets:
            bucket.setdefault(cls, []).append(p)
    if not bucket:
        pytest.skip("no definition .yqz files in cooking dir")
    return bucket


def test_definition_handlers_registered() -> None:
    for cls in _SPECS:
        h = cooked_schemas.get(cls)
        assert isinstance(h, DefinitionHandler)
        assert h.decoded and h.encoded


@pytest.mark.parametrize("cls", sorted(_SPECS))
def test_definition_roundtrip(cls: str, files_by_class: dict[str, list[Path]]) -> None:
    files = files_by_class.get(cls)
    if not files:
        pytest.skip(f"no {cls} files in cooking dir")
    h = cooked_schemas.get(cls)
    for p in files:
        raw = p.read_bytes()
        assert h.encode_container(h.decode_cooked(raw)) == raw, \
            f"{cls} round-trip failed for {p.name}"
