"""A clone whose id is a shipped id silently replaced the shipped def (audit
#202 batch 7). items, enemies, modifiers and challenges now refuse it, as
skills already did, also when the id differs only by case: that is the same
file on Windows (#229 review)."""

from __future__ import annotations

import pytest

from rsmm.engine import corpus
from rsmm.sdk.content import ContentDef, ContentError
from rsmm.sdk.kinds import challenges, enemies, items, modifiers

_CASES = pytest.mark.parametrize("variant", [str, str.lower, str.upper])


def _ships(monkeypatch, *names):
    """The game ships ``names`` (and any base a kind reads), with no corpus."""
    monkeypatch.setattr(corpus, "stems", lambda directory, suffix: sorted(names))
    monkeypatch.setattr(corpus, "exists", lambda rel: True)
    monkeypatch.setattr(corpus, "read", lambda rel: b"x")


@_CASES
def test_item_clone_with_a_shipped_id(tmp_path, monkeypatch, variant):
    monkeypatch.setattr(items, "_vanilla_item_ids", lambda: {"Ring"})
    monkeypatch.setattr(items, "_find_base", lambda base: (b"", "Common"))
    with pytest.raises(ContentError, match="a shipped item is already called"):
        items.emit("m", ContentDef("item", variant("Ring"), {"base": "Other"}), tmp_path)


@_CASES
def test_enemy_clone_with_a_shipped_id(tmp_path, monkeypatch, variant):
    _ships(monkeypatch, "Gnoll")
    with pytest.raises(ContentError, match="a shipped enemy is already called"):
        enemies.emit("m", ContentDef("enemy", variant("Gnoll"), {"base": "Gnoll_Shielded"}),
                     tmp_path)


@_CASES
def test_modifier_clone_with_a_shipped_id(tmp_path, monkeypatch, variant):
    _ships(monkeypatch, "NoMinimap")
    with pytest.raises(ContentError, match="a shipped modifier is already called"):
        modifiers.emit("m", ContentDef("modifier", variant("NoMinimap"), {"base": "NoMinimap"}),
                       tmp_path)


@_CASES
def test_challenge_clone_with_a_shipped_id(tmp_path, monkeypatch, variant):
    _ships(monkeypatch, "DodgeIt")
    monkeypatch.setattr(challenges, "_modifiers", lambda defn: [])
    with pytest.raises(ContentError, match="a shipped challenge is already called"):
        challenges.emit("m", ContentDef("challenge", variant("DodgeIt"), {}), tmp_path)
    assert not any(tmp_path.rglob("*"))


def test_shipped_stem_ignores_case_only(monkeypatch):
    _ships(monkeypatch, "DodgeIt")
    assert corpus.shipped_stem("d", ".gen", "dodgeit") == "DodgeIt"
    assert corpus.shipped_stem("d", ".gen", "DodgeItAgain") is None
