"""Terminal-mode handoff between the raw TUI and the subcommands it runs.

Both bugs these cover produced the same user-visible symptom — "I press apply
and the whole UI breaks" — and neither was catchable by asserting on printed
text, because the damage is in termios/DEC-mode state, not in the output.

Runs against a real pty; skipped where termios is unavailable (Windows).
"""

from __future__ import annotations

import os
import sys

import pytest

termios = pytest.importorskip("termios")
tty = pytest.importorskip("tty")
pty = pytest.importorskip("pty")

from rsmm.cli import _keys, cmd_shell  # noqa: E402  (must come after the importorskip gate)

# (name, termios attribute index) for the flags cooked output/input needs.
_IFLAG, _OFLAG, _LFLAG = 0, 1, 3
_COOKED_FLAGS = (
    ("OPOST", _OFLAG),    # without it print()'s LF has no CR -> stair-stepping
    ("ONLCR", _OFLAG),
    ("ICRNL", _IFLAG),    # without it Enter arrives as CR and input() hangs
    ("ISIG", _LFLAG),     # without it ctrl-c does nothing
    ("ECHO", _LFLAG),
    ("ICANON", _LFLAG),
)


@pytest.fixture()
def fake_tty(monkeypatch):
    """Give the module under test a real pty as stdin."""
    primary, secondary = pty.openpty()

    class _Stdin:
        def fileno(self):
            return secondary

        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", _Stdin())
    try:
        yield secondary
    finally:
        os.close(primary)
        os.close(secondary)


def _flags(fd) -> dict[str, bool]:
    attrs = termios.tcgetattr(fd)
    return {name: bool(attrs[idx] & getattr(termios, name))
            for name, idx in _COOKED_FLAGS}


def test_suspend_raw_restores_every_cooked_flag(fake_tty, monkeypatch):
    """The regression: _suspend_raw used to OR only ECHO|ICANON back into the
    RAW attrs, so OPOST/ICRNL/ISIG stayed off and apply/restore output
    stair-stepped down a terminal where ctrl-c no longer worked."""
    monkeypatch.setattr(sys.stdout, "write", lambda *_a: None)
    monkeypatch.setattr(sys.stdout, "flush", lambda: None)

    before = _flags(fake_tty)
    assert all(before.values()), "pty should start in cooked mode"

    saved = termios.tcgetattr(fake_tty)
    tty.setraw(fake_tty)
    monkeypatch.setattr(_keys, "_PRE_RAW", saved)
    assert not _flags(fake_tty)["OPOST"], "setraw should have cleared OPOST"

    with cmd_shell._suspend_raw():
        inside = _flags(fake_tty)

    missing = [n for n, on in inside.items() if not on]
    assert not missing, f"not restored to cooked mode inside _suspend_raw: {missing}"


def test_suspend_raw_is_cooked_even_without_a_published_pre_raw(fake_tty, monkeypatch):
    """The fallback path (no raw_session on the stack) must still be usable."""
    monkeypatch.setattr(sys.stdout, "write", lambda *_a: None)
    monkeypatch.setattr(sys.stdout, "flush", lambda: None)
    tty.setraw(fake_tty)
    monkeypatch.setattr(_keys, "_PRE_RAW", None)

    with cmd_shell._suspend_raw():
        missing = [n for n, on in _flags(fake_tty).items() if not on]
    assert not missing, f"fallback left the terminal half-raw: {missing}"


def test_suspend_raw_disables_every_mouse_mode_raw_session_enabled(monkeypatch):
    """1003 (all-motion) used to be enabled by raw_session but NOT disabled
    here, so during apply every mouse move sprayed escapes onto the echoing
    terminal and into the [enter] prompt."""
    written: list[str] = []
    monkeypatch.setattr(sys.stdout, "write", written.append)
    monkeypatch.setattr(sys.stdout, "flush", lambda: None)
    monkeypatch.setattr(cmd_shell, "termios", None)      # skip the termios half

    with cmd_shell._suspend_raw():
        pass

    enabled = set(_modes(_keys._MOUSE_ON, "h"))
    disabled = set(_modes("".join(written), "l"))
    assert enabled <= disabled, f"left enabled during a subcommand: {enabled - disabled}"


def _modes(text: str, suffix: str) -> list[str]:
    import re
    return re.findall(rf"\033\[\?(\d+){suffix}", text)


def test_raw_session_publishes_and_clears_pre_raw(fake_tty, monkeypatch):
    monkeypatch.setattr(sys.stdout, "write", lambda *_a: None)
    monkeypatch.setattr(sys.stdout, "flush", lambda: None)
    monkeypatch.setattr(_keys, "_PRE_RAW", None)

    cooked = termios.tcgetattr(fake_tty)
    with _keys.raw_session():
        assert _keys._PRE_RAW == cooked, "cooked attrs not published"
    assert _keys._PRE_RAW is None, "_PRE_RAW outlived its raw session"


def test_pause_drains_stdin_before_prompting(fake_tty, monkeypatch):
    """Bytes typed (or sprayed by the mouse) during a long apply must not be
    consumed as the answer to the [enter] prompt."""
    primary = os.openpty()[0]  # noqa: F841 - keep a pty pair alive for realism
    monkeypatch.setattr("builtins.input", lambda *_a: "")
    drained: list[bool] = []
    monkeypatch.setattr(cmd_shell, "_drain_stdin", lambda: drained.append(True))

    assert cmd_shell._pause("back to mods") is True
    assert drained, "_pause prompted without draining the input queue first"


def test_pause_reports_interrupt_so_callers_can_still_leave(monkeypatch):
    """ctrl-c at the menu prompt meant "quit" before _pause existed; keep it."""
    monkeypatch.setattr(cmd_shell, "_drain_stdin", lambda: None)

    def boom(*_a):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", boom)
    assert cmd_shell._pause("back to menu") is False
