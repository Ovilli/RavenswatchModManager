"""`rsmm changelog` — read the release-notes channel.

The notes live on a rolling GitHub release rather than inside the app
bundle, so a note can be published without shipping a build. See
``rsmm.engine.changelog_feed`` for the trust model (untrusted display text,
strictly bounded, never signed because it is never code).

Usage:
  rsmm changelog             # print the recent entries
  rsmm changelog --refresh   # ignore the cache TTL and re-fetch now
  rsmm changelog --json      # machine-readable output (desktop bridge)
"""

from __future__ import annotations

import argparse
import json
import sys

from rsmm.engine.changelog_feed import check


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="rsmm changelog",
        description="show release notes from the rolling changelog channel",
    )
    ap.add_argument("--refresh", action="store_true",
                    help="re-fetch even if the cached copy is still fresh")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="print machine-readable JSON")
    ap.add_argument("-n", "--limit", type=int, default=5,
                    help="how many releases to print (default: 5)")
    args = ap.parse_args()

    state = check(force=args.refresh)

    if args.as_json:
        print(json.dumps(state))
        return 0

    if state["status"] == "unavailable":
        print(f"changelog unavailable: {state['error']}", file=sys.stderr)
        return 1

    from rsmm.cli._term import Style

    st = Style()
    if state["status"] == "cached" and state["error"]:
        print(st.dim(f"(showing cached notes — {state['error']})"))

    for entry in state["entries"][: max(1, args.limit)]:
        # A loader-channel note has no app version to show; say which loader
        # build it describes instead, so "where did this come from" is answered
        # by the line itself.
        lv = entry.get("loader_version")
        if lv and not entry.get("version"):
            head = f"loader v{lv}"
        elif lv:
            head = f"v{entry['version']} (loader v{lv})"
        else:
            head = f"v{entry['version']}"
        if entry.get("date"):
            head = f"{head}  {entry['date']}"
        print(st.bold(head))
        if entry.get("summary"):
            print(f"  {entry['summary']}")
        for line in entry["highlights"]:
            print(f"  - {line}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
