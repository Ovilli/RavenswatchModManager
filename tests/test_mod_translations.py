"""A mod's lang/<LOCALE>.toml reaches what the client shows and the game."""

from pathlib import Path

import pytest

from rsmm.sdk.config import ConfigStore
from rsmm.sdk.i18n import active_locale, config_text, mod_text

ZH = """
[strings]
hello = "你好"

[manifest]
name = "悬赏榜"

[overlay]
title = "悬赏"

[overlay.columns]
bounty = "悬赏"

[config.difficulty]
label = "难度"

[config.difficulty.choices]
relaxed = "轻松"
"""

SCHEMA = """
[fields.difficulty]
label = "Difficulty"
type = "enum"
values = ["relaxed", "standard"]
default = "standard"
"""


def _mod(tmp_path: Path) -> Path:
    d = tmp_path / "demo"
    (d / "lang").mkdir(parents=True)
    (d / "lang" / "ZH-S.toml").write_text(ZH, encoding="utf-8")
    (d / "config_schema.toml").write_text(SCHEMA, encoding="utf-8")
    return d


@pytest.mark.parametrize(("env", "want"), [
    ("ZH-S", "ZH-S"), ("zh-CN", "ZH-S"), ("zh_cn", "ZH-S"), ("zh-TW", "ZH-T"),
    ("", "EN"), ("klingon", "EN"),
])
def test_active_locale_normalises(monkeypatch, env, want):
    monkeypatch.setenv("RSMM_LOCALE", env)
    assert active_locale() == want


def test_mod_text_reads_client_sections(tmp_path, monkeypatch):
    d = _mod(tmp_path)
    monkeypatch.setenv("RSMM_LOCALE", "ZH-S")
    text = mod_text(d)
    assert text["manifest"]["name"] == "悬赏榜"
    assert "strings" not in text           # game-side text is not the client's
    assert config_text(text, "difficulty") == ("难度", {"relaxed": "轻松"})


def test_english_and_missing_files_change_nothing(tmp_path, monkeypatch):
    d = _mod(tmp_path)
    monkeypatch.setenv("RSMM_LOCALE", "EN")
    assert mod_text(d) == {}
    monkeypatch.setenv("RSMM_LOCALE", "JA")
    assert mod_text(d) == {}


def test_broken_translation_never_hides_the_mod(tmp_path, monkeypatch):
    d = _mod(tmp_path)
    (d / "lang" / "ZH-S.toml").write_text("this is = = not toml", encoding="utf-8")
    monkeypatch.setenv("RSMM_LOCALE", "ZH-S")
    assert mod_text(d) == {}


def test_config_schema_carries_translated_labels(tmp_path, monkeypatch):
    d = _mod(tmp_path)
    monkeypatch.setenv("RSMM_LOCALE", "ZH-S")
    field = ConfigStore(d).schema_as_dict()["fields"]["difficulty"]
    assert field["label"] == "难度"
    assert field["choiceLabels"] == {"relaxed": "轻松"}
    assert field["choices"] == ["relaxed", "standard"]     # values never change


def test_overlay_declaration_is_localized(monkeypatch):
    from rsmm.cli.cmd_overlay import _localize, parse_spec

    spec = parse_spec({"title": "Bounties", "columns": [{"key": "bounty", "label": "Bounty"},
                                                          {"key": "count", "label": ""}]},
                      mod_id="demo")
    _localize(spec, {"overlay": {"title": "悬赏", "columns": {"bounty": "悬赏"}}})
    assert spec["title"] == "悬赏"
    assert [c["label"] for c in spec["columns"]] == ["悬赏", ""]
    assert [c["key"] for c in spec["columns"]] == ["bounty", "count"]


def test_apply_copies_lang_into_the_game(tmp_path):
    """The loader reads <game>/mods/<mod>/lang/; apply used to copy only the
    mod's top-level files, so every translated mod spoke English in game."""
    from rsmm.cli.apply_mods import Mod, _sync_mod_manifests

    d = _mod(tmp_path / "src")
    (d / "manifest.toml").write_text('[mod]\nid = "demo"\nenabled = true\n', encoding="utf-8")
    (d / "init.lua").write_text("-- demo\n", encoding="utf-8")
    game = tmp_path / "game"
    game.mkdir()
    _sync_mod_manifests([Mod(d)], game, dry_run=False)
    assert (game / "mods" / "demo" / "lang" / "ZH-S.toml").read_text(encoding="utf-8") == ZH
