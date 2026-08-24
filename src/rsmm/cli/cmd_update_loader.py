"""`rsmm update-loader` — pull the loader DLL + Lua SDK without an app release.

The Lua SDK is disk-loaded from ``<game>/rsmm/lib/`` and the loader is a
plain ``winhttp.dll`` in the game directory, so neither needs to ride
inside the desktop bundle. This command fetches the signed bundle from
the rolling ``loader`` release and plants it. See
``rsmm.engine.loader_update`` for the format and the security model.

Usage:
  rsmm update-loader            # check + install if the remote is newer
  rsmm update-loader --check    # report only, never write
  rsmm update-loader --json     # machine-readable output (desktop bridge)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rsmm.engine.loader_update import LoaderUpdateError, apply_update, check


def _emit_json(state: dict) -> None:
    print(json.dumps({k: v for k, v in state.items() if not k.startswith("_")}))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="rsmm update-loader",
        description="update the loader DLL and Lua SDK from the rolling channel",
    )
    ap.add_argument("--check", action="store_true",
                    help="report status only, do not install")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="print machine-readable JSON")
    ap.add_argument("--game-dir", type=Path, default=None,
                    help="override the game directory")
    args = ap.parse_args(argv)

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
        if state["status"] == "update_available" and not args.check:
            state = apply_update(game_dir, state)

        if args.as_json:
            _emit_json(state)
            return 0 if state["status"] != "needs_app_update" else 1

        status = state["status"]
        # Say this BEFORE any status line. `installed_version` is the
        # update-eligibility figure (max of planted and bundled), so a game dir
        # running an older planted SDK still reports "up to date" — which is
        # exactly what sent a 2026-08-24 debugging session looking for the bug
        # in the mod instead of in the plant. The channel cannot fix this one:
        # what is behind is the game dir, not the download.
        if state.get("plant_stale"):
            print(f"note: the game dir holds loader v{state['planted_version']}, "
                  f"but this build bundles v{state['bundled_version']} — the game "
                  f"loads the planted copy. Run `rsmm install-loader` to update it.",
                  file=sys.stderr)
        if status == "needs_app_update":
            print(state["error"], file=sys.stderr)
            return 1
        if status == "ahead":
            print(f"loader v{state['installed_version']} installed; the channel is "
                  f"at v{state['remote_version']} — keeping the newer local build")
            return 0
        if status == "not_published":
            print(f"loader v{state['installed_version']} installed; "
                  f"the update channel has nothing published yet")
            return 0
        if status == "up_to_date":
            print(f"loader is up to date (v{state['installed_version']})")
            return 0

        if state.get("generated"):
            print(f"loader v{state.get('remote_version')} "
                  f"(rsmm {state.get('rsmm_version') or '?'}, "
                  f"built {state['generated']})")
        if state.get("notes"):
            print(f"  {state['notes']}")

        if status == "update_available":  # --check path
            print(f"update available: v{state['installed_version']} -> "
                  f"v{state['remote_version']} — run `rsmm update-loader` to install")
        elif status == "updated":
            for p in state.get("planted", []):
                print(f"  planted {p}")
            print(f"loader updated to v{state['installed_version']} — "
                  f"restart Ravenswatch to pick it up")
        return 0
    except LoaderUpdateError as e:
        if args.as_json:
            print(json.dumps({"status": "error", "error": str(e)}))
        else:
            print(f"update-loader: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
