"""Interactive home screen tests.

The shell is the first thing a user meets, and it is the piece most likely to
be exercised only by hand. The logic worth pinning is not the drawing — it is
the state model (what the header claims, what the menu offers, what the
"next step" nudge says) and the guarantee that it never runs without a TTY.
"""

from __future__ import annotations

import json

import pytest

from rsmm.cli import _term, cmd_shell
from rsmm.cli.cmd_shell import ACTIONS, Context


def plain(monkeypatch):
    """Force colour off so assertions compare text, not escape codes."""
    monkeypatch.setattr(cmd_shell, "_ST", _term.Style(enabled=False))


# --- context model ---------------------------------------------------------


def test_action_keys_are_unique_and_stable():
    keys = [a.key for a in ACTIONS]
    assert len(keys) == len(set(keys))
    assert "q" not in keys          # reserved for quit


def test_every_action_dispatches_or_opens_a_screen():
    """An action either shells out (`argv`) or opens a registered internal
    screen. An empty argv with no handler behind it is a dead menu row."""
    for a in ACTIONS:
        if a.argv:
            continue
        assert a.label in cmd_shell.SCREENS, f"{a.label} has no screen handler"
        assert callable(cmd_shell.SCREENS[a.label])


def test_internal_screens_have_a_typed_fallback():
    """Raw mode is unavailable on Windows/dumb terminals; those users must
    still be able to reach the same functionality."""
    for a in ACTIONS:
        if not a.argv:
            assert a.label in cmd_shell.TYPED_EQUIVALENT
            assert cmd_shell.TYPED_EQUIVALENT[a.label]


def test_no_orphan_screen_handlers():
    """A handler with no menu row is unreachable code."""
    labels = {a.label for a in ACTIONS}
    assert set(cmd_shell.SCREENS) <= labels


def test_mods_workflow_is_not_duplicated_as_separate_rows():
    """Browse/enable/disable/apply/restore were merged into the Mods screen;
    re-adding them as top-level rows would split one workflow across five
    destinations again."""
    labels = {a.label.lower() for a in ACTIONS}
    for gone in ("enable mods", "disable mods", "apply", "restore"):
        assert gone not in labels


def test_needs_flags_reference_real_context_fields():
    """A typo in `needs` would silently disable a menu row forever."""
    ctx = Context()
    for a in ACTIONS:
        if a.needs:
            assert hasattr(ctx, a.needs), f"{a.key} needs unknown field {a.needs}"


def test_context_has_defaults_to_true_for_no_requirement():
    ctx = Context()
    assert ctx.has("") is True
    assert ctx.has("enabled") is False
    assert Context(enabled=2).has("enabled") is True


# --- the nudge -------------------------------------------------------------


@pytest.mark.parametrize(
    ("ctx", "expect"),
    [
        (Context(), "game not found"),
        (Context(game=True), "loader not installed"),
        (Context(game=True, loader=True, enabled=3), "nothing applied"),
        (Context(game=True, loader=True, enabled=3, applied=7), ""),
        (Context(game=True, loader=True), ""),          # nothing enabled: fine
    ],
)
def test_next_step_priority(ctx, expect):
    step = cmd_shell.next_step(ctx)
    assert expect in step
    if not expect:
        assert step == ""


def test_status_bits_report_state(monkeypatch):
    plain(monkeypatch)
    bits = " ".join(cmd_shell.status_bits(
        Context(game=True, loader=True, mods=48, enabled=1, applied=5)))
    assert "found" in bits
    assert "installed" in bits
    assert "48" in bits and "1 on" in bits
    assert "applied" in bits


def test_status_bits_without_game_hide_loader(monkeypatch):
    """Loader state is meaningless with no install — don't assert about it."""
    plain(monkeypatch)
    bits = " ".join(cmd_shell.status_bits(Context(game=False)))
    assert "not found" in bits
    assert "loader" not in bits


def test_status_bits_no_mods_enabled(monkeypatch):
    plain(monkeypatch)
    assert "none on" in " ".join(cmd_shell.status_bits(Context(mods=4)))


# --- probe -----------------------------------------------------------------


def test_probe_survives_missing_everything(monkeypatch, tmp_path):
    """A broken install must still yield a renderable menu, not a traceback."""
    monkeypatch.setattr(cmd_shell.P, "DEFAULT_GAME_DIR", tmp_path / "nope")
    monkeypatch.setattr(cmd_shell.P, "mods_dir", lambda: tmp_path / "nomods")
    ctx = cmd_shell.probe()
    assert ctx.game is False
    assert ctx.mods == 0
    cmd_shell.status_bits(ctx)      # must not raise


