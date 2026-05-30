"""oCGeometry (v1.2) — round-trip preview via raw_payload_b64.

Skipped when no Ravenswatch install is reachable. Locally exercises a
random sample of geometry .yqz files through `parse_payload`,
`_build_glb_preview`, and `_extract_raw_payload_from_glb`.
"""

from __future__ import annotations

import os
import random
from pathlib import Path

import pytest

from rsmm.engine.cooked import parse
from rsmm.engine.cooked_schemas.geometry import (
    GeometryHandler,
    _build_glb_preview,
    _extract_raw_payload_from_glb,
    parse_payload,
)

_COOKING_CANDIDATES = [
    Path(os.path.expanduser(
        "~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/"
        "common/Ravenswatch/DarkTalesResources/_Cooking"
    )),
    Path(os.path.expanduser("~/.steam/steam/steamapps/common/Ravenswatch/"
                            "DarkTalesResources/_Cooking")),
]

SAMPLE_LIMIT = int(os.environ.get("RSMM_GEOMETRY_SAMPLE_LIMIT", "16"))


def _find_cooking_root() -> Path | None:
    for c in _COOKING_CANDIDATES:
        if c.is_dir():
            return c
    return None


@pytest.fixture(scope="module")
def geometry_samples() -> list[Path]:
    root = _find_cooking_root()
    if root is None:
        pytest.skip("no Ravenswatch install found")
    # *Kqrxqius* matches the cipher-encoded "Geometry" filename token
    # used by every shipped oCGeometry container in the corpus.
    found = list(root.rglob("*Kqrxqius*.yqz"))
    if not found:
        pytest.skip("no geometry .yqz files in cooking dir")
    random.seed(0xCAFEBABE)
    return random.sample(found, min(SAMPLE_LIMIT, len(found)))


def test_geometry_handler_registered() -> None:
    from rsmm.engine import cooked_schemas

    h = cooked_schemas.get("oCGeometry")
    assert isinstance(h, GeometryHandler)
    assert h.source_ext == "glb"


def test_real_geometry_roundtrip(geometry_samples: list[Path]) -> None:
    for p in geometry_samples:
        cf = parse(p.read_bytes())
        if not any(c.name == "oCGeometry" for c in cf.classes):
            continue
        raw = b"".join(s.payload for s in cf.sections)
        sec_lens = [len(s.payload) for s in cf.sections]
        g = parse_payload(raw, sec_lens)
        glb = _build_glb_preview(g)
        raw_back = _extract_raw_payload_from_glb(glb)
        assert raw_back == raw, f"geometry round-trip failed for {p.name}"


def test_geometry_encode_rejects_unmarked_glb() -> None:
    """`encode()` must refuse a .glb that lacks the rsmm raw-payload marker.

    Full cooker re-quantization is not implemented yet; silently
    accepting unmarked glTF would let modders ship broken meshes.
    """
    import json
    import struct

    h = GeometryHandler()
    # Minimal valid glb with no extras.rsmm
    j = json.dumps({"asset": {"version": "2.0"}}, separators=(",", ":")).encode()
    j_pad = (-len(j)) % 4
    j += b" " * j_pad
    glb = bytearray()
    glb += struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(j))
    glb += struct.pack("<II", len(j), 0x4E4F534A)
    glb += j

    # A custom mesh (no embedded cooked bytes) must surface as
    # NotReversedError so apply-mods / cook_cache skip it cleanly rather
    # than crash on an uncaught error.
    from rsmm.engine.cooked_schemas import NotReversedError
    with pytest.raises(NotReversedError, match="oCGeometry"):
        h.encode(bytes(glb))
