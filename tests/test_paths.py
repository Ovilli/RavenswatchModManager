"""Tests for engine path resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_constants_exist():
    from rsmm.engine.paths import (
        ASSET_MAP_CSV,
        ASSET_MAP_JSON,
        COOKING_SUBDIR,
        DATA_DIR,
        DEFAULT_GAME_DIR,
        DIST_DIR,
        MODS_DIR,
        REPO_ROOT,
    )
    assert REPO_ROOT.is_dir()
    assert DATA_DIR.is_dir()
    assert ASSET_MAP_JSON.name == "asset_map.json"
    assert ASSET_MAP_CSV.name == "asset_map.csv"
    assert COOKING_SUBDIR == "DarkTalesResources/_Cooking"
    assert isinstance(DEFAULT_GAME_DIR, Path)
    assert isinstance(DIST_DIR, Path)
    assert isinstance(MODS_DIR, Path)


def test_game_dir_candidates():
    from rsmm.engine.paths import _game_dir_candidates
    cands = _game_dir_candidates()
    assert len(cands) > 0
    assert all(isinstance(c, Path) for c in cands)
    # De-duped.
    assert len(cands) == len(set(cands))


def test_game_dir_candidates_windows_bad_drive(monkeypatch):
    from rsmm.engine import paths as paths_mod

    monkeypatch.setattr(paths_mod.sys, "platform", "win32", raising=False)

    real_exists = Path.exists

    def fake_exists(self: Path) -> bool:
        if self == Path("D:\\"):
            raise OSError("bad drive")
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)

    cands = paths_mod._game_dir_candidates()
    assert all(isinstance(c, Path) for c in cands)


def test_find_repo_root():
    from rsmm.engine.paths import _find_repo_root
    root = _find_repo_root()
    assert (root / "data" / "asset_map.json").exists()


def test_find_repo_root_warns_and_falls_back(monkeypatch, capsys):
    """When `data/asset_map.json` is missing from every parent, the
    finder emits a stderr warning and returns a best-effort fallback so
    `import rsmm.engine.paths` does not crash on partial installs. The
    actual asset-map-required code paths report their own clear errors
    later."""
    from rsmm.engine import paths as paths_mod

    real_exists = Path.exists

    def fake_exists(self: Path) -> bool:
        if self.name == "asset_map.json":
            return False
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)
    root = paths_mod._find_repo_root()
    assert isinstance(root, Path)
    captured = capsys.readouterr()
    assert "rsmm repo root not found" in captured.err


def test_find_repo_root_frozen_uses_meipass(monkeypatch, tmp_path):
    from rsmm.engine import paths as paths_mod

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "asset_map.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(paths_mod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths_mod.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(paths_mod.sys, "executable", str(tmp_path / "rsmm.exe"), raising=False)

    assert paths_mod._find_repo_root() == tmp_path.resolve()


def test_find_repo_root_frozen_fallback_without_asset_map(monkeypatch, tmp_path):
    from rsmm.engine import paths as paths_mod

    monkeypatch.setattr(paths_mod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths_mod.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(paths_mod.sys, "executable", str(tmp_path / "rsmm.exe"), raising=False)

    root = paths_mod._find_repo_root()
    assert root.is_dir()


def test_mods_dir_env_override(monkeypatch, tmp_path):
    from rsmm.engine.paths import mods_dir
    target = tmp_path / "custom-mods"
    target.mkdir()
    monkeypatch.setenv("RSMM_MODS_DIR", str(target))
    assert mods_dir() == target.resolve()


def test_mods_dir_default(monkeypatch):
    from rsmm.engine.paths import REPO_ROOT, mods_dir
    monkeypatch.delenv("RSMM_MODS_DIR", raising=False)
    assert mods_dir() == REPO_ROOT / "mods"


def test_default_game_dir_scan_is_cached(monkeypatch):
    """The expensive part — the candidate scan — runs once per process.

    Patch `_game_dir_candidates`, not `_scan_game_dir.__wrapped__`: an
    `lru_cache` wrapper calls the function it closed over at decoration time,
    so rebinding `__wrapped__` counts nothing. This test asserted only
    `a == b` and would have passed with the caching removed entirely.
    """
    from rsmm.engine import paths as paths_mod
    from rsmm.engine.paths import default_game_dir

    monkeypatch.delenv("RSMM_GAME_DIR", raising=False)
    calls = {"n": 0}
    real = paths_mod._game_dir_candidates

    def counting():
        calls["n"] += 1
        return real()

    monkeypatch.setattr(paths_mod, "_game_dir_candidates", counting)
    paths_mod._scan_game_dir.cache_clear()
    try:
        a = default_game_dir()
        b = default_game_dir()
        assert a == b
        assert calls["n"] == 1, "the candidate scan must not re-run per call"
    finally:
        paths_mod._scan_game_dir.cache_clear()


def test_default_game_dir_override_wins_after_first_call(monkeypatch, tmp_path):
    """`RSMM_GAME_DIR` must be honoured at call time, not just on first call.

    The whole function used to be `@cache`d, so a long-lived process that set
    the override after any earlier resolution kept the stale autodetected path.
    """
    from rsmm.engine.paths import default_game_dir

    monkeypatch.delenv("RSMM_GAME_DIR", raising=False)
    default_game_dir()                      # prime whatever cache exists
    (tmp_path / "later").mkdir()
    monkeypatch.setenv("RSMM_GAME_DIR", str(tmp_path / "later"))
    assert default_game_dir() == tmp_path / "later"


def test_steam_libraryfolders_vdf_parse(tmp_path, monkeypatch):
    from rsmm.engine import paths as paths_mod

    vdf = tmp_path / "libraryfolders.vdf"
    vdf.write_text(
        '"libraryfolders"\n'
        '{\n'
        '\t"0"\n'
        '\t{\n'
        '\t\t"path"\t\t"' + str(tmp_path / "main").replace("\\", "\\\\") + '"\n'
        '\t}\n'
        '\t"1"\n'
        '\t{\n'
        '\t\t"path"\t\t"' + str(tmp_path / "extra").replace("\\", "\\\\") + '"\n'
        '\t}\n'
        '}\n',
        encoding="utf-8",
    )
    roots = paths_mod._parse_libraryfolders_vdf(vdf)
    assert tmp_path / "main" in roots
    assert tmp_path / "extra" in roots


def test_parse_libraryfolders_vdf_missing(tmp_path):
    from rsmm.engine.paths import _parse_libraryfolders_vdf
    assert _parse_libraryfolders_vdf(tmp_path / "nope.vdf") == []


def test_game_fingerprint_stable(tmp_path):
    from rsmm.engine.paths import game_fingerprint
    game = tmp_path / "game"
    (game / "DarkTalesResources").mkdir(parents=True)
    (game / "Ravenswatch.exe").write_bytes(b"binary-bytes-here" * 64)
    (game / "DarkTalesResources" / "UsedRscList.ot").write_bytes(b"ot-payload" * 32)
    a = game_fingerprint(game)
    b = game_fingerprint(game)
    assert a == b
    assert len(a) == 64


def test_game_fingerprint_detects_change(tmp_path):
    from rsmm.engine.paths import game_fingerprint
    game = tmp_path / "game"
    game.mkdir()
    exe = game / "Ravenswatch.exe"
    exe.write_bytes(b"v1" * 64)
    a = game_fingerprint(game)
    exe.write_bytes(b"v2" * 64)
    b = game_fingerprint(game)
    assert a != b


def test_load_stored_fingerprint_missing(tmp_path):
    from rsmm.engine.paths import load_stored_fingerprint
    assert load_stored_fingerprint(tmp_path) is None


def test_load_stored_fingerprint_malformed(tmp_path):
    from rsmm.engine.paths import COOKING_SUBDIR, GAME_VERSION_FINGERPRINT, load_stored_fingerprint
    fp = tmp_path / COOKING_SUBDIR / GAME_VERSION_FINGERPRINT
    fp.parent.mkdir(parents=True)
    fp.write_text("{not json", encoding="utf-8")
    assert load_stored_fingerprint(tmp_path) is None


def test_load_stored_fingerprint_bad_encoding(tmp_path):
    from rsmm.engine.paths import COOKING_SUBDIR, GAME_VERSION_FINGERPRINT, load_stored_fingerprint
    fp = tmp_path / COOKING_SUBDIR / GAME_VERSION_FINGERPRINT
    fp.parent.mkdir(parents=True)
    fp.write_bytes(b"\xff\xfe\x00bogus")
    assert load_stored_fingerprint(tmp_path) is None


def test_save_fingerprint_atomic(tmp_path):
    from rsmm.engine.paths import (
        COOKING_SUBDIR,
        GAME_VERSION_FINGERPRINT,
        load_stored_fingerprint,
        save_fingerprint,
    )
    save_fingerprint(tmp_path, "deadbeef")
    fp = tmp_path / COOKING_SUBDIR / GAME_VERSION_FINGERPRINT
    assert fp.exists()
    payload = json.loads(fp.read_text(encoding="utf-8"))
    assert payload["fingerprint"] == "deadbeef"
    assert isinstance(payload["ts"], (int, float))
    # No leftover .tmp file.
    assert not (fp.parent / (fp.name + ".tmp")).exists()
    assert load_stored_fingerprint(tmp_path) == "deadbeef"
