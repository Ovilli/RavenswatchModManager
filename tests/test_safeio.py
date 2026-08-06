"""Durability primitives: atomic writes, space preflight, install lock.

These guard the install against the three ways an apply can corrupt it —
torn writes, lost writes, and two processes writing at once.
"""

import json
import os
from pathlib import Path

import pytest

from rsmm.engine.safeio import (
    LOCK_NAME,
    TMP_PREFIX,
    LockBusy,
    NotEnoughSpace,
    atomic_copy,
    atomic_write_bytes,
    atomic_write_text,
    ensure_free_space,
    install_lock,
    sweep_temp_files,
)


def test_atomic_write_replaces_content_and_leaves_no_temp(tmp_path: Path):
    dest = tmp_path / "sub" / "asset.bin"
    atomic_write_bytes(dest, b"one")
    assert dest.read_bytes() == b"one"
    atomic_write_text(dest, "two")
    assert dest.read_text() == "two"
    assert list(tmp_path.rglob(f"{TMP_PREFIX}*")) == []


def test_atomic_copy_preserves_bytes_and_mtime(tmp_path: Path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"payload" * 1000)
    os.utime(src, (1_600_000_000, 1_600_000_000))
    dest = tmp_path / "out" / "dest.bin"

    written = atomic_copy(src, dest)
    assert written == src.stat().st_size
    assert dest.read_bytes() == src.read_bytes()
    assert int(dest.stat().st_mtime) == 1_600_000_000


def test_atomic_copy_leaves_the_original_intact_when_the_read_fails(tmp_path: Path):
    """A failed copy must not have touched the destination at all.

    This is the whole point of staging: `shutil.copy2` truncates the
    destination before it reads a single byte from the source.
    """
    dest = tmp_path / "asset.bin"
    dest.write_bytes(b"vanilla")
    missing = tmp_path / "does-not-exist"

    with pytest.raises(OSError):
        atomic_copy(missing, dest)

    assert dest.read_bytes() == b"vanilla"
    assert list(tmp_path.rglob(f"{TMP_PREFIX}*")) == []


def test_sweep_temp_files_removes_crash_leftovers(tmp_path: Path):
    (tmp_path / "a").mkdir()
    leftover = tmp_path / "a" / f"{TMP_PREFIX}asset.bin.1234"
    leftover.write_bytes(b"junk")
    keep = tmp_path / "a" / "asset.bin"
    keep.write_bytes(b"real")

    assert sweep_temp_files(tmp_path) == 1
    assert not leftover.exists()
    assert keep.exists()


def test_ensure_free_space_raises_before_writing(tmp_path: Path):
    with pytest.raises(NotEnoughSpace) as e:
        ensure_free_space(tmp_path, 1 << 60)
    assert "not enough free space" in str(e.value)
    # A plausible request passes.
    ensure_free_space(tmp_path, 1024)
    # Zero/negative is a no-op, not an error.
    ensure_free_space(tmp_path, 0)


def test_install_lock_is_exclusive(tmp_path: Path):
    with install_lock(tmp_path, "apply"):
        assert (tmp_path / LOCK_NAME).exists()
        with pytest.raises(LockBusy, match="another rsmm process"):
            with install_lock(tmp_path, "restore"):
                pass
    # Released on exit.
    assert not (tmp_path / LOCK_NAME).exists()


def test_install_lock_records_its_owner(tmp_path: Path):
    with install_lock(tmp_path, "apply"):
        info = json.loads((tmp_path / LOCK_NAME).read_text())
    assert info["pid"] == os.getpid()
    assert info["operation"] == "apply"


def test_install_lock_takes_over_a_dead_owner(tmp_path: Path):
    """A killed rsmm must not wedge the install forever."""
    (tmp_path / LOCK_NAME).write_text(
        json.dumps({"pid": 999_999_999, "operation": "apply", "started": 0})
    )
    with install_lock(tmp_path, "apply"):
        info = json.loads((tmp_path / LOCK_NAME).read_text())
        assert info["pid"] == os.getpid()


def test_install_lock_takes_over_an_aged_out_lock(tmp_path: Path, monkeypatch):
    """Even a live-looking owner loses the lock once it is absurdly old.

    On Windows there is no cheap liveness probe, so age is the only signal.
    """
    monkeypatch.setattr("rsmm.engine.safeio._pid_alive", lambda pid: True)
    (tmp_path / LOCK_NAME).write_text(
        json.dumps({"pid": os.getpid(), "operation": "apply", "started": 1.0})
    )
    with install_lock(tmp_path, "apply"):
        assert json.loads((tmp_path / LOCK_NAME).read_text())["started"] > 1.0


def test_install_lock_releases_on_exception(tmp_path: Path):
    with pytest.raises(ValueError):
        with install_lock(tmp_path, "apply"):
            raise ValueError("boom")
    assert not (tmp_path / LOCK_NAME).exists()
