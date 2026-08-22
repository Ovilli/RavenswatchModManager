"""Release-notes channel — changelog entries that do not ride an app release.

The desktop app ships a compiled-in copy of its release notes
(``apps/desktop/src/lib/changelog.ts``), which means a note can only ever
reach a user by shipping them a whole new build. That is backwards for the
two cases that matter most:

  * The loader DLL and Lua SDK already update out of band (see
    ``rsmm.engine.loader_update``), so a scripting fix reaches users with
    no app release — and therefore with no way to tell them what changed.
  * A note that turns out to be wrong, or an advisory that has to go out
    now, cannot wait for the next release train.

So the notes ship the same way the pattern DB and the loader do: as an
asset on a rolling GitHub release, replaced in place whenever there is
something to say. ``scripts/publish_changelog.sh`` pushes it.

Unlike the loader channel this payload is **not** signed, and deliberately
so: it is display text, never code, and it is never written anywhere the
game or the loader reads. The trust model is therefore "untrusted text,
strictly bounded" rather than "verified payload":

  * every field is type-checked, length-capped and control-character
    stripped before it leaves this module (``_clean``/``_entry``),
  * the entry and highlight counts are capped, so a hostile or corrupt
    payload cannot produce an unbounded render,
  * nothing here writes outside the per-user cache directory.

The cache is what makes the feature work offline and keeps GitHub from
being hit on every launch: a successful fetch is stored with its
timestamp, and a fetch is only attempted again once ``CACHE_TTL`` has
passed (``force=True`` overrides). A failed fetch always falls back to
whatever is cached, however old — stale notes beat no notes.
"""

from __future__ import annotations

import json
import os
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from rsmm.engine.paths import DATA_DIR, user_data_dir

ASSET_NAME = "changelog.json"

# Rolling release asset: a re-publish reaches every installed client on its
# next check, with no app release in between. Overridable for tests and for
# a future move to a first-party host.
DEFAULT_REMOTE_BASE = (
    "https://github.com/Ovilli/RavenswatchModManager/releases/download/changelog"
)

_TIMEOUT = 15.0

#: How long a successful fetch is trusted before another is attempted.
CACHE_TTL = 6 * 60 * 60

# Bounds on the untrusted payload. Generous enough that no honest release
# note hits them, small enough that a corrupt or hostile asset cannot make
# the client render an unbounded document.
MAX_ENTRIES = 50
MAX_HIGHLIGHTS = 12
MAX_VERSION = 32
MAX_DATE = 32
MAX_TEXT = 500


class ChangelogError(Exception):
    pass


def remote_base() -> str:
    return os.environ.get("RSMM_CHANGELOG_BASE", "").strip() or DEFAULT_REMOTE_BASE


def cache_path() -> Path:
    return user_data_dir() / "cache" / ASSET_NAME


def bundled_path() -> Path:
    """The copy shipped inside this build.

    Same file the publish script uploads, so the offline answer is whatever
    was true when this build was cut rather than nothing at all. Frozen
    builds reach it through ``_MEIPASS`` like any other bundled data.
    """
    return DATA_DIR / ASSET_NAME


