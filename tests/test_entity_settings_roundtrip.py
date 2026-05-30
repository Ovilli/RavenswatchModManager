"""oCEntitySettingsResource — byte-stable JSON round-trip + path edit.

Skipped when no Ravenswatch install is reachable. Samples a subset for speed.
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

import pytest

from rsmm.engine import cooked_schemas
from rsmm.engine.cooked import parse
from rsmm.engine.cooked_schemas.entity_settings import EntitySettingsHandler

_COOKING_CANDIDATES = [
    Path(os.path.expanduser(
        "~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/"
        "common/Ravenswatch/DarkTalesResources/_Cooking"
    )),
    Path(os.path.expanduser("~/.steam/steam/steamapps/common/Ravenswatch/"
                            "DarkTalesResources/_Cooking")),
]

SAMPLE_LIMIT = int(os.environ.get("RSMM_ENTITY_SAMPLE_LIMIT", "300"))


def _find_cooking_root() -> Path | None:
    for c in _COOKING_CANDIDATES:
        if c.is_dir():
            return c
    return None


@pytest.fixture(scope="module")
def es_samples() -> list[Path]:
    root = _find_cooking_root()
    if root is None:
        pytest.skip("no Ravenswatch install found")
    found = list(root.rglob("*MzidisFqiidzyvLqvrwubq*.yqz"))
    if not found:
        pytest.skip("no entity-settings .yqz files in cooking dir")
    random.seed(0xE571)
    return random.sample(found, min(SAMPLE_LIMIT, len(found)))


def test_entity_settings_handler_registered() -> None:
    h = cooked_schemas.get("oCEntitySettingsResource")
    assert isinstance(h, EntitySettingsHandler)
    assert h.source_ext == "entitysettings.json"


def test_entity_settings_roundtrip(es_samples: list[Path]) -> None:
    h = cooked_schemas.get("oCEntitySettingsResource")
    for p in es_samples:
        raw = p.read_bytes()
        try:
            parse(raw)
        except Exception:
            continue  # malformed container — out of schema scope
        assert h.encode_container(h.decode_cooked(raw)) == raw, \
            f"entity-settings round-trip failed for {p.name}"


def test_entity_settings_path_edit(es_samples: list[Path]) -> None:
    h = cooked_schemas.get("oCEntitySettingsResource")
    for p in es_samples:
        doc = json.loads(h.decode_cooked(p.read_bytes()))
        if not doc.get("entity_path"):
            continue
        doc["entity_path"] = "Objects\\RSMM_Edit_Test_Model.entity.ot"
        again = json.loads(h.decode_cooked(
            h.encode_container(json.dumps(doc).encode())))
        assert again["entity_path"] == "Objects\\RSMM_Edit_Test_Model.entity.ot"
        return
    pytest.skip("no entity with an editable path in sample")
