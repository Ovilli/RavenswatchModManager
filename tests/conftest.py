"""Shared pytest fixtures + repo-state guards.

1. Make `src/` importable when running pytest from a source checkout
   without first running `pip install -e .`.
2. Fail loudly if any test mutates a git-tracked file under `data/`.
   Historically `tests/test_*` that exercised the asset-map pipeline could
   clobber the real `data/asset_map.json` (6 MB), forcing a `git checkout`
   between runs and making the suite non-idempotent. Tests must monkeypatch
   `apply_mods.ASSET_MAP_JSON` / stub `find_iyg.main` to write under tmp_path
   instead. This guard catches regressions of that pattern.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# Fixtures that scan/parse the full shipped corpus (rglob over the ~35k-file
# _Cooking dir). Any test consuming one pays a multi-minute setup, re-run per
# xdist worker — these are the suite's real cost. Auto-mark them `slow` so
# `-m 'not slow'` (the fast dev path) skips them; full CI still runs them. The
# co-located fast `*_handler_registered` unit tests take no such fixture and
# stay in the fast subset.
_CORPUS_FIXTURES = frozenset({
    "animation_samples", "gv_samples", "es_samples",
    "geometry_samples", "texture_samples", "files_by_class",
})


def pytest_collection_modifyitems(items):
    for item in items:
        if _CORPUS_FIXTURES & set(getattr(item, "fixturenames", ())):
            item.add_marker(pytest.mark.slow)


@pytest.fixture(scope="session")
def _tracked_data_files() -> list[Path]:
    """Git-tracked files under `data/`. Empty if git is unavailable."""
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "data/"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return []
    files = [REPO_ROOT / line for line in out.splitlines() if line]
    return [p for p in files if p.is_file()]


def _snapshot(files: list[Path]) -> dict[Path, tuple[int, int]]:
    snap: dict[Path, tuple[int, int]] = {}
    for p in files:
        try:
            st = p.stat()
        except OSError:
            continue
        snap[p] = (st.st_size, st.st_mtime_ns)
    return snap


@pytest.fixture(autouse=True)
def _guard_tracked_data(_tracked_data_files, request):
    """Fail the offending test if it touches a tracked `data/` file.

    Cheap: stat() only, no content hashing (asset_map.json is ~6 MB).
    A changed mtime — even to identical bytes — is still a test writing
    where it must not, so a false positive here is a real bug.
    """
    if not _tracked_data_files:
        yield
        return
    before = _snapshot(_tracked_data_files)
    yield
    after = _snapshot(_tracked_data_files)
    changed = sorted(
        str(p.relative_to(REPO_ROOT)) for p in before if after.get(p) != before[p]
    )
    if changed:
        pytest.fail(
            f"Test '{request.node.nodeid}' mutated git-tracked data file(s): "
            f"{', '.join(changed)}. Tests must redirect writes to tmp_path "
            "(monkeypatch apply_mods.ASSET_MAP_JSON, stub find_iyg.main). "
            f"Restore with: git checkout -- {' '.join(changed)}",
            pytrace=False,
        )
