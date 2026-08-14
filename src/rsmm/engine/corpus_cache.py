"""Disk cache for whole-corpus sweeps of the uncooked mirror.

Several `poi` guards answer questions that can only be settled by reading every
cooked file in `data/uncooked/` — "which tiles place this prop", "what else
uses this mesh", "can this entity stand at a transform on its own". Each is a
pure function of the mirror, and each costs tens of seconds: profiling a real
`apply` put `_placeable_entities` at 25.9s and the exclusivity sweep at 19.8s
out of 57s total, because between them they parse thousands of files and run
the lstr scanner over every byte.

`functools.lru_cache` already stops a sweep repeating *within* one process, but
the dev loop is `restore` -> `apply` -> `install-loader`, over and over, and
each `apply` is a fresh process that pays the whole cost again.

Validity is a fingerprint of the mirror rather than a timestamp: file count,
total size and newest mtime, which a stat walk answers in ~0.3s for 49k files.
Any edit, addition or removal moves at least one of the three, and a stale
cache is therefore rebuilt rather than trusted. Cheap enough to check every
time; the failure direction that matters (silently using a stale index and
mis-answering an exclusivity guard) cannot happen without the mirror being
byte-identical.

Nothing here is required for correctness: every entry point degrades to
rebuilding when the cache is missing, unreadable, stale or written by a
different schema.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .paths import DATA_DIR

#: Bumped when a cached value's SHAPE changes, so an old file is ignored
#: rather than deserialized into the wrong structure.
_SCHEMA = 1

_CACHE_DIR = DATA_DIR / ".corpus_cache"


def _fingerprint(root: Path) -> str:
    """Cheap identity of a directory tree: count, total size, newest mtime."""
    n = size = 0
    newest = 0
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            try:
                st = os.stat(os.path.join(dirpath, f))
            except OSError:
                continue          # vanished mid-walk: treated as a change
            n += 1
            size += st.st_size
            if st.st_mtime_ns > newest:
                newest = st.st_mtime_ns
    return f"{_SCHEMA}:{n}:{size}:{newest}"


def load_or_build(name: str, root: Path, build: Callable[[], Any]) -> Any:
    """Return the cached sweep `name`, rebuilding it if the corpus moved.

    `build` must return something JSON-serialisable; callers convert back to
    whatever runtime shape they want (sets, frozensets) themselves, so this
    module does not have to know about any of them.
    """
    if not root.is_dir():
        return build()
    key = _fingerprint(root)
    path = _CACHE_DIR / f"{name}.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("key") == key:
            return doc["value"]
    except (OSError, ValueError, KeyError):
        pass                      # missing / corrupt / older schema — rebuild

    value = build()
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"key": key, "value": value}),
                       encoding="utf-8")
        os.replace(tmp, path)
    except (OSError, TypeError):
        # A cache that cannot be written is a slow apply, not a broken one.
        pass
    return value
