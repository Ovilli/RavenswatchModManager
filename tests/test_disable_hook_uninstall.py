"""`on_disable.py` has to actually run — frozen or not, disable or uninstall.

Two real failures are pinned here.

1. The frozen sidecar had no way to run a hook at all. `[sys.executable,
   "on_disable.py"]` is only an interpreter invocation in a source checkout;
   in the PyInstaller bundle `sys.executable` IS rsmm, so it became
   `rsmm on_disable.py` — unknown subcommand, exit 2, hook never executed —
   and the caller counted it as "ran". Every desktop user's mod cleanup was
   a no-op.

2. Uninstall deleted `mods/<id>/` without running the hook first, so a mod's
   runtime state (the reported case: a pinned `Forced seed` in
   `_Save/GameSettings.ini`) survived the mod that wrote it, with nothing
   left on disk to undo it.
"""

import sys
from pathlib import Path

import pytest

from rsmm.cli import apply_mods, cmd_run_hook
from rsmm.cli._dispatch import HOOK_RUNNER_VERB

# The hook a mod would ship: writes a marker so a test can prove it ran, and
# echoes the env contract it is promised.
HOOK_SRC = """\
import os, sys
from pathlib import Path

def main() -> int:
    Path(os.environ["RSMM_GAME_DIR"], "hook-ran.txt").write_text(
        os.environ["RSMM_MOD_DIR"], encoding="utf-8")
    print("cleaned up")
    return 0

if __name__ == "__main__":
    sys.exit(main())
"""


@pytest.fixture()
def install(tmp_path):
    game_dir = tmp_path / "game"
    cooking = game_dir / "DarkTalesResources" / "_Cooking"
    cooking.mkdir(parents=True)
    mod_root = tmp_path / "mods" / "seedy"
    mod_root.mkdir(parents=True)
    (mod_root / "manifest.toml").write_text(
        '[mod]\nid = "seedy"\nname = "Seedy"\nversion = "1.0.0"\nenabled = true\n',
        encoding="utf-8",
    )
    (mod_root / "on_disable.py").write_text(HOOK_SRC, encoding="utf-8")
    return game_dir, cooking, mod_root


def test_hook_argv_is_an_interpreter_call_in_source_mode(tmp_path):
    argv = apply_mods._hook_argv(tmp_path / "on_disable.py")
    assert argv == [sys.executable, str(tmp_path / "on_disable.py")]


