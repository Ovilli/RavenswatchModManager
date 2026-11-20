"""`[mod] restore_options`: rsmm clears the game options a mod pinned, on
disable and on uninstall, instead of each mod shipping an `on_disable.py`
that strips the same ini lines (#202 C3)."""

from __future__ import annotations

import re
from pathlib import Path

from rsmm.cli import apply_mods
from rsmm.engine import game_settings as GS

_REPO = Path(__file__).resolve().parents[1]
INI = "[Debug]\nForced seed=12345\nDev=1\nTest=0\n\n[Display]\nScreen shake=0\n"


def _install(tmp_path, restore='["Forced seed", "Dev"]', enabled="true"):
    game = tmp_path / "game"
    cooking = game / "DarkTalesResources" / "_Cooking"
    cooking.mkdir(parents=True)
    (game / "_Save").mkdir()
    GS.settings_ini(game).write_text(INI, encoding="utf-8")
    mod = tmp_path / "mods" / "seedy"
    mod.mkdir(parents=True)
    (mod / "manifest.toml").write_text(
        f'[mod]\nid = "seedy"\nname = "S"\nversion = "1.0.0"\nenabled = {enabled}\n'
        f"restore_options = {restore}\n", encoding="utf-8")
    return game, cooking, mod


def _ini(game) -> str:
    return GS.settings_ini(game).read_text(encoding="utf-8")


def test_the_option_list_matches_the_loaders():
    lua = (_REPO / "src/loader/lib/rsmm.lua").read_text(encoding="utf-8")
    block = re.search(r"local _OPT = \{(.*?)\n\}", lua, re.S).group(1)
    assert set(re.findall(r'\["([^"]+)"\]\s*=', block)) == GS.OPTION_NAMES


def test_clear_options_strips_only_the_named_lines(tmp_path):
    game, _c, _m = _install(tmp_path)
    assert GS.clear_options(game, ["Forced seed", "Dev"]) == 2
    assert _ini(game) == "[Debug]\nTest=0\n\n[Display]\nScreen shake=0\n"
    assert GS.clear_options(game, ["Forced seed"]) == 0              # idempotent
    assert GS.clear_options(game, ["Not an option"]) == 0
    assert GS.clear_options(tmp_path / "nowhere", ["Dev"]) == 0


def test_restore_runs_only_for_a_mod_that_was_enabled(tmp_path):
    """One that never ran pinned nothing; the line may be the player's own."""
    game, cooking, mod = _install(tmp_path)
    state = apply_mods.State(cooking)
    state.set_enabled_mods([])
    assert apply_mods.restore_mod_options(mod, "seedy", game, state) == 0
    assert "Forced seed=12345" in _ini(game)
    state.set_enabled_mods(["seedy"])
    assert apply_mods.restore_mod_options(mod, "seedy", game, state) == 2
    assert "Forced seed" not in _ini(game)


def test_a_mod_flipped_off_since_the_last_apply_gets_its_options_cleared(tmp_path):
    game, cooking, mod = _install(tmp_path, enabled="false")
    state = apply_mods.State(cooking)
    state.set_enabled_mods(["seedy"])
    assert apply_mods.restore_flipped_options([apply_mods.Mod(mod)], state, game) == ["seedy"]
    assert "Forced seed" not in _ini(game) and "Dev=" not in _ini(game)
    # still enabled: nothing to undo
    game2, cooking2, mod2 = _install(tmp_path / "b")
    state2 = apply_mods.State(cooking2)
    state2.set_enabled_mods(["seedy"])
    assert apply_mods.restore_flipped_options([apply_mods.Mod(mod2)], state2, game2) == []
    assert "Forced seed=12345" in _ini(game2)


