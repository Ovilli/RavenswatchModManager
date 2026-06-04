"""Shared file hashing — one chunked SHA-256 impl for the whole codebase.

Previously copy-pasted (with inconsistent chunk sizes) into apply_mods,
cmd_pack, repo, versioning, json_bridge, and doctor. Import from here instead.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK = 1 << 16  # 64 KiB — streaming read keeps memory flat on large assets.


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file, read in constant memory."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()
