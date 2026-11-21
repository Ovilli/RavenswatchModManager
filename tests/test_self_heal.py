"""The start-up self-heal restores a left-behind modded install ONLY when safe.

Each safeguard gets a test that it alone stops the restore; the happy path and
the two races (a launch, or the game, starting during the checks) close it.
"""

from __future__ import annotations

import json

import pytest

from rsmm.cli import self_heal as SH
from rsmm.cli import watch_restore as W
from rsmm.engine import game_proc, steam_app
from rsmm.engine.paths import COOKING_REL


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A game left modded by a launch, with every safeguard passing."""
    game = tmp_path / "steamapps" / "common" / "Ravenswatch"
    cooking = game / COOKING_REL
    cooking.mkdir(parents=True)
    (cooking / ".rsmm_state.json").write_text(json.dumps({
        "version": 1, "applied_for": "launch", "steam_buildid": "100",
        "active": {"enc\\a": {"mod": "m", "src_sha256": "x", "orig_sha256": "y"}},
    }))
    restores: list = []

    def fake_restore(args, repo, cook, gd):
        restores.append(gd)
        return env_state["restore_code"]

    env_state = {"restore_code": 0, "restores": restores}
    from rsmm.cli import apply_mods as A
    monkeypatch.setattr(A, "cmd_restore_all", fake_restore)
    monkeypatch.setattr(A, "_protect_save_items", lambda *_a: None)
    monkeypatch.setattr(W, "watcher_alive", lambda: False)
    monkeypatch.setattr(W, "launch_generation_age", lambda: None)
    monkeypatch.setattr(game_proc, "probe_game", lambda: False)
    monkeypatch.setattr(SH.time, "sleep", lambda _s: None)
    env_state["game"] = game
    env_state["cooking"] = cooking
    return env_state


def _heal(env, **kw):
    return SH.heal(env["game"], **kw)


def _state(env, **changes):
    p = env["cooking"] / ".rsmm_state.json"
    data = json.loads(p.read_text())
    data.update(changes)
    p.write_text(json.dumps(data))


def test_restores_what_a_launch_left_behind(env):
    out = _heal(env)
    assert out["action"] == "restored" and out["ok"] and out["code"] == 0
    assert env["restores"] == [env["game"]]


def test_residue_is_reported_but_still_counts_as_restored(env):
    env["restore_code"] = 2
    out = _heal(env)
    assert out["action"] == "restored" and out["code"] == 2
    assert "could not be restored" in out["detail"]


def test_a_failed_restore_is_not_ok(env):
    env["restore_code"] = 1
    out = _heal(env)
    assert out["ok"] is False and out["reason"] == "restore-failed"


def test_nothing_applied_is_left_alone(env):
    _state(env, active={})
    out = _heal(env)
    assert out["reason"] == "clean" and env["restores"] == []


def test_lua_only_leftovers_still_count(env):
    _state(env, active={})
    (env["game"] / "mods" / "some-mod").mkdir(parents=True)
    assert _heal(env)["action"] == "restored"


def test_loader_files_alone_are_not_leftovers(env):
    _state(env, active={})
    (env["game"] / "mods").mkdir()
    (env["game"] / "mods" / "_log.txt").write_text("log")
    assert _heal(env)["reason"] == "clean"


@pytest.mark.parametrize("applied_for", ["manual", None])
def test_an_explicit_or_unrecorded_apply_is_never_undone(env, applied_for):
    _state(env, applied_for=applied_for)
    out = _heal(env)
    assert out["reason"] == "manual" and env["restores"] == []


def test_a_live_watcher_restores_itself(env, monkeypatch):
    monkeypatch.setattr(W, "watcher_alive", lambda: True)
    assert _heal(env)["reason"] == "watcher" and env["restores"] == []


def test_a_recent_launch_is_left_to_its_watcher(env, monkeypatch):
    monkeypatch.setattr(W, "launch_generation_age", lambda: 30.0)
    assert _heal(env)["reason"] == "recent-launch"
    monkeypatch.setattr(W, "launch_generation_age", lambda: 3600.0)
    assert _heal(env)["action"] == "restored"


@pytest.mark.parametrize("probe,reason", [(True, "game-running"), (None, "probe-failed")])
def test_game_running_or_unknown_never_restores(env, monkeypatch, probe, reason):
    monkeypatch.setattr(game_proc, "probe_game", lambda: probe)
    assert _heal(env)["reason"] == reason and env["restores"] == []


def test_every_probe_must_say_not_running(env, monkeypatch):
    seq = iter([False, False, None])
    monkeypatch.setattr(game_proc, "probe_game", lambda: next(seq, False))
    assert _heal(env)["reason"] == "probe-failed"


def test_steam_writing_the_game_blocks_it(env, monkeypatch):
    monkeypatch.setattr(steam_app, "app_state",
                        lambda _g: steam_app.AppState("100", 1026))
    assert _heal(env)["reason"] == "steam-busy" and env["restores"] == []


def test_a_new_steam_build_blocks_it(env, monkeypatch):
    """A data-only patch leaves rsmm's fingerprint alone: the pre-patch backups
    would go over the patched files. The build id is what catches it."""
    monkeypatch.setattr(steam_app, "app_state",
                        lambda _g: steam_app.AppState("101", 4))
    assert _heal(env)["reason"] == "game-updated" and env["restores"] == []
    monkeypatch.setattr(steam_app, "app_state",
                        lambda _g: steam_app.AppState("100", 4))
    assert _heal(env)["action"] == "restored"


def test_a_launch_that_starts_during_the_checks_wins(env, monkeypatch):
    gens = iter(["g1", "g2"])                    # read before the lock, then inside it
    monkeypatch.setattr(W, "read_launch_generation", lambda: next(gens))
    assert _heal(env)["reason"] == "recent-launch" and env["restores"] == []


def test_the_game_starting_during_the_checks_wins(env, monkeypatch):
    seq = iter([False, False, False, True])      # three checks, then inside the lock
    monkeypatch.setattr(game_proc, "probe_game", lambda: next(seq))
    assert _heal(env)["reason"] == "game-running" and env["restores"] == []


def test_a_held_install_lock_skips(env):
    from rsmm.engine.safeio import install_lock

    with install_lock(env["cooking"], "apply"):
        assert _heal(env)["reason"] == "busy"
    assert env["restores"] == []


def test_steam_manifest_is_read(tmp_path):
    game = tmp_path / "steamapps" / "common" / "Ravenswatch"
    game.mkdir(parents=True)
    (tmp_path / "steamapps" / "appmanifest_2071280.acf").write_text(
        '"AppState"\n{\n\t"appid"\t\t"2071280"\n\t"StateFlags"\t\t"4"\n'
        '\t"installdir"\t\t"Ravenswatch"\n\t"buildid"\t\t"21234567"\n}\n')
    st = steam_app.app_state(game)
    assert st == steam_app.AppState("21234567", 4) and not st.steam_busy
    assert steam_app.app_state(tmp_path / "elsewhere" / "x" / "y") is None
