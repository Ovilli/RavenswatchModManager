"""Clipboard helper tests.

The behaviour worth pinning is the failure handling: copy runs inside an
interactive screen, so it must never raise and never block. xclip in
particular does not exit after copying (X11 has no clipboard daemon — the
tool stays alive to serve the selection), which hung the UI for 10s before
this was handled.
"""

from __future__ import annotations

import subprocess

import pytest

from rsmm.cli import _clip


@pytest.fixture(autouse=True)
def _no_display(monkeypatch):
    for var in ("WAYLAND_DISPLAY", "DISPLAY", "SSH_CONNECTION", "SSH_TTY"):
        monkeypatch.delenv(var, raising=False)


def test_no_tool_reports_instead_of_raising(monkeypatch):
    monkeypatch.setattr(_clip.shutil, "which", lambda _c: None)
    ok, msg = _clip.copy("x")
    assert ok is False
    assert "no clipboard tool" in msg


def test_x11_tool_skipped_without_display(monkeypatch):
    """xclip on PATH but no DISPLAY would fail noisily; skip it instead."""
    monkeypatch.setattr(_clip.shutil, "which", lambda c: c == "xclip")
    assert _clip._available() is None


def test_x11_tool_used_when_display_present(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(_clip.shutil, "which", lambda c: c == "xclip")
    cmd, kind = _clip._available()
    assert cmd[0] == "xclip"
    assert kind == "x11"


def test_persistent_tool_still_running_counts_as_success(monkeypatch):
    """xclip holding the selection is the healthy case, not a timeout."""
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(_clip.shutil, "which", lambda c: c == "xclip")

    class Proc:
        stdin = type("W", (), {"write": lambda self, b: None,
                               "close": lambda self: None})()

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired("xclip", timeout or 0)

    monkeypatch.setattr(_clip.subprocess, "Popen", lambda *a, **k: Proc())
    ok, msg = _clip.copy("hello")
    assert ok is True
    assert "xclip" in msg


def test_nonzero_exit_is_a_failure(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(_clip.shutil, "which", lambda c: c == "xclip")

    class Proc:
        stdin = type("W", (), {"write": lambda self, b: None,
                               "close": lambda self: None})()

        def wait(self, timeout=None):
            return 1

    monkeypatch.setattr(_clip.subprocess, "Popen", lambda *a, **k: Proc())
    ok, msg = _clip.copy("hello")
    assert ok is False
    assert "exited 1" in msg


def test_dump_writes_the_file(tmp_path):
    dest = tmp_path / "nested" / "log.txt"
    ok, msg = _clip.dump("line one\n", dest)
    assert ok and dest.read_text(encoding="utf-8") == "line one\n"
    assert str(dest) in msg


def test_copy_or_dump_falls_back_to_a_file(monkeypatch, tmp_path):
    """The whole point: a machine with no clipboard still keeps the text."""
    monkeypatch.setattr(_clip.shutil, "which", lambda _c: None)
    dest = tmp_path / "out.txt"
    msg = _clip.copy_or_dump("payload", dest)
    assert dest.read_text(encoding="utf-8") == "payload"
    assert "no clipboard tool" in msg and str(dest) in msg


def test_dump_failure_is_reported_not_raised(tmp_path):
    ok, msg = _clip.dump("x", tmp_path)      # a directory, not a file
    assert ok is False
    assert "could not write" in msg
