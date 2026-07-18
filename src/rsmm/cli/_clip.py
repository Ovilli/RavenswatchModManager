"""Clipboard copy with a file fallback — stdlib only.

No pyperclip: the runtime declares no dependencies. Shells out to whatever the
platform provides, newest-first (Wayland before X11, since a Wayland session
usually still has a broken-ish xclip on PATH).

Copy can legitimately fail — headless boxes, SSH without forwarding, missing
tools — so `copy()` reports what happened instead of raising, and the caller
falls back to writing a file the user can open.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# (command, needs stdin) — first one whose binary exists wins.
_CANDIDATES: tuple[tuple[list[str], str], ...] = (
    (["wl-copy"], "wayland"),
    (["xclip", "-selection", "clipboard"], "x11"),
    (["xsel", "--clipboard", "--input"], "x11"),
    (["pbcopy"], "macos"),
    (["clip.exe"], "wsl/windows"),
)


def _available() -> tuple[list[str], str] | None:
    for cmd, kind in _CANDIDATES:
        if shutil.which(cmd[0]):
            # Wayland tools are useless without a display; skip rather than
            # letting them fail noisily.
            if kind == "wayland" and not os.environ.get("WAYLAND_DISPLAY"):
                continue
            if kind == "x11" and not os.environ.get("DISPLAY"):
                continue
            return cmd, kind
    return None


# xclip and xsel do NOT exit after copying: X11 has no clipboard daemon, so
# the tool forks and stays alive to serve the selection on request. Waiting
# for them to exit hangs until something pastes (measured: a 10s timeout on
# this machine, which would freeze the UI). Write, close stdin, and treat
# "still running" as success for those two.
_PERSISTENT = {"xclip", "xsel"}


def copy(text: str) -> tuple[bool, str]:
    """Put `text` on the clipboard. Returns (ok, description).

    Never raises and never blocks for more than a moment: a failed copy must
    degrade to the file fallback, not stall an interactive screen.
    """
    found = _available()
    if not found:
        return False, "no clipboard tool (tried wl-copy, xclip, xsel, pbcopy, clip.exe)"
    cmd, kind = found
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        assert proc.stdin is not None
        proc.stdin.write(text.encode("utf-8"))
        proc.stdin.close()
    except (OSError, ValueError) as e:
        return False, f"{cmd[0]} failed: {e}"

    if cmd[0] in _PERSISTENT:
        # Give it a beat to fail fast on a bad invocation; still-running is
        # the normal, healthy state here.
        try:
            rc = proc.wait(timeout=0.3)
        except subprocess.TimeoutExpired:
            return True, f"copied to clipboard via {cmd[0]} ({kind})"
        if rc != 0:
            return False, f"{cmd[0]} exited {rc}"
        return True, f"copied to clipboard via {cmd[0]} ({kind})"

    try:
        rc = proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        return False, f"{cmd[0]} timed out"
    if rc != 0:
        return False, f"{cmd[0]} exited {rc}"
    return True, f"copied to clipboard via {cmd[0]} ({kind})"


def dump(text: str, path: Path) -> tuple[bool, str]:
    """Fallback: write to a file so the content is still recoverable."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as e:
        return False, f"could not write {path}: {e}"
    return True, f"wrote {path}"


def copy_or_dump(text: str, path: Path) -> str:
    """Try the clipboard, fall back to a file. Returns a message to show."""
    ok, msg = copy(text)
    if ok:
        return msg
    ok2, msg2 = dump(text, path)
    return f"{msg}; {msg2}" if ok2 else f"{msg}; {msg2}"


def is_ssh() -> bool:
    """SSH sessions usually cannot reach a clipboard — worth saying so."""
    return bool(os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY")) \
        and not sys.platform.startswith("darwin")