def test_hook_argv_goes_back_through_rsmm_when_frozen(tmp_path, monkeypatch):
    """The frozen bundle has no interpreter to hand a .py to."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    argv = apply_mods._hook_argv(tmp_path / "on_disable.py")
    assert HOOK_RUNNER_VERB in argv
    assert str(tmp_path / "on_disable.py") in argv
    # The bare `[rsmm, script]` form is what silently did nothing.
    assert argv[:2] != [sys.executable, str(tmp_path / "on_disable.py")]


def test_hook_runner_executes_the_script(install, capsys):
    """The verb the frozen path routes to really runs the hook body."""
    game_dir, cooking, mod_root = install
    import os
    for k, v in (("RSMM_GAME_DIR", game_dir), ("RSMM_COOKING", cooking),
                 ("RSMM_MOD_DIR", mod_root)):
        os.environ[k] = str(v)
    try:
        rc = cmd_run_hook.main([str(mod_root / "on_disable.py")])
    finally:
        for k in ("RSMM_GAME_DIR", "RSMM_COOKING", "RSMM_MOD_DIR"):
            os.environ.pop(k, None)
    assert rc == 0
    assert (game_dir / "hook-ran.txt").read_text(encoding="utf-8") == str(mod_root)


def test_hook_runner_refuses_arbitrary_python(tmp_path, capsys):
    evil = tmp_path / "payload.py"
    evil.write_text("raise SystemExit(0)\n", encoding="utf-8")
    assert cmd_run_hook.main([str(evil)]) == 2
    assert "not a mod lifecycle hook" in capsys.readouterr().err


def test_run_disable_hook_runs_it(install):
    game_dir, cooking, mod_root = install
    r = apply_mods.run_disable_hook(mod_root, game_dir, cooking)
    assert r.returncode == 0, r.stderr
    assert (game_dir / "hook-ran.txt").is_file()
    assert "cleaned up" in r.stdout


def test_uninstall_runs_the_hook_for_an_enabled_mod(install):
    game_dir, cooking, mod_root = install
    state = apply_mods.State(cooking)
    state.set_enabled_mods(["seedy"])

    status, detail = apply_mods.run_uninstall_hook(
        mod_root, "seedy", game_dir, cooking, state)

    assert status == "ok", detail
    assert (game_dir / "hook-ran.txt").is_file()


def test_uninstall_skips_the_hook_for_a_mod_never_enabled(install):
    """Install-then-uninstall must not be an arbitrary-code path."""
    game_dir, cooking, mod_root = install
    state = apply_mods.State(cooking)
    state.set_enabled_mods([])

    status, detail = apply_mods.run_uninstall_hook(
        mod_root, "seedy", game_dir, cooking, state)

    assert status == "not-enabled"
    assert "seedy" in detail
    assert not (game_dir / "hook-ran.txt").exists()


def test_uninstall_reports_a_hook_that_failed(install):
    game_dir, cooking, mod_root = install
    (mod_root / "on_disable.py").write_text(
        "import sys\nsys.stderr.write('boom\\n')\nsys.exit(3)\n", encoding="utf-8")
    state = apply_mods.State(cooking)
    state.set_enabled_mods(["seedy"])

    status, detail = apply_mods.run_uninstall_hook(
        mod_root, "seedy", game_dir, cooking, state)

    assert status == "failed"
    assert "exited 3" in detail


def test_uninstall_is_quiet_when_the_mod_ships_no_hook(install):
    game_dir, cooking, mod_root = install
    (mod_root / "on_disable.py").unlink()
    state = apply_mods.State(cooking)
    state.set_enabled_mods(["seedy"])

    assert apply_mods.run_uninstall_hook(
        mod_root, "seedy", game_dir, cooking, state) == ("absent", "")


def test_apply_deactivation_runs_the_hook_end_to_end(install, capsys):
    """A mod flipping enabled -> disabled gets its cleanup, and `ran` means ran."""
    game_dir, cooking, mod_root = install
    (mod_root / "manifest.toml").write_text(
        '[mod]\nid = "seedy"\nname = "Seedy"\nversion = "1.0.0"\nenabled = false\n',
        encoding="utf-8",
    )
    mod = apply_mods.Mod(mod_root)
    state = apply_mods.State(cooking)
    state.set_enabled_mods(["seedy"])

    ran, missing = apply_mods._run_deactivation_hooks(
        [mod], state, game_dir, cooking, dry_run=False, assume_yes=True)

    assert ran == ["seedy"]
    assert missing == []
    assert (game_dir / "hook-ran.txt").is_file()


def test_apply_does_not_count_a_broken_hook_as_run(install, capsys):
    game_dir, cooking, mod_root = install
    (mod_root / "manifest.toml").write_text(
        '[mod]\nid = "seedy"\nname = "Seedy"\nversion = "1.0.0"\nenabled = false\n',
        encoding="utf-8",
    )
    (mod_root / "on_disable.py").write_text("import sys; sys.exit(4)\n", encoding="utf-8")
    mod = apply_mods.Mod(mod_root)
    state = apply_mods.State(cooking)
    state.set_enabled_mods(["seedy"])

    ran, missing = apply_mods._run_deactivation_hooks(
        [mod], state, game_dir, cooking, dry_run=False, assume_yes=True)

    assert ran == []
    assert missing == ["seedy"]
    assert "exited 4" in capsys.readouterr().err


def test_intents_uninstall_runs_the_hook_before_deleting(install):
    """The in-game menu's uninstall is the same deletion, same requirement."""
    from rsmm.cli import cmd_intents

    game_dir, cooking, mod_root = install
    state = apply_mods.State(cooking)
    state.set_enabled_mods(["seedy"])
    # This path re-reads state from disk (apply is what persists it), so the
    # "was it ever enabled" gate only sees a saved file.
    state.save()

    assert cmd_intents.uninstall_mod(mod_root.parent, "seedy", game_dir) == "ok"
    assert not mod_root.exists()
    assert (game_dir / "hook-ran.txt").is_file()
