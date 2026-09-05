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


@pytest.mark.slow  # rglob over full corpus per class; local-only (needs game)
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


def test_an_edited_level_restamps_its_own_declared_size():
    """A level section declares its OWN length twice, and an edit must update it.

    ⚠ This is the bug that made a custom POI invisible for six playtests. The
    two u32s at +0x08/+0x0c of a section payload are `len(payload) - 16`
    (verified on 25/25 shipped Dark Hills levels). `cooked.emit` re-frames the
    OUTER container, so an edited level stayed structurally valid and passed
    every check — but these inner fields were copied verbatim, so a level whose
    strings grew by 8 bytes still declared the old length. The engine read a
    stream short by exactly that much and never created the objects past the
    cut: the level resource resolved with state=1, the tile was placed and
    built, the cache preloaded the geometry, and the swapped-in entities
    resolved ZERO times with nothing logged anywhere.
    """
    import json
    import struct

    from rsmm.engine import cooked
    from rsmm.engine.cooked_schemas.asset_refs import _decode, _encode

    src = Path("data/uncooked/Ot/DarkHills/Tiles/6x6_Blocker_02.level.ot"
               ".GameStream.gen")
    if not src.is_file():
        pytest.skip("uncooked corpus absent")

    original = src.read_bytes()
    payload = cooked.parse(original).sections[1].payload
    assert struct.unpack_from("<II", payload, 8) == (len(payload) - 16,) * 2, (
        "the shipped file should already satisfy the invariant")

    doc = _decode(original, "oCGameStream")
    # A longer replacement, exactly the shape `swaps` produces.
    doc["asset_refs"] = [
        r.replace("SceneryObjects_DarkHills\\Bone_A.entity.ot",
                  "Objects_DarkHills\\Pontoon_Pillar_12m_C.entity.ot")
        for r in doc["asset_refs"]
    ]
    edited = _encode(json.dumps(doc).encode("utf-8"))

    new_payload = cooked.parse(edited).sections[1].payload
    assert len(new_payload) > len(payload), "the edit should have grown it"
    assert struct.unpack_from("<II", new_payload, 8) == (
        len(new_payload) - 16,) * 2, (
        "the section still declares its OLD length — the engine will read a "
        "truncated stream and silently drop every object past the cut")
