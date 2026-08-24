#!/usr/bin/env python3
"""Record a loader-channel publish in the release-notes feed.

The loader DLL and Lua SDK ship out of band (`scripts/publish_loader.sh`), so a
scripting fix reaches every user with no app release in between — and until now
it reached them silently. Release notes were keyed by APP version, and the
desktop dialog clamps those to the version the user is running, so a note about
a loader build either had to be filed under a release it was not part of, or go
unread.

This writes a CHANNEL note instead: an entry carrying `loader_version` (and no
app `version`), which clients show based on the loader the user has planted.
`data/changelog.json` stays the single source — the same file the sidecar
bundles and `publish_changelog.sh` uploads — so the note cannot drift from what
the app ships with.

Idempotent: re-running for a loader version that already has an entry replaces
it rather than stacking duplicates, which is what a re-publish of the same
version should mean.

Usage:
    python scripts/add_loader_changelog.py --loader-version 8 \
        --summary "..." --highlight "..." [--highlight "..."] [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date as _date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FEED = REPO / "data" / "changelog.json"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--loader-version", type=int, required=True)
    ap.add_argument("--summary", required=True, help="one sentence, shown as the subtitle")
    ap.add_argument("--highlight", action="append", default=[],
                    help="a bullet; repeat for more (at least one required)")
    ap.add_argument("--date", default=_date.today().isoformat())
    ap.add_argument("--feed", default=str(FEED))
    a = ap.parse_args(argv)

    if not a.highlight:
        print("at least one --highlight is required (an entry with nothing to "
              "say is dropped by the client parser)", file=sys.stderr)
        return 2

    path = Path(a.feed)
    doc = json.loads(path.read_text(encoding="utf-8"))
    entries = doc.get("entries")
    if not isinstance(entries, list):
        print(f"{path} has no 'entries' list", file=sys.stderr)
        return 1

    entry = {
        # Explicitly empty rather than absent. The client parser normalises a
        # missing version to "" anyway, but the desktop imports this file
        # DIRECTLY as typed data — an absent key makes the entry a different
        # shape from every other one and fails the build.
        "version": "",
        "loader_version": a.loader_version,
        "date": a.date,
        "summary": a.summary,
        "highlights": list(a.highlight),
    }
    # Replace an existing note for this loader version; otherwise it goes on
    # top, because the feed is newest-first and a channel publish is the most
    # recent thing that happened.
    kept = [e for e in entries
            if not (isinstance(e, dict) and e.get("loader_version") == a.loader_version)]
    replaced = len(kept) != len(entries)
    doc["entries"] = [entry, *kept]
    doc["generated"] = a.date

    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Validate through the client parser, so a note that would be dropped on a
    # user's machine fails here instead of shipping.
    sys.path.insert(0, str(REPO / "src"))
    from rsmm.engine.changelog_feed import ChangelogError, parse

    try:
        feed = parse(path.read_bytes())
    except ChangelogError as e:
        print(f"the feed no longer parses: {e}", file=sys.stderr)
        return 1
    if not any(e.get("loader_version") == a.loader_version for e in feed["entries"]):
        print("the new entry was dropped by the parser (too long? empty?)", file=sys.stderr)
        return 1

    print(f"{'replaced' if replaced else 'added'} loader v{a.loader_version} note in {path}")
    print(f"  {a.summary}")
    for h in a.highlight:
        print(f"  - {h[:96]}{'…' if len(h) > 96 else ''}")
    print("\nNow publish it:  scripts/publish_changelog.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
