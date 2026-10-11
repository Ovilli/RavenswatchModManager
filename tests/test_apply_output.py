"""What `rsmm apply` prints: a summary per mod, not a line per file.

A custom hero installs hundreds of files; one line each buried the warnings
and merges that matter. Per-file lines are behind --verbose / RSMM_VERBOSE.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from rsmm.cli import apply_mods as A


@pytest.fixture
def quiet(monkeypatch):
    monkeypatch.setattr(A, "_VERBOSE", False)


def _adds(mod: str, n: int, prefix: str):
    return [(f"{prefix}{i}", Path("s"), Path("d"), mod) for i in range(n)]


def test_one_line_per_mod_with_its_new_files(quiet, capsys):
    adds = _adds("nyx", 359, "n") + _adds("unfog", 1, "u")
    A._print_apply_summary(adds, ["r1", "r2"], {f"n{i}" for i in range(345)}, 0, False)
    out = capsys.readouterr().out.splitlines()
    assert out[0].split() == ["+", "nyx", "installed", "359", "file(s),", "345", "new"]
    assert out[1].split() == ["+", "unfog", "installed", "1", "file(s)"]
    assert "restored 2 original file(s)" in out[2]
    assert "--verbose" in out[3]
    assert len(out) == 4                      # not one line per file


def test_a_dry_run_says_would(quiet, capsys):
    A._print_apply_summary(_adds("nyx", 3, "n"), [], set(), 0, True)
    assert "would install 3 file(s)" in capsys.readouterr().out


def test_per_file_lines_only_with_verbose(monkeypatch, capsys):
    monkeypatch.setattr(A, "_VERBOSE", False)
    A._detail("  + apply  Zsdgs  <- nyx/file")
    assert capsys.readouterr().out == ""
    monkeypatch.setattr(A, "_VERBOSE", True)
    A._detail("  + apply  Zsdgs  <- nyx/file")
    assert "Zsdgs" in capsys.readouterr().out


def test_the_live_counter_stays_off_when_not_a_terminal(quiet, capsys):
    p = A._Progress("installing", 10)
    for _ in range(10):
        p.step()
    p.done()
    assert capsys.readouterr().out == ""      # piped output stays clean


def test_an_engine_warning_names_the_mod(monkeypatch, capsys):
    monkeypatch.setattr(A, "_CURRENT_MOD", ["custom-hero-test"])
    log = logging.getLogger("rsmm")
    before = list(log.handlers)
    try:
        A._install_warning_handler()
        A._install_warning_handler()          # idempotent: no double printing
        logging.getLogger("rsmm.engine.geometry_cook").warning("mesh will tear")
    finally:
        log.handlers[:] = before
    err = capsys.readouterr().err.splitlines()
    assert len(err) == 1
    assert err[0].strip().endswith("custom-hero-test: mesh will tear")
