"""Tests for the data-only pattern-DB update channel (rsmm update-data)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rsmm.engine import data_update
from rsmm.engine.data_update import (
    DataUpdateError,
    apply_update,
    check,
    planted_dir,
)

PATTERNS = [
    {"name": "FUN_140319f00", "addr": "0x140319f00", "pattern": "40 53 ?? 8d",
     "match_index": 0},
    {"name": "FUN_1401dea90", "addr": "0x1401dea90", "pattern": "48 89 5c ??",
     "match_index": 0},
]


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture
def remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake remote (served via file://) with patterns + meta published."""
    rdir = tmp_path / "remote"
    rdir.mkdir()
    raw = json.dumps(PATTERNS).encode()
    (rdir / "function_patterns.json").write_bytes(raw)
    (rdir / "function_patterns.meta.json").write_text(json.dumps({
        "schema": 1,
        "generated": "2026-07-09T00:00:00+00:00",
        "game_exe_sha256": _sha(b"EXE-BYTES"),
        "game_exe_size": 9,
        "pattern_count": len(PATTERNS),
        "patterns_sha256": _sha(raw),
    }))
    monkeypatch.setenv("RSMM_DATA_UPDATE_BASE", rdir.as_uri())
    return rdir


@pytest.fixture
def game_dir(tmp_path: Path) -> Path:
    g = tmp_path / "game"
    g.mkdir()
    (g / "Ravenswatch.exe").write_bytes(b"EXE-BYTES")
    return g


def test_check_not_planted(remote: Path, game_dir: Path):
    st = check(game_dir)
    assert st["status"] == "not_planted"
    assert st["exe_match"] is True


def test_apply_plants_patterns_and_meta(remote: Path, game_dir: Path):
    st = apply_update(game_dir)
    assert st["status"] == "updated"
    assert st["pattern_count"] == len(PATTERNS)
    planted = planted_dir(game_dir)
    assert json.loads((planted / "function_patterns.json").read_text()) == PATTERNS
    meta = json.loads((planted / "function_patterns.meta.json").read_text())
    assert meta["pattern_count"] == len(PATTERNS)


def test_up_to_date_after_apply(remote: Path, game_dir: Path):
    apply_update(game_dir)
    assert check(game_dir)["status"] == "up_to_date"


def test_update_available_when_remote_changes(remote: Path, game_dir: Path):
    apply_update(game_dir)
    new = [*PATTERNS, {"name": "FUN_140000000", "addr": "0x140000000",
                       "pattern": "cc cc ?? cc", "match_index": 0}]
    raw = json.dumps(new).encode()
    (remote / "function_patterns.json").write_bytes(raw)
    meta = json.loads((remote / "function_patterns.meta.json").read_text())
    meta["patterns_sha256"] = _sha(raw)
    meta["pattern_count"] = len(new)
    (remote / "function_patterns.meta.json").write_text(json.dumps(meta))

    st = check(game_dir)
    assert st["status"] == "update_available"
    st = apply_update(game_dir, st)
    assert st["status"] == "updated"
    assert st["pattern_count"] == 3


def test_hash_mismatch_rejected(remote: Path, game_dir: Path):
    meta = json.loads((remote / "function_patterns.meta.json").read_text())
    meta["patterns_sha256"] = "0" * 64
    (remote / "function_patterns.meta.json").write_text(json.dumps(meta))
    with pytest.raises(DataUpdateError, match="hash mismatch"):
        apply_update(game_dir)
    assert not (planted_dir(game_dir) / "function_patterns.json").exists()


def test_missing_meta_falls_back_to_direct_hash(remote: Path, game_dir: Path):
    (remote / "function_patterns.meta.json").unlink()
    st = check(game_dir)
    assert st["remote_meta"] is None
    assert st["exe_match"] is None
    st = apply_update(game_dir, st)
    assert st["status"] == "updated"
    # No meta upstream -> no meta planted.
    assert not (planted_dir(game_dir) / "function_patterns.meta.json").exists()


def test_exe_mismatch_flagged(remote: Path, game_dir: Path):
    (game_dir / "Ravenswatch.exe").write_bytes(b"DIFFERENT-BUILD")
    st = check(game_dir)
    assert st["exe_match"] is False


def test_invalid_remote_json_rejected(remote: Path, game_dir: Path):
    raw = b"not json at all"
    (remote / "function_patterns.json").write_bytes(raw)
    meta = json.loads((remote / "function_patterns.meta.json").read_text())
    meta["patterns_sha256"] = _sha(raw)
    (remote / "function_patterns.meta.json").write_text(json.dumps(meta))
    with pytest.raises(DataUpdateError, match="not valid JSON"):
        apply_update(game_dir)


def test_empty_pattern_list_rejected(remote: Path, game_dir: Path):
    raw = b"[]"
    (remote / "function_patterns.json").write_bytes(raw)
    meta = json.loads((remote / "function_patterns.meta.json").read_text())
    meta["patterns_sha256"] = _sha(raw)
    (remote / "function_patterns.meta.json").write_text(json.dumps(meta))
    with pytest.raises(DataUpdateError, match="empty"):
        apply_update(game_dir)


def test_refuses_plain_http(monkeypatch: pytest.MonkeyPatch):
    with pytest.raises(DataUpdateError, match="non-HTTPS"):
        data_update._fetch("http://example.com/x.json")


def test_cli_check_json(remote: Path, game_dir: Path, capsys, monkeypatch):
    import sys

    from rsmm.cli import cmd_update_data

    monkeypatch.setattr(sys, "argv",
                        ["update-data", "--check", "--json",
                         "--game-dir", str(game_dir)])
    assert cmd_update_data.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "not_planted"
    assert out["exe_match"] is True
    # --check must never write.
    assert not (planted_dir(game_dir) / "function_patterns.json").exists()


def test_cli_install_json(remote: Path, game_dir: Path, capsys, monkeypatch):
    import sys

    from rsmm.cli import cmd_update_data

    monkeypatch.setattr(sys, "argv",
                        ["update-data", "--json", "--game-dir", str(game_dir)])
    assert cmd_update_data.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "updated"
    assert (planted_dir(game_dir) / "function_patterns.json").exists()
