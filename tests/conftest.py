"""Shared pytest fixtures + repo-state guards.

1. Make `src/` importable when running pytest from a source checkout
   without first running `pip install -e .`.
2. Fail loudly if any test mutates a git-tracked file under `data/`.
   Historically `tests/test_*` that exercised the asset-map pipeline could
   clobber the real `data/asset_map.json` (6 MB), forcing a `git checkout`
   between runs and making the suite non-idempotent. Tests must monkeypatch
   `apply_mods.ASSET_MAP_JSON` / stub `find_iyg.main` to write under tmp_path
   instead. This guard catches regressions of that pattern.
3. Fail loudly if a test freezes one of `rsmm.engine.paths`' lazy PEP 562
   attributes, or writes into the developer's real `mods/`. These are the
   same failure: see `_guard_lazy_paths` for why one causes the other.
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


# --------------------------------------------------------------------------
# Lazy-path + real-mods-dir guards
# --------------------------------------------------------------------------

#: `rsmm.engine.paths` resolves these through a module-level PEP 562
#: `__getattr__` so importing the module doesn't trigger a disk scan, and so
#: the `RSMM_MODS_DIR` / `RSMM_GAME_DIR` env overrides are honoured at *call*
#: time.
_LAZY_PATH_ATTRS = ("MODS_DIR", "DEFAULT_GAME_DIR")


@pytest.fixture(autouse=True)
def _guard_lazy_paths(request):
    """Fail any test that leaves a lazy path attribute frozen in the module.

    `monkeypatch.setattr("rsmm.engine.paths.MODS_DIR", x)` looks harmless but
    is a session-wide landmine. `MODS_DIR` is not in the module dict — it is
    served by `__getattr__` — so monkeypatch reads the *real* repo `mods/` as
    the "old value", writes a genuine dict entry, and on undo writes that real
    path back into the dict. `__getattr__` is never consulted again, not even
    after `importlib.reload`, so every later test's `RSMM_MODS_DIR` override is
    silently ignored and commands like `rsmm new` scaffold into the
    developer's actual `mods/` directory.

    That is exactly what happened: `test_doctor.py` patched this attribute and
    `test_cmd_new_item.py` — which runs later in a serial run, but lands on a
    different xdist worker in the parallel one — then wrote `mods/demo` for
    real and failed on the second attempt. The supported seam is
    `monkeypatch.setenv("RSMM_MODS_DIR", ...)`.

    The guard also deletes the frozen key, so one offending test cannot take
    the rest of the session down with it.
    """
    yield
    paths = sys.modules.get("rsmm.engine.paths")
    if paths is None:
        return
    frozen = [n for n in _LAZY_PATH_ATTRS if n in vars(paths)]
    for name in frozen:
        delattr(paths, name)  # restore laziness for the remaining tests
    if frozen:
        pytest.fail(
            f"Test '{request.node.nodeid}' froze lazy path attribute(s) "
            f"{', '.join(frozen)} into rsmm.engine.paths. Use "
            "monkeypatch.setenv('RSMM_MODS_DIR'/'RSMM_GAME_DIR', ...) instead "
            "of monkeypatch.setattr on the module attribute — setattr's undo "
            "writes the real path into the module dict and permanently "
            "shadows the PEP 562 __getattr__.",
            pytrace=False,
        )


@pytest.fixture(autouse=True)
def _guard_real_mods_dir(request):
    """Fail any test that adds to or removes from the developer's `mods/`.

    Backstop for the above: whatever the mechanism, a test must never write
    into the real mods directory. Names only — a test legitimately reading a
    mod must not be penalised for a mtime change.
    """
    real_mods = REPO_ROOT / "mods"

    def snapshot() -> set[str] | None:
        try:
            return {p.name for p in real_mods.iterdir()}
        except OSError:
            return None

    before = snapshot()
    yield
    after = snapshot()
    if before is None or after is None or before == after:
        return
    added = sorted(after - before)
    removed = sorted(before - after)
    detail = []
    if added:
        detail.append(f"created {', '.join(added)}")
    if removed:
        detail.append(f"removed {', '.join(removed)}")
    pytest.fail(
        f"Test '{request.node.nodeid}' modified the real mods directory "
        f"({real_mods}): {'; '.join(detail)}. Redirect writes with "
        "monkeypatch.setenv('RSMM_MODS_DIR', str(tmp_path)).",
        pytrace=False,
    )
