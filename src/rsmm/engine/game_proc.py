"""Is Ravenswatch running right now?

Writing cooked assets under a live game is unsafe in two directions:

* Windows keeps handles on files the engine has open, so a copy can fail
  part-way through a batch and leave the install half-applied;
* even where the write succeeds (Linux/Proton replaces the inode happily),
  the running engine may still be reading the old handle, or may read a
  file that changed underneath it — the resulting behaviour ranges from
  "mod doesn't take effect" to a crash the player reports as a mod bug.

Detection is best effort and fails OPEN: if we cannot tell, we do not
block the user's apply. Being wrong in that direction costs a warning;
being wrong the other way makes rsmm unusable when the probe misbehaves.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time

PROCESS_NAME = "Ravenswatch.exe"

#: The probe is a courtesy check on the way into a long operation; if the
#: system is wedged enough that this takes seconds, do not add to it.
_PROBE_TIMEOUT_SEC = 5


def _run(cmd: list[str]) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, check=False,
            timeout=_PROBE_TIMEOUT_SEC,
            # Windows: don't flash a console window when the desktop app
            # shells out to the frozen sidecar.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None


def is_game_running() -> bool:
    """True when a Ravenswatch process is visibly running.

    False when it is not — and also when we could not find out (missing
    tool, timeout, permission denied). See the module docstring: this
    fails open on purpose.
    """
    if os.name == "nt":
        proc = _run(["tasklist", "/FI", f"IMAGENAME eq {PROCESS_NAME}", "/NH"])
        if proc is None:
            return False
        # tasklist prints an "INFO: No tasks..." banner rather than exiting
        # non-zero when nothing matches, so match the name, not the code.
        return PROCESS_NAME.lower() in (proc.stdout or "").lower()

    # Linux/Proton: scan /proc and match the process ITSELF, never a command
    # line that merely mentions the exe.
    #
    # This used to be `pgrep -f Ravenswatch.exe`, which matches the whole
    # command line — and under Proton the launcher scaffolding (reaper,
    # steam-runtime-launch-client, bwrap, pv-adverb, proton, steam.exe) all
    # carry the exe PATH in their arguments and outlive the game. So every
    # apply after the first launch of a Steam session was refused with
    # "Ravenswatch is running" while nothing was running, and `-f` even
    # matched a shell script that was waiting for the game to exit. Measured
    # 2026-08-23: 9 matching processes, 0 of them the game.
    #
    # `comm` is the kernel's own name for the process (truncated to 15 chars,
    # which "Ravenswatch.exe" fits exactly) and argv[0] is what the program
    # was invoked as; the wrappers match neither.
    try:
        entries = os.listdir("/proc")
    except OSError:
        return False
    want = PROCESS_NAME.lower()
    for entry in entries:
        if not entry.isdigit():
            continue
        base = "/proc/" + entry
        try:
            with open(base + "/comm", encoding="utf-8", errors="replace") as fh:
                if fh.read().strip().lower() == want:
                    return True
            with open(base + "/cmdline", "rb") as fh:
                argv0 = fh.read().split(b"\0", 1)[0]
        except OSError:
            continue                      # the process exited from under us
        # Normalise separators before taking the leaf: under Wine/Proton argv[0]
        # is the WINDOWS path the program was invoked as ("Z:\\...\\Ravenswatch.exe"),
        # and posix os.path.basename does not split on "\\" — it would hand back
        # the whole string and this branch would never fire, leaving detection
        # resting entirely on comm.
        leaf = argv0.decode("utf-8", "replace").replace("\\", "/")
        if argv0 and os.path.basename(leaf).lower() == want:
            return True
    return False


#: How long to let the game shut down politely before insisting.
_STOP_GRACE_SEC = 8


def _pids() -> list[int]:
    """PIDs of the game process itself. Linux only; see is_game_running for
    why matching the process rather than a command line matters here."""
    out: list[int] = []
    try:
        entries = os.listdir("/proc")
    except OSError:
        return out
    want = PROCESS_NAME.lower()
    for entry in entries:
        if not entry.isdigit():
            continue
        base = "/proc/" + entry
        try:
            with open(base + "/comm", encoding="utf-8", errors="replace") as fh:
                if fh.read().strip().lower() == want:
                    out.append(int(entry))
                    continue
            with open(base + "/cmdline", "rb") as fh:
                argv0 = fh.read().split(b"\0", 1)[0]
        except OSError:
            continue
        leaf = argv0.decode("utf-8", "replace").replace("\\", "/")
        if argv0 and os.path.basename(leaf).lower() == want:
            out.append(int(entry))
    return out


def stop_game(grace_sec: float = _STOP_GRACE_SEC) -> bool:
    """Ask Ravenswatch to close, then insist. True once nothing is running.

    Polite first in both directions — `taskkill` without `/F` and SIGTERM let
    the engine flush its save; only a process that ignores that gets killed.
    A run in progress is lost either way, so nothing calls this without the
    user having asked for it in as many words.
    """
    if not is_game_running():
        return True

    deadline = time.monotonic() + grace_sec
    if os.name == "nt":
        _run(["taskkill", "/IM", PROCESS_NAME])
    else:
        for pid in _pids():
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGTERM)

    while time.monotonic() < deadline:
        if not is_game_running():
            return True
        time.sleep(0.25)

    # Still there: insist.
    if os.name == "nt":
        _run(["taskkill", "/F", "/IM", PROCESS_NAME])
    else:
        for pid in _pids():
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)

    hard_deadline = time.monotonic() + 5
    while time.monotonic() < hard_deadline:
        if not is_game_running():
            return True
        time.sleep(0.25)
    return False
