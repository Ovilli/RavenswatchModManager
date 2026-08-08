"""Durable file primitives for everything that touches the game install.

Three failure modes this module exists to remove:

* **Torn writes.** ``shutil.copy2(src, dest)`` writes in place. A crash,
  a power loss or a full disk part-way through leaves a truncated game
  asset — and the engine happily loads whatever bytes are there. Every
  write here lands via a temp file in the *same directory* plus
  ``os.replace``, which is atomic on both NTFS and ext4: readers see the
  old bytes or the new ones, never half.

* **Lost writes.** ``os.replace`` orders the rename against the data only
  if the data reached the disk first. Without an ``fsync`` a crash can
  leave the rename applied and the file empty. So the temp file is fsynced
  before the rename and the directory after it.

* **Concurrent writers.** Two applies (the desktop app and a terminal, or
  a double-clicked launch) interleaving over the same asset can back up a
  *modded* file as the "original" — permanently losing the vanilla bytes,
  which no restore can undo. :class:`InstallLock` serialises them.

Stdlib only: the CLI ships frozen with no runtime dependencies.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path

TMP_PREFIX = ".rsmm.tmp."
LOCK_NAME = ".rsmm.lock"

#: A lock older than this with no live owner is treated as abandoned.
#: Deliberately generous — a big apply over a slow disk is minutes, and
#: stealing a live lock is far worse than waiting.
STALE_LOCK_SEC = 30 * 60

#: How long a lock whose contents carry no timestamp is still respected.
#: `os.open(O_CREAT | O_EXCL)` publishes the lock *path* before the payload
#: is written, so there is a window in which the holder's own lock reads as
#: empty. Treating that as abandoned outright is a lock-stealing race; waiting
#: `STALE_LOCK_SEC` instead would re-wedge the install this file's ageing
#: rules exist to unwedge. Seconds is the right order: the write window is
#: sub-millisecond, and a genuinely orphaned zero-byte lock clears fast.
TORN_LOCK_GRACE_SEC = 5.0


class NotEnoughSpace(OSError):
    """Raised by :func:`ensure_free_space` before anything is written."""


class LockBusy(RuntimeError):
    """Another rsmm process holds the install lock."""


def fsync_dir(directory: Path) -> None:
    """Flush a directory entry so a rename survives a crash.

    Windows has no directory fsync and rejects opening one, so this is a
    no-op there; NTFS orders metadata through its own journal.
    """
    if os.name == "nt":
        return
    fd = None
    try:
        fd = os.open(str(directory), os.O_RDONLY)
        os.fsync(fd)
    except OSError:
        # Best effort: a filesystem that refuses this (some network mounts)
        # must not fail the write that already succeeded.
        pass
    finally:
        if fd is not None:
            os.close(fd)


def _tmp_path(dest: Path) -> Path:
    # Same directory as the destination: os.replace is only atomic within a
    # filesystem, and /tmp is routinely a different one.
    return dest.parent / f"{TMP_PREFIX}{dest.name}.{os.getpid()}"


def atomic_write_bytes(dest: Path, data: bytes) -> None:
    """Write `data` to `dest` atomically and durably."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path(dest)
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dest)
        fsync_dir(dest.parent)
    finally:
        _cleanup(tmp)


def atomic_write_text(dest: Path, text: str, encoding: str = "utf-8") -> None:
    atomic_write_bytes(dest, text.encode(encoding))


