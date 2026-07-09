"""Data-only update channel for the pattern database.

The loader resolves engine functions by scanning byte patterns from
``function_patterns.json``. The scan itself self-heals across small game
patches, but the pattern *data* is regenerated dev-side from a Ghidra
corpus after each game update — users can't rebuild it. This module lets
an installed rsmm (frozen sidecar included) pull the freshly-regenerated
patterns straight from the repo without waiting for a full app release.

Flow:
  1. Fetch ``function_patterns.meta.json`` from the remote (a rolling
     GitHub release asset under the ``pattern-db`` tag, published by
     ``scripts/publish_pattern_db.sh`` after each regen — the DB itself
     is gitignored, so it cannot ride the repo) — tiny, records which
     game build the patterns were generated against plus the sha256 of
     the patterns file.
  2. Compare against what is planted in ``<game>/rsmm/data/`` (the copy
     the loader actually reads; see fn_resolver.cpp locate_patterns_file).
  3. If different, download the patterns file, verify its sha256 against
     the meta, and atomically replace the planted copy + meta.

The bundled copy under ``data/`` is never touched: in a frozen sidecar it
lives in read-only _MEIPASS, and in source mode it is git-tracked.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from rsmm.engine.paths import DATA_DIR

PATTERNS_NAME = "function_patterns.json"
META_NAME = "function_patterns.meta.json"

# Rolling release asset: updates land the moment the dev re-publishes the
# tag's assets (`scripts/publish_pattern_db.sh`), no app release required.
# Overridable for tests and for a future move to a first-party host.
DEFAULT_REMOTE_BASE = (
    "https://github.com/Ovilli/RavenswatchModManager/releases/download/pattern-db"
)

_TIMEOUT = 30.0


class DataUpdateError(Exception):
    pass


def remote_base() -> str:
    return os.environ.get("RSMM_DATA_UPDATE_BASE", "").strip() or DEFAULT_REMOTE_BASE


def planted_dir(game_dir: Path) -> Path:
    """Where the loader looks for the pattern DB (fn_resolver.cpp)."""
    return game_dir / "rsmm" / "data"


def _fetch(url: str) -> bytes:
    if not url.startswith(("https://", "file://")):  # file:// = tests only
        raise DataUpdateError(f"refusing to fetch non-HTTPS URL: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "rsmm-update-data"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return r.read()
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise DataUpdateError(f"fetch failed: {url}: {e}") from e


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_meta(path: Path) -> dict | None:
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


def _validate_patterns(raw: bytes) -> list:
    """Structural sanity check: what fn_resolver.cpp expects to parse."""
    try:
        entries = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise DataUpdateError(f"remote patterns file is not valid JSON: {e}") from e
    if not isinstance(entries, list) or not entries:
        raise DataUpdateError("remote patterns file is empty or not a JSON list")
    for e in entries[:16]:
        if not isinstance(e, dict) or "name" not in e or "pattern" not in e:
            raise DataUpdateError("remote patterns entries missing name/pattern")
    return entries


def local_exe_sha256(game_dir: Path) -> str | None:
    for cand in (
        game_dir / "Ravenswatch.exe",
        game_dir / "Ravenswatch-Win64-Shipping.exe",
        game_dir / "Ravenswatch" / "Binaries" / "Win64" / "Ravenswatch-Win64-Shipping.exe",
    ):
        if cand.exists():
            h = hashlib.sha256()
            with open(cand, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            return h.hexdigest()
    return None


def check(game_dir: Path) -> dict:
    """Compare planted patterns against the remote. Network: meta fetch only.

    Returns a status dict:
      status           up_to_date | update_available | not_planted
      remote_meta      parsed remote meta (or None if the remote has no
                       meta yet — pre-meta repo state; falls back to
                       hashing the remote patterns file itself)
      planted_sha256   sha256 of the planted patterns file, if any
      exe_match        True/False/None — remote patterns generated against
                       the user's exact game build (None = undeterminable)
    """
    base = remote_base()
    planted = planted_dir(game_dir) / PATTERNS_NAME

    remote_meta = None
    raw = None
    try:
        remote_meta = json.loads(_fetch(f"{base}/{META_NAME}").decode("utf-8"))
        remote_sha = str(remote_meta.get("patterns_sha256", ""))
        if not remote_sha:
            raise DataUpdateError("remote meta missing patterns_sha256")
    except DataUpdateError:
        # No meta upstream yet — hash the patterns file directly.
        raw = _fetch(f"{base}/{PATTERNS_NAME}")
        remote_sha = _sha256(raw)

    planted_sha = _sha256(planted.read_bytes()) if planted.exists() else None

    exe_match = None
    if remote_meta and remote_meta.get("game_exe_sha256"):
        exe_sha = local_exe_sha256(game_dir)
        if exe_sha:
            exe_match = exe_sha == remote_meta["game_exe_sha256"]

    if planted_sha is None:
        status = "not_planted"
    elif planted_sha == remote_sha:
        status = "up_to_date"
    else:
        status = "update_available"

    return {
        "status": status,
        "remote_base": base,
        "remote_sha256": remote_sha,
        "remote_meta": remote_meta,
        "planted_path": str(planted),
        "planted_sha256": planted_sha,
        "exe_match": exe_match,
        "_raw": raw,  # reused by apply_update to avoid a second fetch
    }


def apply_update(game_dir: Path, state: dict | None = None) -> dict:
    """Download + verify + atomically plant the remote patterns (and meta).

    Pass a ``check()`` result as *state* to skip re-fetching the meta.
    Returns the (possibly refreshed) state with status "updated".
    """
    if state is None:
        state = check(game_dir)

    raw = state.pop("_raw", None)
    if raw is None:
        raw = _fetch(f"{state['remote_base']}/{PATTERNS_NAME}")
    if _sha256(raw) != state["remote_sha256"]:
        raise DataUpdateError(
            "downloaded patterns hash mismatch (raw CDN cache skew? retry later)"
        )
    entries = _validate_patterns(raw)

    dst_dir = planted_dir(game_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)

    def _atomic_write(path: Path, data: bytes) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    _atomic_write(dst_dir / PATTERNS_NAME, raw)
    if state["remote_meta"] is not None:
        _atomic_write(
            dst_dir / META_NAME,
            (json.dumps(state["remote_meta"], indent=2) + "\n").encode("utf-8"),
        )

    state["status"] = "updated"
    state["pattern_count"] = len(entries)
    return state


def bundled_meta() -> dict | None:
    """Meta shipped alongside the bundled pattern DB (may be absent)."""
    return _read_meta(DATA_DIR / META_NAME)


def planted_meta(game_dir: Path) -> dict | None:
    return _read_meta(planted_dir(game_dir) / META_NAME)
