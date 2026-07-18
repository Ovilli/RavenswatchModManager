"""Raw-terminal input: arrow keys and mouse clicks, stdlib only.

Gives the home screen opencode-style navigation — move the highlight with
↑/↓, click a row with the mouse — without pulling in curses or a TUI library
(the runtime declares no dependencies).

Two hard rules, because both failure modes leave the user's terminal broken:

1. Raw mode and mouse reporting are ALWAYS restored, including on exception
   and KeyboardInterrupt — `raw_session()` is a context manager and the
   teardown lives in a `finally`.
2. Anything unsupported degrades to `available() is False`, and the caller
   falls back to the plain numbered prompt. Windows (no termios), a dumb
   terminal, and a pipe all take that path rather than half-working.

Mouse uses SGR mode 1006 (`ESC[<b;x;yM`), which is what modern terminals
speak; the legacy X10 encoding is deliberately not parsed.
"""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Iterator

try:  # POSIX only — Windows has no termios and falls back to the plain prompt.
    import termios
    import tty
except ImportError:  # pragma: no cover - platform dependent
    termios = None  # type: ignore[assignment]
    tty = None  # type: ignore[assignment]

# Key names returned by read_key()
UP, DOWN, ENTER, ESC, BACKSPACE = "up", "down", "enter", "esc", "backspace"
PGUP, PGDN, HOME, END = "pgup", "pgdn", "home", "end"
WHEEL_UP, WHEEL_DOWN = "wheel_up", "wheel_down"
MOTION = "motion"          # bare mouse movement, for hover highlighting

# 1000 = button press/release, 1003 = ALL motion (needed for hover),
# 1006 = SGR extended coordinates (so columns past 223 still work).
_MOUSE_ON = "\033[?1000h\033[?1003h\033[?1006h"
_MOUSE_OFF = "\033[?1006l\033[?1003l\033[?1000l"
_HIDE_CURSOR = "\033[?25l"
_SHOW_CURSOR = "\033[?25h"
_ALT_ON = "\033[?1049h"    # alternate screen buffer
_ALT_OFF = "\033[?1049l"


@contextlib.contextmanager
def alt_screen() -> Iterator[None]:
    """Draw on the alternate screen buffer, like less/vim.

    Without this every menu redraw is appended to the scrollback and the
    terminal grows forever during a session. On exit the previous screen is
    restored byte-for-byte, so running rsmm leaves no trace in the buffer.
    Restored in a finally: leaving a user stuck on the alt screen is worse
    than never using it.
    """
    sys.stdout.write(_ALT_ON)
    sys.stdout.flush()
    try:
        yield
    finally:
        sys.stdout.write(_ALT_OFF)
        sys.stdout.flush()


def available(stream=None) -> bool:
    """True when raw-mode navigation can be used at all."""
    stream = stream or sys.stdin
    if termios is None or tty is None:
        return False
    if os.environ.get("TERM") == "dumb" or os.environ.get("RSMM_NO_RAW"):
        return False
    try:
        return bool(stream.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


@contextlib.contextmanager
def raw_session(mouse: bool = True, hide_cursor: bool = True) -> Iterator[None]:
    """Put the terminal in raw mode for the duration of the block.

    Restores the saved termios state, mouse reporting and cursor no matter how
    the block exits. A crash here would otherwise leave the shell with no echo
    and mouse escape codes spraying into it.
    """
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        if mouse:
            sys.stdout.write(_MOUSE_ON)
        if hide_cursor:
            sys.stdout.write(_HIDE_CURSOR)
        sys.stdout.flush()
        yield
    finally:
        if mouse:
            sys.stdout.write(_MOUSE_OFF)
        if hide_cursor:
            sys.stdout.write(_SHOW_CURSOR)
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def _read_sgr_mouse() -> tuple[str, int, int] | None:
    """Parse the tail of an `ESC [ <` mouse report -> ('click', col, row).

    Returns None for anything that is not a left-button press: releases and
    scroll/drag events would otherwise fire an action twice per click.
    """
    buf = ""
    while len(buf) < 32:
        ch = sys.stdin.read(1)
        if not ch:
            return None
        if ch in ("M", "m"):
            parts = buf.split(";")
            if len(parts) != 3:
                return None
            try:
                btn, col, row = int(parts[0]), int(parts[1]), int(parts[2])
            except ValueError:
                return None
            # Wheel events set bit 6; 64 = up, 65 = down. They are presses
            # with no release, so they are safe to act on directly.
            if btn in (64, 65):
                return ((WHEEL_UP if btn == 64 else WHEEL_DOWN), col, row)
            # Bit 5 (32) marks motion. 35 = moving with no button held, which
            # is plain hover; 32-34 are drags. Both are reported as MOTION —
            # callers only use the coordinates.
            if btn & 32:
                return (MOTION, col, row)
            # 'm' is a release; low 2 bits select the button, 0 = left.
            if ch == "m" or (btn & 0b11) != 0 or btn >= 64:
                return None
            return ("click", col, row)
        buf += ch
    return None


def read_key() -> tuple[str, int, int] | tuple[str] | None:
    """Block for one key or mouse click.

    Returns ('click', col, row), or a 1-tuple naming the key: an arrow, enter,
    esc, backspace, or the literal character typed.
    """
    ch = sys.stdin.read(1)
    if not ch:
        return None
    if ch == "\033":
        nxt = sys.stdin.read(1)
        if nxt != "[":
            return (ESC,)
        third = sys.stdin.read(1)
        if third == "<":
            return _read_sgr_mouse()
        simple = {"A": (UP,), "B": (DOWN,), "H": (HOME,), "F": (END,)}
        if third in simple:
            return simple[third]
        if third.isdigit():
            # ESC [ <n> ~  — 5=PgUp, 6=PgDn, 1/7=Home, 4/8=End
            tail = third
            while len(tail) < 4:
                nxt2 = sys.stdin.read(1)
                if not nxt2 or nxt2 == "~":
                    break
                tail += nxt2
            return {"5": (PGUP,), "6": (PGDN,), "1": (HOME,), "7": (HOME,),
                    "4": (END,), "8": (END,)}.get(tail, (ESC,))
        return (ESC,)
    if ch in ("\r", "\n"):
        return (ENTER,)
    if ch in ("\x7f", "\b"):
        return (BACKSPACE,)
    if ch == "\x03":            # Ctrl-C never reaches the signal handler in raw mode
        raise KeyboardInterrupt
    return (ch,)