def test_uninstall_clears_the_options_before_removing_the_mod(tmp_path, monkeypatch, capsys):
    import json

    from rsmm.cli import json_bridge
    game, cooking, mod = _install(tmp_path)
    state = apply_mods.State(cooking)
    state.set_enabled_mods(["seedy"])
    state.save()
    monkeypatch.setattr(json_bridge, "MODS_DIR", mod.parent)
    monkeypatch.setattr(json_bridge, "find_game_dir", lambda: game)
    json_bridge.cmd_uninstall_mod("seedy")
    assert json.loads(capsys.readouterr().out)["removed"] is True
    assert not mod.exists()
    assert "Forced seed" not in _ini(game)


def test_lint_refuses_an_unknown_option(tmp_path, capsys):
    from rsmm.cli import lint
    _game, _c, mod = _install(tmp_path, restore='["Forced seed", "Turbo mode"]')
    errs, _warns = lint.lint_one(mod)
    out = capsys.readouterr().out
    assert errs >= 1 and "'Turbo mode' is not a game option" in out
    assert "'Forced seed' is not" not in out


def test_the_seed_pin_example_declares_its_options_instead_of_a_hook(capsys):
    from rsmm.cli import lint
    ex = _REPO / "examples" / "ExampleSeedPin"
    assert not (ex / "on_disable.py").exists()
    assert apply_mods.Mod(ex).restore_options == ["Forced seed", "Dev"]
    lint.lint_one(ex)
    assert "restore_options" not in capsys.readouterr().out


def test_clear_options_leaves_every_other_byte_alone(tmp_path):
    """CRLF endings and a non-UTF-8 byte in an unrelated line survive."""
    game, _c, _m = _install(tmp_path)
    before = (b"[Debug]\r\nForced seed=12345\r\nName=Caf\xe9\r\nDev=1\r\nTest=0\r\n"
              b"[Display]\r\nScreen shake=0")
    GS.settings_ini(game).write_bytes(before)
    assert GS.clear_options(game, ["Forced seed", "Dev"]) == 2
    assert GS.settings_ini(game).read_bytes() == (
        b"[Debug]\r\nName=Caf\xe9\r\nTest=0\r\n[Display]\r\nScreen shake=0")


def _boom(*_a, **_k):
    raise PermissionError(13, "locked")


def test_apply_cleanup_failure_warns_continues_and_retries(tmp_path, monkeypatch, capsys):
    game, cooking, mod = _install(tmp_path, enabled="false")
    state = apply_mods.State(cooking)
    state.set_enabled_mods(["seedy"])
    with monkeypatch.context() as mp:
        mp.setattr(GS, "clear_options", _boom)
        assert apply_mods.restore_flipped_options([apply_mods.Mod(mod)], state, game) == []
    err = capsys.readouterr().err
    assert "seedy" in err and "GameSettings.ini" in err
    assert "Forced seed=12345" in _ini(game)
    state.save()
    # a fresh State (next apply) still knows what to retry; the mod is no longer flipped
    state2 = apply_mods.State(cooking)
    state2.set_enabled_mods([])
    apply_mods.restore_flipped_options([apply_mods.Mod(mod)], state2, game)
    assert "Forced seed" not in _ini(game) and "Dev=" not in _ini(game)
    state2.save()
    assert not apply_mods.State(cooking).pending_option_restores


def test_uninstall_reports_a_failed_cleanup_and_keeps_the_mod(tmp_path, monkeypatch, capsys):
    import json

    from rsmm.cli import json_bridge
    game, cooking, mod = _install(tmp_path)
    state = apply_mods.State(cooking)
    state.set_enabled_mods(["seedy"])
    state.save()
    monkeypatch.setattr(json_bridge, "MODS_DIR", mod.parent)
    monkeypatch.setattr(json_bridge, "find_game_dir", lambda: game)
    monkeypatch.setattr(GS, "clear_options", _boom)
    json_bridge.cmd_uninstall_mod("seedy")
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["modId"] == "seedy"
    assert "seedy" in out["error"] and "GameSettings.ini" in out["error"]
    assert mod.exists()
