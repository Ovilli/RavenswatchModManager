"""Terminal styling for the CLI — stdlib only, safe to pipe.

The runtime has no third-party dependencies (`pyproject.toml` declares none),
so this is a small hand-rolled ANSI layer rather than `rich`/`colorama`.

Colour is **off unless stdout is a TTY**. That matters here beyond taste: the
desktop app shells out to this CLI and parses the output, so escape codes
leaking into a pipe would corrupt it. Honours the usual environment contract:

    NO_COLOR=1          force off  (https://no-color.org)
    TERM=dumb           force off
    FORCE_COLOR / CLICOLOR_FORCE=1   force on (CI logs, `less -R`)
"""

from __future__ import annotations

import os
import shutil
import sys


def _never_die_on_encoding() -> None:
    """Make stdout/stderr incapable of raising UnicodeEncodeError.

    Windows picks the ANSI codepage (cp1252) for a redirected stream, and the
    prose in these commands is full of em dashes and the bars/box glyphs below.
    `rsmm overlay meter > out.txt` therefore CRASHED on Windows with
    `'charmap' codec can't encode characters` — a real user-facing bug on the
    platform the loader targets, not merely a CI detail.

    `box_chars()` already degrades for exactly this reason, but it only covers
    the box; a single em dash anywhere else is enough to kill the process. This
    is the backstop: keep the stream's own encoding (so a real console still
    renders what it can) and swap the error handler, so an unrepresentable
    character becomes a replacement mark instead of a traceback. Output is
    never worth crashing over.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue                      # not a TextIOWrapper (pytest capture)
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):     # detached or already closed
            pass


_never_die_on_encoding()

RESET = "\033[0m"
_CODES = {
    "bold": "1",
    "dim": "2",
    "italic": "3",
    "underline": "4",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "white": "37",
    "grey": "90",
}


def color_enabled(stream=None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR") or os.environ.get("CLICOLOR_FORCE"):
        return True
    if os.environ.get("TERM") == "dumb":
        return False
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


class Style:
    """Styling bound to one stream's colour decision.

    Held as an object rather than module globals so tests (and `--no-color`)
    can construct a plain instance without touching process state.
    """

    def __init__(self, enabled: bool | None = None, stream=None):
        self.enabled = color_enabled(stream) if enabled is None else enabled

    def __call__(self, text: str, *styles: str) -> str:
        if not self.enabled or not styles:
            return text
        codes = ";".join(_CODES[s] for s in styles if s in _CODES)
        return f"\033[{codes}m{text}{RESET}" if codes else text

    # convenience wrappers — read better at call sites than ("x", "red")
    def bold(self, t: str) -> str:
        return self(t, "bold")

    def dim(self, t: str) -> str:
        return self(t, "dim")

    def ok(self, t: str) -> str:
        return self(t, "green")

    def warn(self, t: str) -> str:
        return self(t, "yellow")

    def err(self, t: str) -> str:
        return self(t, "red")

    def accent(self, t: str) -> str:
        return self(t, "cyan")

    def heading(self, t: str) -> str:
        return self(t, "bold", "cyan")


# One content width for every framed/ruled surface. Without a shared cap the
# panels and rules disagree on wide terminals and the output looks unaligned.
MAX_WIDTH = 78


def width(default: int = 100) -> int:
    """Terminal width, clamped so rules and panels line up at any size."""
    try:
        cols = shutil.get_terminal_size((default, 24)).columns
    except OSError:
        cols = default
    return max(48, min(cols, MAX_WIDTH))


def full_width(default: int = 100) -> int:
    """Terminal width WITHOUT the MAX_WIDTH cap.

    `width()` clamps to 78 so framed panels and rules line up. That cap is
    right for chrome and wrong for content: applying it to loader log lines
    threw away everything past column 74 (one real line lost 862 of its 936
    characters). Use this for anything the user needs to actually read.
    """
    try:
        cols = shutil.get_terminal_size((default, 24)).columns
    except OSError:
        cols = default
    return max(40, cols)


def wrap_line(text: str, limit: int, indent: str = "") -> list[str]:
    """Hard-wrap one PLAIN line to `limit` columns.

    Deliberately operates on unstyled text: splitting an already-styled string
    can cut through an ANSI escape and bleed colour across the screen. Callers
    style the resulting pieces instead. Wraps at a space when there is a
    sensible one, otherwise mid-token — a 900-character log line has no spaces
    where we need them and must still be readable.
    """
    if limit <= 0:
        return [text]
    out: list[str] = []
    rest = text
    while True:
        budget = limit if not out else limit - len(indent)
        if budget <= 0 or len(rest) <= budget:
            out.append(rest if not out else indent + rest)
            return out
        cut = rest.rfind(" ", max(0, budget - 24), budget)
        if cut <= 0:
            cut = budget
        piece, rest = rest[:cut], rest[cut:].lstrip(" ")
        out.append(piece if len(out) == 0 else indent + piece)
        if not rest:
            return out


def height(default: int = 24) -> int:
    """Terminal rows, floored so a tiny window still renders something."""
    try:
        rows = shutil.get_terminal_size((100, default)).lines
    except OSError:
        rows = default
    return max(10, rows)


def human_bytes(n: int) -> str:
    """1234567 -> '1.2 MB'. Byte counts in raw digits are hard to compare."""
    step = 1024.0
    val = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(val) < step or unit == "GB":
            return f"{val:.0f} {unit}" if unit == "B" else f"{val:.1f} {unit}"
        val /= step
    return f"{val:.1f} GB"


def rule(label: str = "", s: Style | None = None, char: str = "─") -> str:
    """A horizontal rule, optionally with an inline label."""
    s = s or Style()
    total = width()
    if not label:
        return s.dim(char * total)
    text = f"{char}{char} {label} "
    pad = max(0, total - len(text))
    return s.dim(text + char * pad)


# Box-drawing. Rounded corners read as "modern TUI" and degrade fine in any
# UTF-8 terminal; ASCII fallback is deliberate for the rare terminal that
# mangles them (LANG=C, some CI capture, older Windows consoles).
_BOX = {
    "tl": "\u256d", "tr": "\u256e", "bl": "\u2570", "br": "\u256f",
    "h": "\u2500", "v": "\u2502",
}
_BOX_ASCII = {"tl": "+", "tr": "+", "bl": "+", "br": "+", "h": "-", "v": "|"}


def box_chars() -> dict[str, str]:
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    return _BOX if ("utf" in enc) else _BOX_ASCII


def visible_len(text: str) -> int:
    """Length ignoring ANSI escapes — box padding must not count colour codes."""
    out, i = 0, 0
    while i < len(text):
        if text[i] == "\033":
            j = text.find("m", i)
            if j == -1:
                break
            i = j + 1
            continue
        out += 1
        i += 1
    return out


def truncate(text: str, limit: int) -> str:
    """Cut to `limit` VISIBLE characters, keeping escape sequences intact.

    A plain slice can land inside an ANSI sequence, which leaks raw escape
    bytes (or bleeds colour into the rest of the screen). Always closes with a
    reset when anything was dropped.
    """
    if visible_len(text) <= limit:
        return text
    out, seen, i = [], 0, 0
    while i < len(text) and seen < limit:
        if text[i] == "\033":
            j = text.find("m", i)
            if j == -1:
                break
            out.append(text[i:j + 1])
            i = j + 1
            continue
        out.append(text[i])
        seen += 1
        i += 1
    return "".join(out) + RESET


def panel_top(title: str = "", s: Style | None = None, w: int | None = None) -> str:
    s = s or Style()
    b = box_chars()
    w = w or width()
    if title:
        head = f"{b['h']} {title} "
        return s.dim(b["tl"] + head + b["h"] * max(0, w - visible_len(head) - 2)
                     + b["tr"])
    return s.dim(b["tl"] + b["h"] * (w - 2) + b["tr"])


def panel_bottom(s: Style | None = None, w: int | None = None) -> str:
    s = s or Style()
    b = box_chars()
    w = w or width()
    return s.dim(b["bl"] + b["h"] * (w - 2) + b["br"])


def panel_row(text: str, s: Style | None = None, w: int | None = None) -> str:
    """One framed line, padded to the panel width (ANSI-aware)."""
    s = s or Style()
    b = box_chars()
    w = w or width()
    pad = max(0, w - visible_len(text) - 4)
    return f"{s.dim(b['v'])} {text}{' ' * pad} {s.dim(b['v'])}"


def bar(fraction: float, size: int = 24, s: Style | None = None) -> str:
    """Unicode meter for proportions (e.g. how much of a file is opaque)."""
    s = s or Style()
    fraction = max(0.0, min(1.0, fraction))
    filled = int(round(fraction * size))
    return s.accent("█" * filled) + s.dim("░" * (size - filled))
