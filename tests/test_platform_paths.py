"""Sanity checks for the cross-platform Ravenswatch path discovery.

The full discovery is best exercised on each real host, but we can
pin the contract a quick refactor would break:

  * `_steam_roots()` returns at least one absolute path per platform.
  * `_parse_libraryfolders_vdf()` extracts `"path"` entries from the
    handful of VDF shapes Steam has actually shipped.
  * `_game_dir_candidates()` survives OSError from `Path.exists()` on
    drive enumeration (regression: Windows D:\\ with WinError 1005).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rsmm.engine import paths as paths_mod


def test_steam_roots_returns_absolute_paths():
    roots = paths_mod._steam_roots()
    assert roots, "expected at least one steam root candidate"
    for r in roots:
        assert isinstance(r, Path)
        assert r.is_absolute()


def test_parse_libraryfolders_vdf_flat(tmp_path):
    vdf = tmp_path / "libraryfolders.vdf"
    vdf.write_text(
        '"libraryfolders"\n'
        '{\n'
        '\t"0"\n'
        '\t{\n'
        '\t\t"path"\t\t"/home/u/.steam/steam"\n'
        '\t}\n'
        '\t"1"\n'
        '\t{\n'
        '\t\t"path"\t\t"D:\\\\Games\\\\SteamLibrary"\n'
        '\t}\n'
        '}\n',
        encoding="utf-8",
    )
    libs = paths_mod._parse_libraryfolders_vdf(vdf)
    assert any(str(p).endswith(".steam/steam") for p in libs)
    # Backslash-escaped Windows path round-trips into a single backslash.
    assert any("Games" in str(p) and "SteamLibrary" in str(p) for p in libs)


def test_parse_libraryfolders_vdf_missing_file(tmp_path):
    """A missing file must not throw — Steam may not be installed."""
    assert paths_mod._parse_libraryfolders_vdf(tmp_path / "does_not_exist.vdf") == []


def test_game_dir_candidates_dedupes():
    cands = paths_mod._game_dir_candidates()
    assert cands, "expected at least one candidate"
    assert len(cands) == len(set(cands)), "candidates should be de-duplicated"


def test_game_dir_candidates_survives_oserror(monkeypatch):
    """The Windows D:\\ enumeration crashed customers with WinError 1005.
    `_game_dir_candidates()` must keep running when `Path.exists()`
    raises OSError, not bubble it up.
    """
    original_exists = Path.exists

    def flaky_exists(self):
        # Pretend any C-drive style path raises.
        if str(self).startswith("Z:"):
            raise OSError(1005, "fake")
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", flaky_exists)
    # Should not raise.
    cands = paths_mod._game_dir_candidates()
    assert isinstance(cands, list)


def test_default_game_dir_returns_path():
    p = paths_mod.default_game_dir()
    assert isinstance(p, Path)
    assert p.is_absolute()


def test_mods_dir_respects_env_override(monkeypatch, tmp_path):
    target = tmp_path / "alt_mods"
    monkeypatch.setenv("RSMM_MODS_DIR", str(target))
    assert paths_mod.mods_dir() == target.resolve()


def test_mods_dir_uses_repo_root_when_unset(monkeypatch):
    monkeypatch.delenv("RSMM_MODS_DIR", raising=False)
    md = paths_mod.mods_dir()
    assert md == paths_mod.REPO_ROOT / "mods"


def test_pep562_getattr_returns_mods_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("RSMM_MODS_DIR", str(tmp_path))
    # Access via `getattr` to exercise the module-level `__getattr__`.
    assert paths_mod.__getattr__("MODS_DIR") == tmp_path.resolve()


def test_pep562_getattr_raises_for_unknown():
    with pytest.raises(AttributeError):
        paths_mod.__getattr__("NOT_A_REAL_ATTR")
