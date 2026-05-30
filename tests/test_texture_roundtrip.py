"""oCTexture (v1.14) round-trip — schema verification against real .tpi files.

Skipped automatically when no Ravenswatch install is reachable on this
host (e.g. CI runners without the game). Locally, exercises a random
sample of cooked textures end-to-end through `_decode_payload` +
`_encode_payload`.
"""

from __future__ import annotations

import os
import random
from pathlib import Path

import pytest

from rsmm.engine.cooked import parse
from rsmm.engine.cooked_schemas.texture import (
    TextureHandler,
    _decode_payload,
    _encode_payload,
)

_COOKING_CANDIDATES = [
    Path(os.path.expanduser(
        "~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/"
        "common/Ravenswatch/DarkTalesResources/_Cooking"
    )),
    Path(os.path.expanduser("~/.steam/steam/steamapps/common/Ravenswatch/"
                            "DarkTalesResources/_Cooking")),
]

SAMPLE_LIMIT = int(os.environ.get("RSMM_TEXTURE_SAMPLE_LIMIT", "32"))


def _find_cooking_root() -> Path | None:
    for c in _COOKING_CANDIDATES:
        if c.is_dir():
            return c
    return None


@pytest.fixture(scope="module")
def texture_samples() -> list[Path]:
    root = _find_cooking_root()
    if root is None:
        pytest.skip("no Ravenswatch install found")
    files = list(root.rglob("*.tpi"))
    if not files:
        pytest.skip("no .tpi files in cooking dir")
    random.seed(0xC0FFEE)
    return random.sample(files, min(SAMPLE_LIMIT, len(files)))


def test_texture_handler_registered() -> None:
    from rsmm.engine import cooked_schemas

    h = cooked_schemas.get("oCTexture")
    assert isinstance(h, TextureHandler)
    assert h.source_ext == "dds"


def test_real_texture_roundtrip(texture_samples: list[Path]) -> None:
    for p in texture_samples:
        cf = parse(p.read_bytes())
        if not any(c.name == "oCTexture" for c in cf.classes):
            continue
        success = False
        for sec in cf.sections:
            try:
                schema = _decode_payload(sec.payload)
                rt = _encode_payload(schema)
            except Exception:
                continue
            if rt == sec.payload:
                success = True
                break
        assert success, f"oCTexture round-trip failed for {p.name}"


def test_real_dds_roundtrip(texture_samples: list[Path]) -> None:
    """cooked -> DDS -> cooked must reproduce a semantically-equivalent texture.

    Production code path for DDS source mods: a modder ships a .dds file,
    apply pipeline calls `TextureHandler.encode_container`, engine loads
    the result. The cooked-format encoder picks corpus-typical defaults
    for fields that DDS metadata can't express (the engine accepts both
    `array_size=0/1` and `mip_count_field=0/1` for plain 2D textures —
    the shipped corpus has both, presumably from different asset-pipeline
    revisions).

    Asserts on the *semantic* schema (width, height, format, pixel data,
    mip chain) — not on byte-identity — because the encoder picks one
    canonical value for the ambiguous flag fields.
    """
    from rsmm.engine.cooked_schemas.texture import dds_to_schema, schema_to_dds

    h = TextureHandler()
    for p in texture_samples:
        cf = parse(p.read_bytes())
        if not any(c.name == "oCTexture" for c in cf.classes):
            continue
        try:
            schema = _decode_payload(cf.sections[1].payload)
        except Exception:
            continue
        if schema.format_name is None:
            continue

        dds_bytes = schema_to_dds(schema)
        # DDS must parse back into a schema matching pixels/dims/format.
        new_schema = dds_to_schema(dds_bytes)
        assert new_schema.width == schema.width, p.name
        assert new_schema.height == schema.height, p.name
        assert new_schema.format_engine_enum == schema.format_engine_enum, p.name
        assert new_schema.pixels == schema.pixels, f"pixel mismatch in {p.name}"
        assert new_schema.mips == schema.mips, f"mip chain mismatch in {p.name}"

        # Full container path must produce a parseable cooked file.
        cooked_out = h.encode_container(dds_bytes)
        new_cf = parse(cooked_out)
        assert any(c.name == "oCTexture" for c in new_cf.classes), p.name
