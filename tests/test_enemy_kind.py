"""The `[[content]] kind="enemy"` builder clones a vanilla
``oCDtEnemyDefinition`` and patches spawn-relevant fields.

Covers the guardrails added once the spawn model was pinned down (the candidate
list is the tribe's runtime roster at ``+0x2b8``, populated from each enemy's
``tribe_ref``): reject unknown tribes + crash-prone weights, warn on cross-tribe
clones, and keep a weight-only clone byte-identical to its base everywhere else.
Runs against the real vanilla Gnoll corpus (skipped if absent).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from rsmm.engine import cooked
from rsmm.engine.cooked_schemas import definitions as D
from rsmm.sdk.content import ContentDef, ContentError
from rsmm.sdk.kinds import enemies

_BASE = "Gnoll_Shielded"
_BASE_GEN = enemies._ENEMY_DIR / f"{_BASE}{enemies._ENEMY_GEN_SUFFIX}"


def _require_corpus():
    if not _BASE_GEN.is_file():
        pytest.skip("vanilla enemy corpus not present")


def _decode(path) -> dict:
    spec = D._SPECS["oCDtEnemyDefinition"]
    return spec.decode_body(cooked.parse(Path(path).read_bytes()).sections[-1].payload)


def _emit(tmp_path: Path, *, id: str = "Clone", **fields) -> list[Path]:
    defn = ContentDef(kind="enemy", id=id, fields={"base": _BASE, **fields})
    return enemies.emit("TestEnemyMod", defn, tmp_path)


def test_weight_only_clone_is_byte_identical_except_weight(tmp_path):
    """A clone passing only `weight` must keep tribe_ref/entity_ref/flags/tail
    byte-identical — the property the in-game self-register test depends on."""
    _require_corpus()
    base = _decode(_BASE_GEN)
    clone = _decode(_emit(tmp_path, weight=20.0)[0])
    for k in ("tribe_ref", "entity_ref", "flags", "base_flags", "_tail_hex"):
        assert clone[k] == base[k], f"{k} changed unexpectedly"
    assert clone["spawn_weight"] == 20.0
    assert base["spawn_weight"] != 20.0  # the one field we did change


def test_unknown_tribe_rejected(tmp_path):
    _require_corpus()
    with pytest.raises(ContentError, match="not a vanilla tribe"):
        _emit(tmp_path, tribe="Goblins")  # Ravenswatch has Gnolls, not Goblins


def test_known_tribe_accepted(tmp_path):
    _require_corpus()
    clone = _decode(_emit(tmp_path, tribe="Gnolls")[0])
    assert clone["tribe_ref"][1].endswith("Gnolls.enemytribedef.ot")
    assert clone["base_flags"] == [1, 1]  # has-tribe gate on


def test_extreme_weight_rejected(tmp_path):
    _require_corpus()
    with pytest.raises(ContentError, match="exceeds the safe ceiling"):
        _emit(tmp_path, weight=9999)  # the value that crashed the game


def test_cross_tribe_clone_warns(tmp_path, caplog):
    _require_corpus()
    # Gnoll_Shielded belongs to Gnolls; rewriting to Crabs (a real tribe) is
    # cross-tribe — the clone keeps the gnoll entity, pooled in the wrong biome.
    with caplog.at_level(logging.WARNING):
        _emit(tmp_path, tribe="Crabs")
    assert "cross-tribe" in caplog.text


def test_known_tribes_includes_corpus(tmp_path):
    _require_corpus()
    tribes = enemies._known_tribes()
    assert "Gnolls" in tribes and "Crabs" in tribes
    assert "Goblins" not in tribes
