"""The in-game menu's art pack (rsmm.engine.ui_pack) and the files the loader
reads to draw the Settings page."""

from __future__ import annotations

import json

import pytest

from rsmm.engine import corpus, ui_pack


def _game(tmp_path, exe_size=1234):
    game = tmp_path / "game"
    game.mkdir()
    (game / "Ravenswatch.exe").write_bytes(b"\0" * exe_size)
    return game


def test_a_pack_from_another_game_build_is_not_current(tmp_path):
    game = _game(tmp_path)
    ui = game / ui_pack.UI_DIR
    ui.mkdir(parents=True)
    meta = {"version": ui_pack.PACK_VERSION, "game_exe_size": 1234}
    (ui / "pack.json").write_text(json.dumps(meta))
    assert ui_pack.current(game)
    (game / "Ravenswatch.exe").write_bytes(b"\0" * 999)          # a game update
    assert not ui_pack.current(game)
    meta["version"] = ui_pack.PACK_VERSION + 1
    (ui / "pack.json").write_text(json.dumps(meta))
    assert not ui_pack.current(game)


def test_no_pack_is_not_current(tmp_path):
    assert not ui_pack.current(_game(tmp_path))


def test_the_pack_holds_every_texture_and_font_at_its_size(tmp_path):
    if not corpus.exists(ui_pack.TEXTURES["button"]):
        pytest.skip("game textures not available (no mirror, no install)")
    game = _game(tmp_path)
    meta = ui_pack.build(game)
    ui = game / ui_pack.UI_DIR
    assert meta["missing"] == []
    assert set(meta["textures"]) == set(ui_pack.TEXTURES)
    assert set(meta["fonts"]) == set(ui_pack.FONTS)
    # The loader reads raw RGBA8 rows and refuses a file of the wrong length.
    for t in list(meta["textures"].values()) + list(meta["fonts"].values()):
        assert (ui / t["file"]).stat().st_size == t["w"] * t["h"] * 4
    body = meta["fonts"]["body"]
    assert all(str(ord(c)) in body["glyphs"] for c in "Settings 0.5")
    assert json.loads((ui / "pack.json").read_text()) == meta
    assert ui_pack.current(game)


def test_apply_installs_the_config_schema(tmp_path):
    """The in-game Settings page draws each mod's fields from the INSTALLED
    copy of config_schema.toml; apply used to hold the schema back."""
    from rsmm.cli.apply_mods import Mod, _sync_mod_manifests

    d = tmp_path / "src" / "demo"
    d.mkdir(parents=True)
    (d / "manifest.toml").write_text('[mod]\nid = "demo"\nenabled = true\n', encoding="utf-8")
    schema = '[fields.speed]\ntype = "float"\ndefault = 1.0\nmin = 0.0\nmax = 2.0\n'
    (d / "config_schema.toml").write_text(schema, encoding="utf-8")
    game = tmp_path / "game"
    game.mkdir()
    _sync_mod_manifests([Mod(d)], game, dry_run=False)
    assert (game / "mods" / "demo" / "config_schema.toml").read_text(encoding="utf-8") == schema
