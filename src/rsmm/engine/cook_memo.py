"""Content-addressed memo for the expensive, pure cookers.

A content kind re-emits every file on every ``apply``, and the slow part is
almost never the edit the author just made: a custom hero spends ~8 s cooking
its ``.glb`` and ~16 s decoding its PNGs although neither changed since the last
apply. :func:`cached` keys a cook on the exact bytes that go into it (plus the
cooker code itself), so an unchanged model or texture is read back instead of
cooked again — whatever else in the mod changed.

What is safe to put through it: a function of its inputs only. ``cook_model``
and ``cook_texture`` are (bytes in, bytes out, no I/O); anything that reads the
game install or the mod tree is not, and must not be memoised here.

Two things a cache must not lose:

* **Warnings.** The geometry cooker logs real problems ("the mesh does not
  overlap the bind pose", "bone names not on the skeleton"). Those are recorded
  with the entry and replayed on every hit, so a cached cook says exactly what
  a fresh one would.
* **Code changes.** The key includes a fingerprint of the cooker sources (of
  the executable, when frozen), so fixing a cooker invalidates every entry it
  produced instead of serving stale bytes.

Frozen builds keep the cache under :func:`~rsmm.engine.paths.user_data_dir`:
``REPO_ROOT`` is PyInstaller's ``_MEIPASS`` there, deleted on exit, and a cache
written into it would look like it works while rebuilding on every run (the
trap ``corpus_cache`` documents). Safe to delete at any time.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path

from .paths import REPO_ROOT, user_data_dir

#: Bumped when an entry's on-disk SHAPE changes.
_SCHEMA = 1
#: The cache is trimmed back under this many bytes, oldest entries first.
_MAX_BYTES = 2 * 1024 ** 3


def cache_dir() -> Path:
    override = os.environ.get("RSMM_COOK_CACHE", "").strip()
    if override:
        return Path(override).expanduser()
    if getattr(sys, "frozen", False):
        return user_data_dir() / "cook_cache"
    return REPO_ROOT / ".rsmm" / "cook_memo"


def enabled() -> bool:
    """``RSMM_NO_COOK_CACHE=1`` turns the memo off (cook every time)."""
    return os.environ.get("RSMM_NO_COOK_CACHE", "").strip() not in ("1", "true", "yes")


@functools.cache
def code_fingerprint() -> str:
    """Identity of the code that cooks: every ``rsmm`` source file, or the
    frozen executable. Any code change therefore misses every old entry (the
    apply-time emit cache keys on this too)."""
    h = hashlib.sha256(str(_SCHEMA).encode())
    if getattr(sys, "frozen", False):
        st = os.stat(sys.executable)
        h.update(f"{sys.executable}:{st.st_size}:{st.st_mtime_ns}".encode())
        return h.hexdigest()
    root = Path(__file__).resolve().parent.parent      # the rsmm package
    for p in sorted(root.rglob("*.py")):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def key(kind: str, *parts: bytes | str) -> str:
    h = hashlib.sha256(code_fingerprint().encode())
    h.update(kind.encode())
    for part in parts:
        b = part.encode("utf-8") if isinstance(part, str) else part
        h.update(len(b).to_bytes(8, "little"))
        h.update(b)
    return h.hexdigest()


class _Capture(logging.Handler):
    """Collects every record an ``rsmm`` logger emits while a cook runs."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[list] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append([record.name, record.levelno, record.getMessage()])


def cached(kind: str, parts: tuple[bytes | str, ...], build: Callable[[], bytes]) -> bytes:
    """``build()``'s result, served from the cache when ``kind`` + ``parts``
    (the cook's whole input) were cooked before by the same code.

    A miss runs ``build()`` and stores its bytes with the log records it
    produced; a hit replays those records and returns the stored bytes. Any
    cache I/O failure falls back to cooking: the cache can only save time,
    never change a result.
    """
    if not enabled():
        return build()
    k = key(kind, *parts)
    d = cache_dir()
    blob, meta = d / f"{kind}-{k}.bin", d / f"{kind}-{k}.json"
    try:
        data = blob.read_bytes()
        records = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if data is not None:
        for name, level, msg in records:
            logging.getLogger(name).log(level, msg)
        try:
            os.utime(blob)          # recently used: kept by the trim below
        except OSError:
            pass
        return data

    cap = _Capture()
    root = logging.getLogger("rsmm")
    root.addHandler(cap)
    try:
        data = build()
    finally:
        root.removeHandler(cap)
    try:
        d.mkdir(parents=True, exist_ok=True)
        tag = f".{os.getpid()}.tmp"
        tmp_b, tmp_m = blob.with_name(blob.name + tag), meta.with_name(meta.name + tag)
        tmp_b.write_bytes(data)
        tmp_m.write_text(json.dumps(cap.records), encoding="utf-8")
        os.replace(tmp_m, meta)     # meta first: a blob without meta is a miss
        os.replace(tmp_b, blob)
        _trim(d)
    except OSError:
        pass
    return data


def _trim(d: Path) -> None:
    entries = []
    total = 0
    for p in d.glob("*.bin"):
        try:
            st = p.stat()
        except OSError:
            continue
        entries.append((st.st_mtime, st.st_size, p))
        total += st.st_size
    if total <= _MAX_BYTES:
        return
    for _mtime, size, p in sorted(entries):
        for f in (p, p.with_suffix(".json")):
            try:
                f.unlink()
            except OSError:
                pass
        total -= size
        if total <= _MAX_BYTES:
            return
