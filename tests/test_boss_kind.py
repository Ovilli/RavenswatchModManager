"""The `[[content]] kind="boss"` builder stages a set of JSON manifests under
``<out>/_pending_bosses/<id>/`` for the next-phase apply pipeline — it does no
corpus I/O of its own, so these tests run without the vanilla boss corpus.

The boss kind is rated ``guess`` (picker/HP/arena offsets are speculative), so
these assertions lock the *emit structure and guardrails*, not offset
correctness — they exist to catch accidental shape regressions, not to claim the
cooked bytes load in-game.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rsmm.sdk.content import ContentDef, SchemaNotMined
from rsmm.sdk.kinds import bosses

_MOD = "TestBossMod"
_BASE = "Heredos"  # any vanilla boss id; emit only records it as `cloned_from`

_PIECES = {"boss.json", "enemy.json", "bosstimer.json", "reward.json", "spawn.json", "i18n.json"}


def _emit(tmp_path: Path, *, id: str = "ShadowKing", **fields) -> list[Path]:
    defn = ContentDef(kind="boss", id=id, fields={"base": _BASE, **fields})
    return bosses.emit(_MOD, defn, tmp_path)


def _load(paths: list[Path], name: str) -> dict:
    (one,) = [p for p in paths if p.name == name]
    return json.loads(one.read_text())


# --- guardrails (corpus-free, always run) ----------------------------------


def test_missing_base_raises_schema_not_mined(tmp_path):
    defn = ContentDef(kind="boss", id="ShadowKing", fields={})
    with pytest.raises(SchemaNotMined, match="needs a 'base'"):
        bosses.emit(_MOD, defn, tmp_path)


def test_phases_must_be_list(tmp_path):
    with pytest.raises(ValueError, match="'phases' must be a list"):
        _emit(tmp_path, phases="phase-one")


def test_invalid_id_rejected(tmp_path):
    with pytest.raises(ValueError, match="must match"):
        _emit(tmp_path, id="Shadow King!")  # space + punctuation


# --- emit structure --------------------------------------------------------


def test_emits_all_pieces_under_pending_dir(tmp_path):
    paths = _emit(tmp_path)
    assert {p.name for p in paths} == _PIECES
    root = tmp_path / "_pending_bosses" / "ShadowKing"
    assert all(p.parent == root for p in paths)


def test_boss_manifest_shape(tmp_path):
    boss = _load(_emit(tmp_path), "boss.json")
    assert boss["schema"] == "rsmm.boss.v1"
    assert boss["kind"] == "boss"
    assert boss["id"] == "ShadowKing"
    assert boss["mod"] == _MOD
    assert boss["base"] == _BASE
    assert boss["display_name_key"] == f"RSMM_{_MOD}_ShadowKing_name"
    # pointer map drives the apply pipeline from boss.json alone
    assert set(boss["pieces"]) == {"enemy", "bosstimer", "reward", "spawn"}


def test_reward_inherited_when_omitted(tmp_path):
    reward = _load(_emit(tmp_path), "reward.json")
    assert reward["reward_id"] is None
    assert reward["inherited_from_base"] is True


def test_reward_explicit(tmp_path):
    reward = _load(_emit(tmp_path, reward="GildedChest"), "reward.json")
    assert reward["reward_id"] == "GildedChest"
    assert reward["inherited_from_base"] is False


def test_enemy_flag_inherited_when_no_flag_tag(tmp_path):
    enemy = _load(_emit(tmp_path), "enemy.json")
    assert enemy["flag_bit_inherited_from_base"] is True
    assert enemy["cloned_from"] == _BASE


def test_arena_seeds_bosstimer_picker(tmp_path):
    bt = _load(_emit(tmp_path, arena="StormIsland"), "bosstimer.json")
    targets = [s.get("target") for s in bt["synthesized"].values()]
    assert "StormIsland" in targets


def test_no_arena_leaves_bosstimer_unsynthesized(tmp_path):
    bt = _load(_emit(tmp_path), "bosstimer.json")
    assert bt["synthesized"] == {}


def test_i18n_seeds_display_name(tmp_path):
    i18n = _load(_emit(tmp_path, display_name="The Shadow King"), "i18n.json")
    assert i18n["strings"][f"RSMM_{_MOD}_ShadowKing_name"] == "The Shadow King"
    assert i18n["fallback_locale"] == "EN"
