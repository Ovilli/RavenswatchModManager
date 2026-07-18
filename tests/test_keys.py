"""Raw-input parsing tests.

Parsing is done byte-at-a-time against a real terminal stream, so the cases
that matter are the ambiguous ones: a release must not fire a second action, a
drag must not be mistaken for a click, and an unknown escape must not swallow
the rest of the input.
"""

from __future__ import annotations

import io
import sys

import pytest

from rsmm.cli import _keys


def feed(seq: str, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(seq))
    return _keys.read_key()


@pytest.mark.parametrize(
    ("seq", "expected"),
    [
        ("\033[A", (_keys.UP,)),
        ("\033[B", (_keys.DOWN,)),
        ("\033[5~", (_keys.PGUP,)),
        ("\033[6~", (_keys.PGDN,)),
        ("\033[H", (_keys.HOME,)),
        ("\033[F", (_keys.END,)),
        ("\r", (_keys.ENTER,)),
        ("\n", (_keys.ENTER,)),
        ("\x7f", (_keys.BACKSPACE,)),
        ("q", ("q",)),
        (" ", (" ",)),
    ],
)
def test_key_sequences(seq, expected, monkeypatch):
    assert feed(seq, monkeypatch) == expected


@pytest.mark.parametrize(
    ("seq", "expected"),
    [
        ("\033[<0;10;7M", ("click", 10, 7)),
        ("\033[<35;10;7M", (_keys.MOTION, 10, 7)),      # hover, no button
        ("\033[<32;10;7M", (_keys.MOTION, 10, 7)),      # drag
        ("\033[<64;10;7M", (_keys.WHEEL_UP, 10, 7)),
        ("\033[<65;10;7M", (_keys.WHEEL_DOWN, 10, 7)),
    ],
)
def test_mouse_events(seq, expected, monkeypatch):
    assert feed(seq, monkeypatch) == expected


def test_button_release_is_ignored(monkeypatch):
    """A press+release pair must fire exactly one action, not two."""
    assert feed("\033[<0;10;7m", monkeypatch) is None


def test_right_and_middle_buttons_ignored(monkeypatch):
    for btn in (1, 2):
        assert feed(f"\033[<{btn};5;5M", monkeypatch) is None


def test_malformed_mouse_report_does_not_raise(monkeypatch):
    assert feed("\033[<notnumbers;;M", monkeypatch) is None
    assert feed("\033[<0;1M", monkeypatch) is None          # too few fields


def test_ctrl_c_raises_keyboardinterrupt(monkeypatch):
    """Raw mode swallows SIGINT, so the parser must surface it itself."""
    with pytest.raises(KeyboardInterrupt):
        feed("\x03", monkeypatch)


def test_eof_returns_none(monkeypatch):
    assert feed("", monkeypatch) is None


def test_bare_escape_is_esc(monkeypatch):
    assert feed("\033x", monkeypatch) == (_keys.ESC,)


def test_motion_tracking_is_enabled_and_torn_down():
    """Hover needs mode 1003; leaving it on would spray escapes into the
    user's shell after exit."""
    assert "?1003h" in _keys._MOUSE_ON
    assert "?1003l" in _keys._MOUSE_OFF
    assert "?1049h" in _keys._ALT_ON and "?1049l" in _keys._ALT_OFF


def test_available_is_false_without_a_tty(monkeypatch):
    monkeypatch.delenv("RSMM_NO_RAW", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert _keys.available() is False


def test_available_respects_the_opt_out(monkeypatch):
    monkeypatch.setenv("RSMM_NO_RAW", "1")

    class TTY(io.StringIO):
        def isatty(self):
            return True

    assert _keys.available(TTY()) is False
