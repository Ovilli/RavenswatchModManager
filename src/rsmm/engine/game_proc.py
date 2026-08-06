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

import os
import subprocess

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

    # Linux/Proton: the exe name is the process name under Wine. `pgrep -f`
    # matches the full command line, which is where it shows up.
    proc = _run(["pgrep", "-f", PROCESS_NAME])
    if proc is None:
        return False
    return proc.returncode == 0 and bool((proc.stdout or "").strip())
