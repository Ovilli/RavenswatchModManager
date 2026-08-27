"""`rsmm log` — the archived-run surface, and what must survive a restore.

Rotation used to be one rename onto `_log.prev.txt`, so every launch destroyed
the run before last: reproduce a bug, relaunch to test the fix, and the log you
needed was already gone. The loader now copies each finished run into
`<game>/rsmm/logs/`; these tests cover the reader side and the one thing that
would silently undo it — `restore` clearing that directory.
"""

from __future__ import annotations

from rsmm.cli import apply_mods, cmd_log


def _mk(game: str | object, name: str, text: str = "x\n"):
    from pathlib import Path
    d = Path(game) / "rsmm" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(text)
    return p


def test_archived_runs_are_newest_first_by_name(tmp_path):
    """Ordering must come from the NAME, not mtime.

    The filename leads with the run's own start stamp, while the file is copied
    at the start of the FOLLOWING run — so mtime ordering can disagree with the
    order the runs actually happened in.
    """
    import os

    old = _mk(tmp_path, "2026-08-14_101500_aaaa.log")
    new = _mk(tmp_path, "2026-08-16_162321_fd1d.log")
    # Give the OLDER run the NEWER mtime, i.e. the case mtime gets wrong.
    os.utime(old, (2 << 30, 2 << 30))
    os.utime(new, (1 << 30, 1 << 30))

    runs = cmd_log.archived_runs(tmp_path)
    assert [p.name for p in runs] == [new.name, old.name]


def test_list_and_run_read_the_archive(tmp_path, capsys):
    _mk(tmp_path, "2026-08-16_162321_fd1d.log", "== SESSION fd1d\nhello\n")
    _mk(tmp_path, "2026-08-14_101500_aaaa.log", "== SESSION aaaa\nolder\n")

    assert cmd_log.main(["--list", "--game-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "2026-08-16_162321_fd1d.log" in out and "2 archived run(s)" in out

    # A unique PREFIX is enough — nobody wants to type the whole stamp.
    assert cmd_log.main(["--run", "2026-08-14", "--all",
                         "--game-dir", str(tmp_path)]) == 0
    assert "older" in capsys.readouterr().out


def test_run_reports_no_match_and_ambiguity_instead_of_guessing(tmp_path, capsys):
    _mk(tmp_path, "2026-08-16_162321_fd1d.log")
    _mk(tmp_path, "2026-08-16_180000_bbbb.log")

    assert cmd_log.main(["--run", "nope", "--game-dir", str(tmp_path)]) == 1
    assert "no archived run" in capsys.readouterr().err

    # A prefix matching both must NOT silently pick one.
    assert cmd_log.main(["--run", "2026-08-16", "--game-dir", str(tmp_path)]) == 1
    assert "matches 2 runs" in capsys.readouterr().err


def test_restore_keeps_the_archived_logs(tmp_path):
    """`restore --all` clears <game>/rsmm wholesale. It must spare the logs.

    The documented iteration loop is restore -> apply -> install-loader, so an
    rmtree here deletes the archive exactly when it is being relied on.
    """
    game = tmp_path
    (game / "rsmm" / "data").mkdir(parents=True)
    (game / "rsmm" / "data" / "function_patterns.json").write_text("{}")
    (game / "rsmm" / "lib").mkdir()
    (game / "rsmm" / "lib" / "rsmm.lua").write_text("-- sdk")
    kept = _mk(game, "2026-08-16_162321_fd1d.log", "keep me\n")

    assert apply_mods.clear_loader_artifacts(game) == 1
    assert not (game / "rsmm" / "lib").exists(), "loader runtime is still cleared"
    assert not (game / "rsmm" / "data").exists()
    assert kept.read_text() == "keep me\n", "the archived run survived"


def test_restore_removes_the_rsmm_dir_when_there_is_no_archive(tmp_path):
    """No logs to keep means the directory should still go, as before."""
    game = tmp_path
    (game / "rsmm" / "lib").mkdir(parents=True)
    (game / "rsmm" / "lib" / "rsmm.lua").write_text("-- sdk")

    assert apply_mods.clear_loader_artifacts(game) == 1
    assert not (game / "rsmm").exists()


def test_install_loader_refuses_a_non_compiling_sdk(tmp_path, monkeypatch):
    """A syntax error in the SDK is not a degraded feature — it makes
    `require "rsmm"` raise for every mod. install-loader must not plant it.

    One `local` too many (the main chunk sits at Lua's 200-local ceiling) was
    planted on 2026-08-16 and would have bricked the next launch; it was caught
    only because the same command happened to be run twice by hand.
    """
    import shutil as _shutil

    import pytest

    from rsmm.cli import install_loader

    if not any(_shutil.which(c) for c in ("luac5.4", "luac5.3", "luac")):
        pytest.skip("no luac on PATH")

    lib = tmp_path / "src" / "loader" / "lib"
    lib.mkdir(parents=True)
    monkeypatch.setattr(install_loader, "REPO_ROOT", tmp_path)

    (lib / "ok.lua").write_text("local a = 1\nreturn a\n")
    assert install_loader._lua_syntax_gate() is True

    (lib / "broken.lua").write_text("local x = = 1\n")
    assert install_loader._lua_syntax_gate() is False


# --- severity ---------------------------------------------------------------

def test_line_severity_reads_the_loader_tag():
    """`Loader::log_err` / `log_warn` stamp the severity BEFORE the subsystem
    tag, so both survive and `[subsystem]` stays where readers look for it."""
    from rsmm.cli.cmd_log import line_severity

    stamp = "[2026-08-27 12:00:00.123 ab12 42]"
    assert line_severity(f"{stamp} [err] [ui-hook] resolve failed") == "err"
    assert line_severity(f"{stamp} [warn] flags parse error") == "warn"
    assert line_severity(f"{stamp} [va-gate] fine") is None
    # Unclassified means unclassified — a message that merely says "failed"
    # must not be promoted, or the filter fills up with noise again.
    assert line_severity(f"{stamp} [lua] mod said: failed") is None
    assert line_severity("== SESSION ab12 ==") is None


def test_style_line_keeps_both_tokens_and_adds_no_characters(monkeypatch):
    """Colouring must be in place: the log tab aligns on the plain text."""
    import re

    from rsmm.cli import cmd_log

    monkeypatch.setattr(cmd_log._ST, "enabled", True, raising=False)
    raw = "[2026-08-27 12:00:00.123 ab12 42] [err] [ui-hook] resolve failed"
    styled = cmd_log._style_line(raw)
    assert re.sub(r"\x1b\[[0-9;]*m", "", styled) == raw


def test_errors_filter_keeps_session_banners(tmp_path, monkeypatch, capsys):
    """An error with no run attached to it is not much use, so the banners
    survive the filter even though they carry no severity."""
    from rsmm.cli import cmd_log

    game = tmp_path / "game"
    (game / "mods").mkdir(parents=True)
    stamp = "[2026-08-27 12:00:00.123 ab12 42]"
    (game / "mods" / "_log.txt").write_text(
        "== SESSION ab12 ==\n"
        f"{stamp} [va-gate] quiet\n"
        f"{stamp} [err] [ui-hook] resolve failed\n"
        f"{stamp} [warn] odd\n"
    )
    monkeypatch.setenv("NO_COLOR", "1")
    assert cmd_log.main(["--errors", "--game-dir", str(game)]) == 0
    out = capsys.readouterr().out
    assert "resolve failed" in out
    assert "odd" in out
    assert "quiet" not in out
    assert "== SESSION" in out
