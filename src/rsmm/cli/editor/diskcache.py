"""Editor answers kept on disk, so a new launch does not re-parse the game.

The read routes an editor lists in ``CACHED`` are pure functions of the game
data: the cooked files (pristine copy first), the asset map, the dev mirror,
and the rsmm code that reads them. Every launch used to recompute them from
scratch, which is seconds of parsing per tab (talents for one hero ~1 s, the
stat list ~1.5 s, a chapter's scene and terrain layers ~1 s each).

A response is stored under a FINGERPRINT of everything it depends on, so a
stale answer is never served: a game update (exe + pristine manifest), any
apply or restore (the state file), a rebuilt asset map, an edited mirror, or a
different rsmm build each name a different directory, and the old one is
deleted when a new one is made. Only 200 JSON answers are stored.

The local editor turns this on; the web editor (Pyodide, an in-memory disk)
does not. Nothing here is needed for correctness: any I/O error simply
recomputes the answer.
"""

from __future__ import annotations

import gzip
import hashlib
import os
import shutil
import sys
import threading
from pathlib import Path

#: Bumped when a stored answer's meaning changes without the code changing.
_SCHEMA = 1
_lock = threading.Lock()
_fp: str | None = None


def _stat(p: Path) -> str:
    try:
        st = p.stat()
    except OSError:
        return "-"
    return f"{st.st_size}:{st.st_mtime_ns}"


def _code() -> str:
    """The rsmm build: the frozen executable, or every source and data file."""
    if getattr(sys, "frozen", False):
        return "frozen:" + _stat(Path(sys.executable))
    from rsmm.engine.paths import DATA_DIR
    h = hashlib.sha1()
    src = Path(__file__).resolve().parents[2]            # src/rsmm
    for root, sub in ((src, True), (DATA_DIR, False)):
        files = root.rglob("*") if sub else root.glob("*")
        for p in sorted(files):
            if p.is_file() and "__pycache__" not in p.parts and not p.name.startswith("."):
                h.update(f"{p}={_stat(p)};".encode())
    return h.hexdigest()


def _game() -> str:
    from rsmm.cli.apply_mods import find_game_dir
    from rsmm.engine.paths import ASSET_MAP_JSON, COOKING_REL, DATA_DIR, game_fingerprint

    parts = [_stat(ASSET_MAP_JSON)]
    game = find_game_dir()
    if game is not None:
        parts += [str(game), game_fingerprint(game),
                  _stat(game / COOKING_REL / ".rsmm_state.json")]
    mirror = DATA_DIR / "uncooked"
    if mirror.is_dir():
        from rsmm.engine.corpus_cache import _fingerprint
        parts.append(_fingerprint(mirror))
    return "|".join(parts)


def fingerprint() -> str:
    """Computed once per process: the editor assumes, like its in-memory
    caches, that nothing it reads changes while it runs."""
    global _fp
    with _lock:
        if _fp is None:
            raw = f"{_SCHEMA}|{_code()}|{_game()}"
            _fp = hashlib.sha1(raw.encode()).hexdigest()[:16]
        return _fp


def _dir() -> Path:
    from rsmm.engine.paths import user_data_dir
    return user_data_dir() / "editor_cache"


def _path(key: str) -> Path:
    return _dir() / fingerprint() / (hashlib.sha1(key.encode()).hexdigest() + ".json.gz")


def get(key: str) -> bytes | None:
    try:
        return gzip.decompress(_path(key).read_bytes())
    except (OSError, EOFError, gzip.BadGzipFile):
        return None


def put(key: str, data: bytes) -> None:
    try:
        dest = _path(key)
        if not dest.parent.is_dir():
            dest.parent.mkdir(parents=True, exist_ok=True)
            for old in dest.parent.parent.iterdir():     # answers for older data
                if old.is_dir() and old.name != dest.parent.name:
                    shutil.rmtree(old, ignore_errors=True)
        tmp = dest.with_name(f"{dest.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_bytes(gzip.compress(data, compresslevel=1))
        os.replace(tmp, dest)
    except OSError:
        pass