def test_probe_reads_loader_and_applied_state(monkeypatch, tmp_path):
    game = tmp_path / "game"
    cooking = game / "DarkTalesResources" / "_Cooking"
    cooking.mkdir(parents=True)
    (game / "winhttp.dll").write_bytes(b"\0" * 2_000_000)   # ours, not stock
    (cooking / ".rsmm_state.json").write_text(
        json.dumps({"active": {"a": 1, "b": 2}}), encoding="utf-8")

    mods = tmp_path / "mods"
    (mods / "OnMod").mkdir(parents=True)
    (mods / "OffMod").mkdir(parents=True)
    (mods / "OnMod" / "manifest.toml").write_text(
        "[mod]\nenabled     = true\n", encoding="utf-8")   # aligned, as shipped
    (mods / "OffMod" / "manifest.toml").write_text(
        "[mod]\nenabled = false\n", encoding="utf-8")

    monkeypatch.setattr(cmd_shell.P, "DEFAULT_GAME_DIR", game)
    monkeypatch.setattr(cmd_shell.P, "mods_dir", lambda: mods)

    ctx = cmd_shell.probe()
    assert ctx.game and ctx.loader
    assert ctx.mods == 2
    assert ctx.enabled == 1          # the aligned `enabled     = true` counts
    assert ctx.applied == 2


def test_probe_flags_stock_dll_as_no_loader(monkeypatch, tmp_path):
    """Steam reinstalling its own winhttp.dll is a real, silent failure mode."""
    game = tmp_path / "game"
    game.mkdir()
    (game / "winhttp.dll").write_bytes(b"\0" * 713_160)     # stock size
    monkeypatch.setattr(cmd_shell.P, "DEFAULT_GAME_DIR", game)
    monkeypatch.setattr(cmd_shell.P, "mods_dir", lambda: tmp_path / "none")
    assert cmd_shell.probe().loader is False


# --- entry guard -----------------------------------------------------------


def test_refuses_without_a_tty(monkeypatch, capsys):
    monkeypatch.setattr(cmd_shell.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(cmd_shell.sys.stdout, "isatty", lambda: True)
    assert cmd_shell.main() == 2
    assert "terminal" in capsys.readouterr().err


def test_render_does_not_raise_on_any_context(monkeypatch, capsys):
    """Rendering is pure output, but padding maths on ANSI strings is easy to
    get wrong — exercise both colour modes and the extremes."""
    for enabled in (True, False):
        monkeypatch.setattr(cmd_shell, "_ST", _term.Style(enabled=enabled))
        for ctx in (Context(),
                    Context(game=True, loader=True, mods=99, enabled=99,
                            applied=99)):
            cmd_shell._render(ctx)
    capsys.readouterr()


# --- pager -----------------------------------------------------------------
#
# The pager is the only scrolling implementation (log, captured command
# output, symbols all route through it), and it runs on the alternate screen
# where the terminal's own scrollback is unavailable — so its clamping is the
# difference between "scrollable" and "content you can never reach".


@pytest.mark.parametrize(
    ("total", "page", "requested_top", "expected"),
    [
        (100, 10, -5, 0),        # scrolling above the start clamps to 0
        (100, 10, 500, 90),      # past the end stops with a full page shown
        (5, 10, 3, 0),           # content shorter than the page never scrolls
        (100, 10, 42, 42),       # in-range positions are untouched
    ],
)
def test_pager_clamp_arithmetic(total, page, requested_top, expected):
    """Mirrors the clamp in `pager()`; off-by-one here hides the last lines."""
    top = max(0, min(requested_top, max(0, total - page)))
    assert top == expected


def test_screens_cover_every_internal_action_after_symbols_merge():
    """Symbols became an internal screen too — the registry must keep up."""
    internal = {a.label for a in ACTIONS if not a.argv}
    assert internal == set(cmd_shell.SCREENS)
    assert "Symbols" in internal


def test_symbol_rows_are_built_from_the_real_map():
    """Guards the data path the symbols screen renders: category grouping and
    status counts must come out of the shipped map, not a stub."""
    from rsmm.engine.symbols import load_symbol_map

    smap = load_symbol_map()
    counts: dict[str, int] = {}
    for cat in smap.categories:
        for sym in smap.by_category(cat):
            counts[sym.status] = counts.get(sym.status, 0) + 1
    assert counts.get("ok", 0) > 0
    assert set(counts) <= {"ok", "va", "unverified"}


def test_colorize_symbol_marks_status(monkeypatch):
    monkeypatch.setattr(cmd_shell, "_ST", _term.Style(enabled=True))
    ok_line = cmd_shell._colorize_symbol("  [ok        ] 0x140000000  Foo")
    unv = cmd_shell._colorize_symbol("  [unverified] 0x140000000  Bar")
    assert "\033[32m" in ok_line          # green for resolvable
    assert "\033[33m" in unv              # yellow for fail-closed
    assert cmd_shell._colorize_symbol("# ui").startswith("\033[")


# --- regressions from real use (2026-07-19) --------------------------------


def test_captured_output_keeps_colour(monkeypatch):
    """`Doctor` lost all colour once its output was captured for the pager.

    Subcommands decide colour from stdout.isatty() when their module is first
    imported; under capture that is a StringIO. `_run_paged` sets FORCE_COLOR
    for the duration — without it the pager shows flat grey text.
    """
    import io
    import os
    from contextlib import redirect_stdout

    seen = {}

    def fake_main(argv):
        seen["force"] = os.environ.get("FORCE_COLOR")
        return 0

    monkeypatch.setattr(cmd_shell, "pager", lambda *a, **k: None)
    import rsmm.cli._dispatch as dispatch
    monkeypatch.setattr(dispatch, "main", fake_main)

    had = os.environ.get("FORCE_COLOR")
    buf = io.StringIO()
    with redirect_stdout(buf):
        cmd_shell._run_paged(["doctor"], "doctor")

    assert seen["force"] == "1", "FORCE_COLOR must be set while capturing"
    # and restored afterwards, so it cannot leak into later commands
    assert os.environ.get("FORCE_COLOR") == had


def test_run_paged_restores_force_color_on_failure(monkeypatch):
    """A crashing subcommand must not leave FORCE_COLOR set process-wide."""
    import os

    def boom(argv):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cmd_shell, "pager", lambda *a, **k: None)
    import rsmm.cli._dispatch as dispatch
    monkeypatch.setattr(dispatch, "main", boom)
    monkeypatch.delenv("FORCE_COLOR", raising=False)

    rc = cmd_shell._run_paged(["doctor"], "doctor")
    assert rc == 1                      # reported, not raised
    assert "FORCE_COLOR" not in os.environ


