"""oCGlobalEntityValueSettings (v1.1) — JSON decode/encode round-trip.

Byte-stable across the shipped corpus: cooked -> JSON -> cooked reproduces
the original bytes. Skipped when no Ravenswatch install is reachable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from rsmm.engine import cooked_schemas
from rsmm.engine.cooked_schemas.global_values import (
    GlobalValuesHandler,
    decode_cooked_to_json,
    encode_json_to_cooked,
)

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
def gv_samples() -> list[Path]:
    root = _find_cooking_root()
    if root is None:
        pytest.skip("no Ravenswatch install found")
    # *KlraglMzidisDglwqFqiidzyv* = cipher-encoded "GlobalEntityValueSettings".
    found = list(root.rglob("*KlraglMzidisDglwqFqiidzyv*.yqz"))
    if not found:
        pytest.skip("no global-value .yqz files in cooking dir")
    return found


def test_global_values_handler_registered() -> None:
    h = cooked_schemas.get("oCGlobalEntityValueSettings")
    assert isinstance(h, GlobalValuesHandler)
    assert h.source_ext == "globalvalue.json"
    assert h.decoded and h.encoded


def test_real_global_values_roundtrip(gv_samples: list[Path]) -> None:
    for p in gv_samples:
        raw = p.read_bytes()
        js = decode_cooked_to_json(raw)
        back = encode_json_to_cooked(js)
        assert back == raw, f"global-value round-trip failed for {p.name}"


def test_global_values_edit_persists(gv_samples: list[Path]) -> None:
    # Editing a scalar value and re-encoding must survive a second decode.
    for p in gv_samples:
        doc = json.loads(decode_cooked_to_json(p.read_bytes()))
        if doc["value"]["type"] != "int":
            continue
        doc["value"]["value"] = 12345
        again = json.loads(decode_cooked_to_json(
            encode_json_to_cooked(json.dumps(doc).encode())))
        assert again["value"]["value"] == 12345
        return
    pytest.skip("no int-typed global value in corpus sample")