def _fetch(url: str) -> bytes:
    if not url.startswith(("https://", "file://")):  # file:// = tests only
        raise ChangelogError(f"refusing to fetch non-HTTPS URL: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "rsmm-changelog"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            # Cap the read: a redirect to something enormous must not be
            # pulled into memory just to be rejected afterwards.
            return r.read(1 << 20)
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise ChangelogError(f"fetch failed: {url}: {e}") from e


def _clean(value: Any, limit: int) -> str:
    """Coerce an untrusted field to a bounded single-line string.

    Control characters are dropped rather than escaped: the consumers are a
    terminal renderer and a React tree, and a stray CSI sequence in the
    former can repaint the screen. Unicode category ``C`` covers the ANSI
    introducer, the bidi overrides that let text render in an order other
    than the one it is written in, and the zero-width joiners that hide
    length from a reader while still counting against the cap.
    """
    if not isinstance(value, str):
        return ""
    text = "".join(ch for ch in value if unicodedata.category(ch)[0] != "C")
    text = " ".join(text.split())
    return text[:limit].strip()


def _entry(raw: Any) -> dict | None:
    """Validate one release entry. Returns None if it is unusable."""
    if not isinstance(raw, dict):
        return None
    version = _clean(raw.get("version"), MAX_VERSION)
    if not version:
        return None
    highlights = raw.get("highlights")
    if not isinstance(highlights, list):
        return None
    lines = [_clean(h, MAX_TEXT) for h in highlights[:MAX_HIGHLIGHTS]]
    lines = [ln for ln in lines if ln]
    if not lines:
        # An entry with a version and nothing to say is noise, not news.
        return None
    entry = {
        "version": version,
        "date": _clean(raw.get("date"), MAX_DATE),
        "highlights": lines,
    }
    summary = _clean(raw.get("summary"), MAX_TEXT)
    if summary:
        entry["summary"] = summary
    return entry


def parse(data: bytes) -> dict:
    """Parse + sanitize a raw feed payload. Raises on anything unusable."""
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ChangelogError(f"feed is not valid JSON: {e}") from e
    if not isinstance(doc, dict):
        raise ChangelogError("feed root must be a JSON object")
    raw_entries = doc.get("entries")
    if not isinstance(raw_entries, list):
        raise ChangelogError("feed has no 'entries' list")
    entries = [e for e in (_entry(r) for r in raw_entries[:MAX_ENTRIES]) if e]
    if not entries:
        raise ChangelogError("feed contains no usable entries")
    return {"generated": _clean(doc.get("generated"), MAX_DATE), "entries": entries}


def _read_cache() -> dict | None:
    try:
        cached = json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(cached, dict) or not isinstance(cached.get("entries"), list):
        return None
    return cached


def _read_bundled() -> dict | None:
    """Parse the build's own copy. Sanitized like any other payload — the
    bundled file is trusted, but running it through the same validator is
    what keeps a hand-edit from producing a shape the clients never see."""
    try:
        return parse(bundled_path().read_bytes())
    except (OSError, ChangelogError):
        return None


def _write_cache(feed: dict) -> None:
    path = cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # PID-qualified staging: two rsmm processes checking at once must not
        # each write the same temp name and have one replace the other's file
        # mid-write.
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(feed), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        # A cache that cannot be written costs a fetch next launch. It is
        # never a reason to fail the command.
        pass


def check(force: bool = False) -> dict:
    """Return the newest release notes available, fetching if warranted.

    Never raises: a client asking "what changed" while offline gets the
    cached answer, and one with no cache gets an empty list plus the
    reason. The status distinguishes them so a caller can tell a fresh
    fetch from a stale cache from this build's own bundled copy.
    """
    cached = _read_cache()
    age = time.time() - float(cached.get("fetched_at", 0)) if cached else None
    if cached and not force and age is not None and age < CACHE_TTL:
        return {
            "status": "cached",
            "generated": cached.get("generated", ""),
            "entries": cached.get("entries", []),
            "error": None,
        }

    url = f"{remote_base()}/{ASSET_NAME}"
    try:
        feed = parse(_fetch(url))
    except ChangelogError as e:
        if cached:
            return {
                "status": "cached",
                "generated": cached.get("generated", ""),
                "entries": cached.get("entries", []),
                # Reported, not raised: the caller has usable content and
                # only needs to know it may be stale.
                "error": str(e),
            }
        bundled = _read_bundled()
        if bundled:
            return {
                "status": "bundled",
                "generated": bundled.get("generated", ""),
                "entries": bundled.get("entries", []),
                "error": str(e),
            }
        return {"status": "unavailable", "generated": "", "entries": [], "error": str(e)}

    _write_cache({**feed, "fetched_at": time.time()})
    return {"status": "fetched", **feed, "error": None}
