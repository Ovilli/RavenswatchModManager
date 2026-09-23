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

from rsmm.engine import cooked, corpus
from rsmm.engine.cooked_schemas import definitions as D
from rsmm.sdk.content import ContentDef, ContentError
from rsmm.sdk.kinds import enemies

_BASE = "Gnoll_Shielded"
_BASE_GEN = corpus.CorpusFile(f"{enemies._ENEMY_DIR}/{_BASE}{enemies._ENEMY_GEN_SUFFIX}")


def _require_corpus():
    if not _BASE_GEN.is_file():
        pytest.skip("vanilla enemy corpus not present")


def _decode(path) -> dict:
    spec = D._SPECS["oCDtEnemyDefinition"]
    src = path if hasattr(path, "read_bytes") else Path(path)   # CorpusFile or Path
    return spec.decode_body(cooked.parse(src.read_bytes()).sections[-1].payload)


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


def test_clone_ships_its_own_resource_cache(tmp_path):
    """Every shipped enemydef has a sibling `.UsedRscCache.ot`, found by name —
    so a clone under a new name has none unless the emit writes one. It must
    name the CLONE's def (never the base's), keep the base's closure, and be
    sorted, because the engine binary-searches it."""
    _require_corpus()
    from rsmm.engine import rsc_cache as RC

    written = _emit(tmp_path, id="Clone_Gnoll", weight=5.0)
    caches = [p for p in written if p.name.endswith(".UsedRscCache.ot")]
    assert [p.name for p in caches] == ["Clone_Gnoll.enemydef.UsedRscCache.ot"]
    lines = RC.parse(caches[0].read_bytes())
    assert lines == sorted(lines)
    assert "Definitions|Enemies\\Clone_Gnoll.enemydef.ot|oCDtEnemyDefinition" in lines
    assert not any(f"Enemies\\{_BASE}.enemydef.ot" in ln for ln in lines)
    assert f"EntitySettings|Enemies\\Gnoll\\{_BASE}.entity.ot|oCEntitySettingsResource" in lines


def test_clone_with_repointed_entity_borrows_the_owners_closure(tmp_path):
    _require_corpus()
    from rsmm.engine import rsc_cache as RC

    entity = "Enemies\\Gnoll\\Gnoll_Hunter.entity.ot"
    written = _emit(tmp_path, id="Clone_Gnoll", entity=entity)
    lines = RC.parse(written[-1].read_bytes())
    assert f"EntitySettings|{entity}|oCEntitySettingsResource" in lines
