"""Asset-ref passthrough classes (VFX / GameStream / CollisionMesh) —
byte-stable JSON round-trip + ref edit. Skipped without a game install."""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

import pytest

from rsmm.engine import cooked_schemas
from rsmm.engine.cooked import parse
from rsmm.engine.cooked_schemas.asset_refs import AssetRefsHandler

_COOKING_CANDIDATES = [
    Path(os.path.expanduser(
        "~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/"
        "common/Ravenswatch/DarkTalesResources/_Cooking"
    )),
    Path(os.path.expanduser("~/.steam/steam/steamapps/common/Ravenswatch/"
                            "DarkTalesResources/_Cooking")),
]

# class -> cipher-encoded cooked-filename token
_TOKENS = {
    "oCScheduledVfxSettings": "FbnqtwlqtDhpFqiidzyv",
    "oCGameStream": "KgxqFiuqgx",
    "oCCollisionMesh": "Srlldvdrz",
    "oCMaterial": "Hgiqudgl",
}
SAMPLE_LIMIT = int(os.environ.get("RSMM_ASSETREFS_SAMPLE_LIMIT", "200"))


def _find_cooking_root() -> Path | None:
    for c in _COOKING_CANDIDATES:
        if c.is_dir():
            return c
    return None


def test_assetrefs_handlers_registered() -> None:
    for cls in _TOKENS:
        h = cooked_schemas.get(cls)
        assert isinstance(h, AssetRefsHandler)


@pytest.mark.parametrize("cls", sorted(_TOKENS))
def test_assetrefs_roundtrip(cls: str) -> None:
    root = _find_cooking_root()
    if root is None:
        pytest.skip("no Ravenswatch install found")
    files = list(root.rglob(f"*{_TOKENS[cls]}*.yqz"))
    if not files:
        pytest.skip(f"no {cls} files in cooking dir")
    random.seed(0xA55E7)
    files = random.sample(files, min(SAMPLE_LIMIT, len(files)))
    h = cooked_schemas.get(cls)
    edited = False
    for p in files:
        raw = p.read_bytes()
        try:
            parse(raw)
        except Exception:
            continue
        assert h.encode_container(h.decode_cooked(raw)) == raw, \
            f"{cls} round-trip failed for {p.name}"
        if not edited:
            doc = json.loads(h.decode_cooked(raw))
            if doc["asset_refs"]:
                doc["asset_refs"][0] = "Materials\\RSMM_Edit_Test.mat.ot"
                again = json.loads(h.decode_cooked(
                    h.encode_container(json.dumps(doc).encode())))
                assert again["asset_refs"][0] == "Materials\\RSMM_Edit_Test.mat.ot"
                edited = True