def atomic_copy(src: Path, dest: Path) -> int:
    """Copy `src` onto `dest` atomically and durably; return bytes written.

    Metadata is copied like ``shutil.copy2`` so mtime-based staleness checks
    elsewhere keep working.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path(dest)
    try:
        with open(src, "rb") as fsrc, open(tmp, "wb") as fdst:
            shutil.copyfileobj(fsrc, fdst)
            fdst.flush()
            os.fsync(fdst.fileno())
        shutil.copystat(src, tmp)
        size = tmp.stat().st_size
        os.replace(tmp, dest)
        fsync_dir(dest.parent)
        return size
    finally:
        _cleanup(tmp)


def _cleanup(tmp: Path) -> None:
    try:
        tmp.unlink()
    except (FileNotFoundError, OSError):
        pass


def sweep_temp_files(root: Path) -> int:
    """Delete leftover ``.rsmm.tmp.*`` files under `root`; return the count.

    A crash between opening the temp file and the rename leaves one behind.
    They are inert — the engine never loads them, since the cooked name is
    ciphered — but they waste space and confuse a `ls` of the install.
    """
    removed = 0
    for p in root.rglob(f"{TMP_PREFIX}*"):
        try:
            if p.is_file():
                p.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def ensure_free_space(directory: Path, need_bytes: int, *, margin: float = 1.15) -> None:
    """Raise :class:`NotEnoughSpace` unless `directory` can take the write.

    Checked BEFORE the first byte is written: a disk that fills up mid-apply
    is one of the few ways to end up with a partially applied install, and
    the check costs one syscall. `margin` covers the backups taken alongside
    and normal filesystem overhead.
    """
    if need_bytes <= 0:
        return
    try:
        free = shutil.disk_usage(directory).free
    except OSError:
        return  # Can't tell — don't block the apply on a stat failure.
    want = int(need_bytes * margin)
    if free < want:
        raise NotEnoughSpace(
            errno.ENOSPC,
            f"not enough free space in {directory}: need about "
            f"{want // (1 << 20)} MiB, {free // (1 << 20)} MiB available",
        )


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # No signal 0 on Windows; tasklist is the stdlib-free option, but
        # shelling out here would be slow and noisy. Fall back to the age
        # check, which is what STALE_LOCK_SEC is for.
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Exists, owned by someone else.
    return True


def _read_lock(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@contextmanager
def install_lock(cooking: Path, operation: str = "apply", *, timeout: float = 0.0):
    """Serialise install-mutating operations against a lock in `cooking`.

    Held by exactly one process. A lock whose owner is gone, or which is
    older than :data:`STALE_LOCK_SEC`, is taken over — an rsmm that was
    killed must not wedge the install permanently.

    `timeout` seconds to wait for a busy lock before raising
    :class:`LockBusy` (0 = fail immediately).
    """
    cooking.mkdir(parents=True, exist_ok=True)
    path = cooking / LOCK_NAME
    deadline = time.monotonic() + timeout
    fd = None
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            info = _read_lock(path)
            owner = int(info.get("pid", 0) or 0)
            started = float(info.get("started", 0) or 0)
            if started > 0:
                aged_out = (time.time() - started) > STALE_LOCK_SEC
            else:
                # No timestamp: either a foreign file, or a lock somebody is
                # still acquiring (see TORN_LOCK_GRACE_SEC). Its own mtime
                # tells the two apart without trusting its contents — which
                # also keeps the Windows case working, where `_pid_alive` must
                # answer True for every pid and age is the only other signal.
                try:
                    age = time.time() - path.stat().st_mtime
                except OSError:
                    age = TORN_LOCK_GRACE_SEC + 1
                aged_out = age > TORN_LOCK_GRACE_SEC
            if not _pid_alive(owner) or aged_out:
                # Abandoned. Remove and retry; if someone else wins the race
                # the next open simply fails again and we loop.
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise LockBusy(
                    f"another rsmm process is working on this install "
                    f"(pid {owner or 'unknown'}, {info.get('operation', '?')}). "
                    f"Wait for it to finish, or delete {path} if it is gone."
                ) from None
            time.sleep(0.25)
    try:
        os.write(fd, json.dumps({
            "pid": os.getpid(),
            "operation": operation,
            "started": time.time(),
            "argv": " ".join(sys.argv[:3]),
        }).encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        fd = None
        yield path
    finally:
        if fd is not None:
            os.close(fd)
        # Release only a lock we still own. If ours aged out and another
        # process legitimately took over, unlinking here would delete *their*
        # lock and let a third process in alongside them — the exact
        # interleaving this lock exists to prevent. An unowned leftover is
        # self-healing: it ages out via TORN_LOCK_GRACE_SEC / STALE_LOCK_SEC.
        try:
            if int(_read_lock(path).get("pid", 0) or 0) == os.getpid():
                path.unlink()
        except (FileNotFoundError, OSError):
            pass
