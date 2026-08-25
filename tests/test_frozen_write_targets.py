"""Nothing the CLI writes at runtime may land inside the frozen bundle.

A onefile PyInstaller build unpacks itself into `_MEIPASS`, a temp directory
it DELETES when the process exits. `REPO_ROOT` resolves there, so
`REPO_ROOT`-derived write targets succeed, report success, and are gone by the
next invocation — a failure mode that never shows up in a source checkout and
is invisible in the shipped app.

Two live examples this file pins:

* `rsmm json pack-mod` writes a zip and returns its path for a SEPARATE
  `upload-bytes` process. Under `_MEIPASS` that second process finds nothing.
* the corpus sweep cache re-built itself on every single run forever, while
  looking like a cache.

Read locations (`DIST_DIR/winhttp.dll`, `DATA_DIR/*.json`) are the opposite
case: those are bundled INTO `_MEIPASS` and must keep pointing at it.
"""

import importlib
import sys
import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def frozen(monkeypatch, tmp_path):
    """Reload rsmm.engine.paths as if we were the onefile sidecar."""
    mei = tmp_path / "MEIPASS"
    (mei / "data").mkdir(parents=True)
    (mei / "data" / "asset_map.json").write_text("{}", encoding="utf-8")
    (mei / "dist").mkdir()
    (mei / "dist" / "winhttp.dll").write_bytes(b"bundled loader")

    monkeypatch.delenv("RSMM_REPO_ROOT", raising=False)
    monkeypatch.setenv("RSMM_DATA_DIR", str(tmp_path / "userdata"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(mei), raising=False)

    import rsmm.engine.paths as paths
    paths = importlib.reload(paths)
    yield paths, mei
    monkeypatch.undo()
    importlib.reload(paths)


def test_repo_root_is_the_bundle_when_frozen(frozen):
    paths, mei = frozen
    assert paths.REPO_ROOT == mei


def test_pack_output_escapes_the_bundle(frozen, tmp_path):
    paths, mei = frozen
    out = paths.dist_out_dir()
    assert mei not in out.parents and out != mei, (
        f"pack output {out} is inside the bundle; it will not survive the process"
    )
    assert out == tmp_path / "userdata" / "dist"


def test_bundled_loader_dll_still_reads_from_the_bundle(frozen):
    """The other direction: DIST_DIR is a READ path and must not move."""
    paths, mei = frozen
    assert (paths.DIST_DIR / "winhttp.dll").read_bytes() == b"bundled loader"


def test_asset_map_escapes_the_bundle(frozen, tmp_path):
    paths, _mei = frozen
    assert paths.ASSET_MAP_JSON.parent == tmp_path / "userdata" / "data"


def test_dist_out_dir_is_the_repo_in_source_mode():
    from rsmm.engine import paths
    assert paths.dist_out_dir() == paths.DIST_DIR


def test_corpus_cache_escapes_the_bundle(monkeypatch, tmp_path):
    monkeypatch.setenv("RSMM_DATA_DIR", str(tmp_path / "userdata"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    from rsmm.engine import corpus_cache
    assert corpus_cache._cache_dir() == tmp_path / "userdata" / ".corpus_cache"
