"""oCAnimation (v1.5) round-trip — schema verification against real .yqz files.

Skipped when no Ravenswatch install is reachable. Locally exercises a
random sample of animation files through `parse_payload` +
`emit_payload`.
"""

from __future__ import annotations

import os
import random
from pathlib import Path

import pytest

from rsmm.engine.cooked import parse
from rsmm.engine.cooked_schemas.animation import (
    AnimationHandler,
    emit_payload,
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

SAMPLE_LIMIT = int(os.environ.get("RSMM_ANIM_SAMPLE_LIMIT", "16"))


def _find_cooking_root() -> Path | None:
    for c in _COOKING_CANDIDATES:
        if c.is_dir():
            return c
    return None


@pytest.fixture(scope="module")
def animation_samples() -> list[Path]:
    root = _find_cooking_root()
    if root is None:
        pytest.skip("no Ravenswatch install found")
    found: list[Path] = []
    for p in root.rglob("*.yqz"):
        try:
            cf = parse(p.read_bytes())
        except Exception:
            continue
        if any(c.name == "oCAnimation" for c in cf.classes):
            found.append(p)
    if not found:
        pytest.skip("no oCAnimation .yqz files in cooking dir")
    random.seed(0xA51_FACE)
    return random.sample(found, min(SAMPLE_LIMIT, len(found)))


def test_animation_handler_registered() -> None:
    from rsmm.engine import cooked_schemas

    h = cooked_schemas.get("oCAnimation")
    assert isinstance(h, AnimationHandler)
    assert h.source_ext == "glb"


def test_real_animation_roundtrip(animation_samples: list[Path]) -> None:
    for p in animation_samples:
        cf = parse(p.read_bytes())
        pay = b"".join(s.payload for s in cf.sections)
        anim = parse_payload(pay)
        rt = emit_payload(anim)
        assert rt == pay, f"animation round-trip failed for {p.name}"
        assert anim.name, f"empty animation name in {p.name}"
        assert anim.tracks, f"no tracks in {p.name}"
