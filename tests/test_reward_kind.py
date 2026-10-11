"""The `[[content]] kind="reward"` builder edits a retail rewarddef in place
(override asset at the vanilla decoded path) — ban reward entities, tune
per-category spawn counts.

Runs against the real vanilla rewards corpus (skipped if absent).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rsmm.engine import corpus
from rsmm.engine.cooked_schemas.definitions import RewardDefinitionHandler
from rsmm.sdk.content import ContentDef, ContentError
from rsmm.sdk.kinds import rewards

_BASE = "Camp_Rewards_Avalon_Update5"
_BASE_GEN = f"{rewards._REWARD_DIR}/{_BASE}{rewards.GEN_SUFFIX}"


def _require_corpus():
    if not corpus.exists(_BASE_GEN):
        pytest.skip("vanilla rewards corpus not present")


def _decode(src: Path | str) -> dict:
    """Decode an emitted file (a Path) or a shipped def (a decoded path)."""
    raw = src.read_bytes() if isinstance(src, Path) else corpus.read(src)
    return json.loads(RewardDefinitionHandler().decode_cooked(raw))


def _emit(tmp_path: Path, *, id: str = "Edit", **fields) -> list[Path]:
    defn = ContentDef(kind="reward", id=id, fields={"base": _BASE, **fields})
    return rewards.emit("TestRewardMod", defn, tmp_path)


def test_emits_at_retail_decoded_path(tmp_path):
    _require_corpus()
    (out,) = _emit(tmp_path, ban=["Astrolab"])
    assert out == tmp_path / "Definitions" / "Rewards" / f"{_BASE}{rewards.GEN_SUFFIX}"


def test_ban_drops_matching_items_from_all_categories(tmp_path):
    _require_corpus()
    base = _decode(_BASE_GEN)
    astrolabs = {i for i, item in enumerate(base["reward_items"])
                 if "astrolab" in item["entity"].lower()}
    assert astrolabs, "corpus should contain astrolab rows"
    edited = _decode(_emit(tmp_path, ban=["Astrolab"])[0])
    for t in edited["reward_types"]:
        assert not astrolabs & set(t["items"])
    # Item rows themselves stay so indices remain stable.
    assert len(edited["reward_items"]) == len(base["reward_items"])


def test_ban_locked_variant_clears_ref_only(tmp_path):
    _require_corpus()
    base = _decode(_BASE_GEN)
    locked = {i for i, item in enumerate(base["reward_items"])
              if "chest_locked" in item["_ref_b"][1].lower()}
    assert locked, "corpus should carry locked-chest variant refs"
    edited = _decode(_emit(tmp_path, ban=["Chest_Locked"])[0])
    for i in locked:
        assert edited["reward_items"][i]["_ref_b"] == ["", ""]
        # The chest itself is NOT dropped from its category.
        assert any(i in t["items"] for t in edited["reward_types"])


def test_ban_emptying_a_category_zeroes_its_counts(tmp_path):
    _require_corpus()
    base = _decode(_BASE_GEN)
    # Ban everything -> every category emptied and zeroed.
    all_entities = sorted({rewards._basename(i["entity"])
                           for i in base["reward_items"]})
    edited = _decode(_emit(tmp_path, ban=all_entities)[0])
    for t in edited["reward_types"]:
        assert t["items"] == []
        assert t["min_count"] == 0 and t["max_count"] == 0


def test_counts_override(tmp_path):
    _require_corpus()
    edited = _decode(_emit(tmp_path, counts={"0": [0, 0], "1": [2, 5]})[0])
    assert (edited["reward_types"][0]["min_count"],
            edited["reward_types"][0]["max_count"]) == (0, 0)
    assert (edited["reward_types"][1]["min_count"],
            edited["reward_types"][1]["max_count"]) == (2, 5)


def test_output_reencodes_and_untouched_fields_survive(tmp_path):
    _require_corpus()
    base = _decode(_BASE_GEN)
    edited = _decode(_emit(tmp_path, counts={"0": [1, 1]})[0])
    assert edited["reward_items"] == base["reward_items"]
    assert edited["reward_types"][1:] == base["reward_types"][1:]
    assert edited["_container"] == base["_container"]


def test_noop_edit_rejected(tmp_path):
    _require_corpus()
    with pytest.raises(ContentError, match="no edits"):
        _emit(tmp_path)


def test_unmatched_ban_pattern_rejected(tmp_path):
    _require_corpus()
    with pytest.raises(ContentError, match="matches no reward item"):
        _emit(tmp_path, ban=["Definitely_Not_A_Chest"])


def test_bad_counts_rejected(tmp_path):
    _require_corpus()
    with pytest.raises(ContentError, match="out of range"):
        _emit(tmp_path, counts={"99": [0, 1]})
    with pytest.raises(ContentError, match="min <= max"):
        _emit(tmp_path, counts={"0": [3, 1]})


def test_superseded_base_is_refused(tmp_path):
    """The plain Camp_Rewards_<Biome> defs are referenced by nothing; only the
    LiveOps5 versiondef names reward defs, and it names the _Update5 ones. An
    edit to the dead def installs cleanly and changes nothing."""
    dead = f"{rewards._REWARD_DIR}/Camp_Rewards_Avalon{rewards.GEN_SUFFIX}"
    if not corpus.exists(dead):
        pytest.skip("vanilla rewards corpus not present")
    defn = ContentDef(kind="reward", id="Dead", fields={
        "base": "Camp_Rewards_Avalon", "ban": ["Astrolab"]})
    with pytest.raises(ContentError, match="Camp_Rewards_Avalon_Update5"):
        rewards.emit("TestRewardMod", defn, tmp_path)
