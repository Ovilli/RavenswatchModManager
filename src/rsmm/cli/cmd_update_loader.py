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


def _refresh_pattern_db(game_dir: Path) -> None:
    """A new SDK may call symbols the planted pattern DB predates, and nothing
    else refetches a DB that exists for the same game build — so v50's
    R.modifier.max_selected reported "symbols unavailable" until a manual
    `rsmm update-data`. Advisory: stderr only, so `--json` stays parseable."""
    from rsmm.engine import data_update
    try:
        st = data_update.check(game_dir)
        if st["status"] != "up_to_date":
            data_update.apply_update(game_dir, st)
            print("  refreshed the pattern DB", file=sys.stderr)
    except (data_update.DataUpdateError, OSError) as e:
        print(f"update-loader: pattern DB not refreshed ({e}); "
              f"run `rsmm update-data`", file=sys.stderr)


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
            if state.get("not_planted"):
                # Vanilla on purpose (restore removed the loader): cache the
                # update for the next install-loader / modded launch instead.
                from rsmm.engine.loader_update import cache_update

                state = cache_update(game_dir, state)
            else:
                state = apply_update(game_dir, state)
            if state["status"] == "updated":
                _refresh_pattern_db(game_dir)
        elif not args.check:
            from rsmm.engine.loader_update import repair_plant

            repair = repair_plant(game_dir, state)
            if repair is not None:
                state["repaired"] = repair["repaired"]
                state["repair_error"] = repair["error"]
                if repair["repaired"]:
                    state["plant_stale"] = False
                    print(f"reinstalled loader v{repair['version']}: the "
                          f"winhttp.dll in the game dir was not a published build",
                          file=sys.stderr)
                else:
                    print(f"could not reinstall the loader: {repair['error']}",
                          file=sys.stderr)

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
        # Before everything, including "up to date": that line is about version numbers, and a
        # game dir with no winhttp.dll at all is running no loader whatever they say. Seen on a
        # tester's Windows install, where it read "up to date (v26)" over an empty folder.
        if state.get("not_planted"):
            print(f"note: there is NO loader in {game_dir} (no winhttp.dll), so the game is "
                  f"running without it, whatever the version below says. Run "
                  f"`rsmm install-loader \"{game_dir}\"` to put it there.", file=sys.stderr)
        if state.get("plant_stale"):
            planted = state.get("planted_version")
            if planted is None or planted >= state.get("bundled_version", 0):
                # No version to blame: either no manifest (`install-loader`
                # wrote none), or one at this version whose winhttp.dll entry
                # the DLL on disk does not match. Only the bytes are wrong.
                print("note: the winhttp.dll in the game dir is not a published "
                      "loader build (it matches neither this build's DLL nor the "
                      "planted manifest), and the game loads it. Run `rsmm "
                      "install-loader` to replace it; if it comes back, another "
                      "program is replacing winhttp.dll.", file=sys.stderr)
            else:
                print(f"note: the game dir holds loader v{planted}, but this "
                      f"build bundles v{state['bundled_version']} — the game "
                      f"loads the planted copy. Run `rsmm install-loader` to "
                      f"update it.", file=sys.stderr)
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
        elif status == "cached":
            print(f"loader v{state['cached_version']} downloaded; it is installed with "
                  f"your next modded launch (or `rsmm install-loader`). The game dir "
                  f"has no loader, so plain Steam launches stay vanilla.")
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
