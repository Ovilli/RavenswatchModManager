"""A clone whose id is a shipped id silently replaced the shipped def (audit
#202 batch 7). items, enemies, modifiers and challenges now refuse it, as
skills already did."""

from __future__ import annotations

import types

import pytest

from rsmm.sdk.content import ContentDef, ContentError
from rsmm.sdk.kinds import challenges, enemies, items, modifiers

_SHIPPED = types.SimpleNamespace(read=lambda rel: b"x", exists=lambda rel: True)


def test_item_clone_with_a_shipped_id(tmp_path, monkeypatch):
    monkeypatch.setattr(items, "_vanilla_item_ids", lambda: {"Ring"})
    monkeypatch.setattr(items, "_find_base", lambda base: (b"", "Common"))
    with pytest.raises(ContentError, match="already called 'Ring'"):
        items.emit("m", ContentDef("item", "Ring", {"base": "Other"}), tmp_path)


def test_enemy_clone_with_a_shipped_id(tmp_path, monkeypatch):
    monkeypatch.setattr(enemies, "_load_base_cooked", lambda name: b"x")
    with pytest.raises(ContentError, match="already called 'Gnoll'"):
        enemies.emit("m", ContentDef("enemy", "Gnoll", {"base": "Gnoll_Shielded"}), tmp_path)


def test_modifier_clone_with_a_shipped_id(tmp_path, monkeypatch):
    monkeypatch.setattr(modifiers, "corpus", _SHIPPED)
    with pytest.raises(ContentError, match="already called 'NoMinimap'"):
        modifiers.emit("m", ContentDef("modifier", "NoMinimap", {"base": "NoMinimap"}), tmp_path)


def test_challenge_clone_with_a_shipped_id(tmp_path, monkeypatch):
    monkeypatch.setattr(challenges, "corpus", _SHIPPED)
    monkeypatch.setattr(challenges, "_modifiers", lambda defn: [])
    with pytest.raises(ContentError, match="already called 'DodgeIt'"):
        challenges.emit("m", ContentDef("challenge", "DodgeIt", {}), tmp_path)
    assert not any(tmp_path.rglob("*"))
