"""rsmm watch-restore — wait for Ravenswatch to exit, then restore the install.

Internal: `rsmm run` starts this detached after a modded launch, so the
install is put back to vanilla even when the terminal or the desktop app that
launched the game is gone. Hidden from `rsmm --help`; one watcher at a time
(pid file under the user data dir), logging to `watch-restore.log` because it
has no console.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from rsmm.engine import game_proc
from rsmm.engine.paths import self_cmd, user_data_dir

LOCK_NAME = "watch-restore.pid"
LOG_NAME = "watch-restore.log"
#: Bumped by every modded launch (`bump_launch_generation`). Only one watcher
#: runs at a time, so a second launch's watcher exits and the FIRST one is left
#: holding the second session — which it must not end with a restore.
GEN_NAME = "watch-restore.gen"
#: Past this size the log is truncated at the next start.
LOG_MAX_BYTES = 256 * 1024


def _log_path() -> Path:
    return user_data_dir() / LOG_NAME


def _log(msg: str) -> None:
    try:
        p = _log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with p.open("a", encoding="utf-8") as f:
            f.write(f"{stamp} [{os.getpid()}] {msg}\n")
    except OSError:
        pass


def _trim_log() -> None:
    p = _log_path()
    try:
        if p.stat().st_size > LOG_MAX_BYTES:
            data = p.read_bytes()[-LOG_MAX_BYTES // 4:]
            p.write_bytes(data[data.find(b"\n") + 1:])
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) on Windows TERMINATES the process, so ask the OS.
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _acquire_lock() -> bool:
    """Take the single-instance pid file. False when a live watcher holds it."""
    path = user_data_dir() / LOCK_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                pid = int(path.read_text(encoding="utf-8").strip() or 0)
            except (OSError, ValueError):
                pid = 0
            if pid and pid != os.getpid() and _pid_alive(pid):
                return False
            with contextlib.suppress(OSError):
                path.unlink()  # stale: its owner is gone
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        return True
    return False


def _release_lock() -> None:
    path = user_data_dir() / LOCK_NAME
    with contextlib.suppress(OSError, ValueError):
        if int(path.read_text(encoding="utf-8").strip()) == os.getpid():
            path.unlink()


def bump_launch_generation() -> None:
    """Record that a modded launch is starting (called before it applies).

    The running watcher compares this before restoring: a changed value means
    the game it saw exit has been (or is being) relaunched modded, so restoring
    would pull files from under the new session — Restart game hit exactly
    that, because the old watcher restored once the relaunch took longer than
    its three exit probes, and nothing then watched the new session at all.
    """
    p = user_data_dir() / GEN_NAME
    with contextlib.suppress(OSError):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"{time.time_ns()}-{os.getpid()}", encoding="utf-8")


def read_launch_generation() -> str:
    try:
        return (user_data_dir() / GEN_NAME).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _run_restore() -> tuple[bool, str]:
    """Run `rsmm restore` as a child; (ok, stderr tail)."""
    try:
        proc = subprocess.run(
            self_cmd(["restore"]), capture_output=True, text=True,
            errors="replace", check=False, stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as e:
        return False, str(e)
    tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-5:])
    return proc.returncode == 0, tail


def _wait_for_session(*, interval: float, start_timeout: float, exit_probes: int) -> None:
    """Wait for the game to appear (up to `start_timeout`), then for it to exit."""
    deadline = time.monotonic() + start_timeout
    seen = False
    while True:
        if game_proc.is_game_running():
            seen = True
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(interval)

    if not seen:
        _log(f"never saw the game within {start_timeout:g}s; restoring anyway")
        if not game_proc.is_game_running():
            return
        # It came up on the last probe: let it finish normally.
    _log("game seen; waiting for it to exit")
    # is_game_running() fails open: a probe timeout reads as "not
    # running". Only consecutive misses count as the game having exited.
    misses = 0
    while misses < exit_probes:
        time.sleep(interval)
        misses = 0 if game_proc.is_game_running() else misses + 1
    _log("game exited")


def watch(*, interval: float, start_timeout: float, exit_probes: int,
          restore_attempts: int, retry_delay: float) -> int:
    """The watch loop. 0 once restored, 1 when every restore attempt failed."""
    generation = read_launch_generation()
    while True:
        _wait_for_session(interval=interval, start_timeout=start_timeout,
                          exit_probes=exit_probes)
        attempt = 0
        superseded = False
        while attempt < restore_attempts:
            # Checked before EVERY attempt: a relaunch can land during the
            # retries as well as during the exit probes.
            now = read_launch_generation()
            if now != generation:
                generation = now
                superseded = True
                _log("a newer modded launch started; watching its session "
                     "instead of restoring")
                break
            attempt += 1
            ok, tail = _run_restore()
            if ok:
                _log("restore ok")
                return 0
            _log(f"restore failed (attempt {attempt}/{restore_attempts}): {tail}")
            if attempt < restore_attempts:
                time.sleep(retry_delay)
        if not superseded:
            return 1


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="rsmm watch-restore",
        description="Internal: wait for Ravenswatch to exit, then restore the "
                    "original files. Started by `rsmm run` after a modded launch.")
    ap.add_argument("--interval", type=float, default=5.0,
                    help="seconds between game probes (default 5)")
    ap.add_argument("--start-timeout", type=float, default=300.0,
                    help="seconds to wait for the game to appear (default 300)")
    ap.add_argument("--exit-probes", type=int, default=3,
                    help="consecutive not-running probes that count as exited (default 3)")
    ap.add_argument("--restore-attempts", type=int, default=4)
    ap.add_argument("--retry-delay", type=float, default=3.0)
    args = ap.parse_args()

    _trim_log()
    if not _acquire_lock():
        _log("another watcher is running; exiting")
        return 0
    try:
        _log("started")
        return watch(interval=args.interval, start_timeout=args.start_timeout,
                     exit_probes=args.exit_probes,
                     restore_attempts=args.restore_attempts,
                     retry_delay=args.retry_delay)
    finally:
        _release_lock()


if __name__ == "__main__":
    sys.exit(main())
