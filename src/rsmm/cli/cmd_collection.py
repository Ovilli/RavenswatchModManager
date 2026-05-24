"""rsmm collection <subcommand> — manage mod collections."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from rsmm.cli.json_bridge import cmd_install_mod


def _api_base() -> str:
    import os
    return os.environ.get("RSMM_INDEX_URL", "https://api.ravenswatch.ovilli.de")


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return dict(json.loads(resp.read().decode()))


def cmd_install(slug: str) -> int:
    """Install all mods from a collection."""
    base = _api_base()
    detail_url = f"{base}/api/collections/{slug}"
    print(f"Fetching collection: {slug}")
    try:
        detail = _http_get_json(detail_url)
    except urllib.error.HTTPError as e:
        print(f"Failed to fetch collection: HTTP {e.code}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"Failed to fetch collection: {e}", file=sys.stderr)
        return 1

    name = detail.get("name", slug)
    mods = detail.get("mods", [])
    if not mods:
        print(f'Collection "{name}" has no mods.')
        return 0

    print(f'Collection: {name} ({len(mods)} mods)')
    ok = 0
    failed: list[str] = []
    for idx, m in enumerate(mods, 1):
        mslug = m.get("slug") or m.get("id", "?")
        mname = m.get("name", mslug)
        print(f"[{idx}/{len(mods)}] Installing {mname} ({mslug})…")
        try:
            rc = cmd_install_mod(mslug)
            if rc == 0:
                ok += 1
            else:
                failed.append(mslug)
                print(f"  └─ install failed (exit {rc})", file=sys.stderr)
        except (urllib.error.URLError, OSError, ValueError) as e:
            failed.append(mslug)
            print(f"  └─ install error: {e}", file=sys.stderr)

    print(f"\nDone: {ok}/{len(mods)} installed.")
    if failed:
        print(f"Failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        print(__doc__, file=sys.stderr)
        print("Subcommands: install <slug>", file=sys.stderr)
        return 2
    sub = argv[0]
    rest = argv[1:]

    if sub == "install":
        if not rest:
            print("Usage: rsmm collection install <slug>", file=sys.stderr)
            return 2
        return cmd_install(rest[0])

    print(f"Unknown collection subcommand: {sub}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