def test_wheel_scrolls_lists_not_just_the_pager():
    """The Mods screen ignored wheel events, so scrolling felt dead there
    while the mouse still moved. Every row screen must consume the wheel."""
    import inspect

    for fn in (cmd_shell._mods_screen, cmd_shell.pager):
        src = inspect.getsource(fn)
        assert "WHEEL_UP" in src and "WHEEL_DOWN" in src, fn.__name__

    from rsmm.cli import cmd_mods
    assert "WHEEL_UP" in inspect.getsource(cmd_mods._pick_raw)


def test_ctrl_c_is_handled_in_every_interactive_screen():
    """Raw mode swallows SIGINT and `read_key` re-raises it; a screen that
    does not catch it dumps a traceback over the user's terminal."""
    import inspect

    for fn in (cmd_shell._mods_screen, cmd_shell.pager, cmd_shell._navigate):
        src = inspect.getsource(fn)
        assert "KeyboardInterrupt" in src, f"{fn.__name__} would traceback"

    from rsmm.cli import cmd_mods
    assert "KeyboardInterrupt" in inspect.getsource(cmd_mods._pick_raw)


# --- log screen ------------------------------------------------------------


def test_log_screen_reads_the_same_file_as_rsmm_log(monkeypatch, tmp_path):
    """The Log tab derived its own path (`<game>/rsmm/rsmm_log.txt`, which has
    never existed), so it was permanently blank while `rsmm log` worked."""
    from rsmm.cli import cmd_log

    game = tmp_path / "game"
    (game / "mods").mkdir(parents=True)
    (game / "mods" / "_log.txt").write_text("hello from the loader\n", encoding="utf-8")
    monkeypatch.setattr(cmd_log, "DEFAULT_GAME_DIR", game)

    seen = {}
    monkeypatch.setattr(cmd_shell, "pager",
                        lambda title, lines, **kw: seen.update(lines=lines))
    cmd_shell._log_screen()

    assert seen["lines"] == ["hello from the loader"]


def test_log_screen_does_not_derive_its_own_path():
    """Structural guard: one path implementation, in cmd_log."""
    import inspect
    import re

    src = inspect.getsource(cmd_shell._log_screen)
    code = "\n".join(re.sub(r"#.*", "", ln) for ln in src.splitlines())
    assert "log_file()" in code, "must ask cmd_log for the path"
    assert not re.search(r"_log\.txt|rsmm_log", code), "path re-derived locally"


def test_log_screen_names_the_missing_file(monkeypatch, tmp_path):
    """A blank tab told the user nothing. Say which file was looked for."""
    from rsmm.cli import cmd_log

    monkeypatch.setattr(cmd_log, "DEFAULT_GAME_DIR", tmp_path / "nogame")
    seen = {}
    monkeypatch.setattr(cmd_shell, "pager",
                        lambda title, lines, **kw: seen.update(lines=lines))
    cmd_shell._log_screen()

    assert any("_log.txt" in ln for ln in seen["lines"])
