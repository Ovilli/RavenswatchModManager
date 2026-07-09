"""`rsmm update-data` — pull the latest pattern DB without an app release.

After a game patch, the dev-side Ghidra corpus is re-analyzed and
``data/function_patterns.json`` regenerated and pushed. This command
downloads that regenerated DB and plants it where the loader reads it
(``<game>/rsmm/data/``), so users get fixed engine-function resolution
without waiting for the next rsmm release.

Usage:
  rsmm update-data            # check + install if the remote is different
  rsmm update-data --check    # report only, never write
  rsmm update-data --json     # machine-readable output (desktop bridge)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rsmm.engine.data_update import DataUpdateError, apply_update, check


def _emit_json(state: dict) -> None:
    state = {k: v for k, v in state.items() if not k.startswith("_")}
    print(json.dumps(state))


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="rsmm update-data",
        description="update the loader's function-pattern DB from the repo",
    )
    ap.add_argument("--check", action="store_true",
                    help="report status only, do not install")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="print machine-readable JSON")
    ap.add_argument("--game-dir", type=Path, default=None,
                    help="override the game directory")
    args = ap.parse_args()

    game_dir = args.game_dir
    if game_dir is None:
        from rsmm.engine.paths import default_game_dir
        game_dir = default_game_dir()
    if not game_dir.is_dir():
        msg = f"game directory not found: {game_dir}"
        if args.as_json:
            print(json.dumps({"status": "error", "error": msg}))
        else:
            print(msg, file=sys.stderr)
        return 1

    try:
        state = check(game_dir)

        if state["status"] == "up_to_date" or args.check:
            state.pop("_raw", None)
        else:
            state = apply_update(game_dir, state)

        if args.as_json:
            _emit_json(state)
            return 0

        meta = state.get("remote_meta") or {}
        if meta.get("generated"):
            print(f"remote pattern DB: generated {meta['generated']}, "
                  f"{meta.get('pattern_count', '?')} patterns")
        if state["exe_match"] is True:
            print("remote DB matches your exact game build")
        elif state["exe_match"] is False:
            print("note: remote DB was generated against a different game build "
                  "(pattern scan usually still resolves; if the loader logs "
                  "unresolved symbols, wait for the next data push)")

        if state["status"] == "up_to_date":
            print("pattern DB is up to date")
        elif state["status"] == "updated":
            print(f"updated: {state['planted_path']}")
        elif state["status"] == "update_available":
            print("update available — run `rsmm update-data` (without --check) "
                  "to install")
        elif state["status"] == "not_planted":  # only reachable with --check
            print("no pattern DB planted in the game dir yet — "
                  "`rsmm update-data` will plant one (loader install: "
                  "`rsmm install-loader`)")
        return 0
    except DataUpdateError as e:
        if args.as_json:
            print(json.dumps({"status": "error", "error": str(e)}))
        else:
            print(f"update-data: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
