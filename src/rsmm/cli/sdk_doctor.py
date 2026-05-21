#!/usr/bin/env python3
"""`rsmm sdk-doctor` — SDK v3 self-check.

Reports:
  * SDK API version
  * loaded plugins (entry-points)
  * health quarantine state
  * game-build pin status
  * per-mod config_schema validity
  * per-mod i18n coverage warnings
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

from rsmm.cli.apply_mods import find_game_dir
from rsmm.engine.paths import COOKING_SUBDIR, MODS_DIR
from rsmm.sdk.api import API_VERSION, registry
from rsmm.sdk.config import ConfigError, ConfigSchema
from rsmm.sdk.health import Health
from rsmm.sdk.i18n import I18nBundle
from rsmm.sdk.plugins import discover_plugins
from rsmm.sdk.versioning import check_compat


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm sdk-doctor")
    ap.add_argument("--game-dir", type=Path, default=None)
    ap.add_argument("--list-api", action="store_true",
                    help="dump every @sdk_export name and exit")
    args = ap.parse_args(argv)

    if args.list_api:
        for name in sorted(registry()):
            print(name)
        return 0

    print(f"SDK API: {API_VERSION}")

    api = SimpleNamespace(version=API_VERSION)
    loaded, skipped = discover_plugins(api)
    print(f"\nPlugins: {len(loaded)} loaded, {len(skipped)} skipped")
    for p in loaded:
        print(f"  + {p.name} ({p.target})")
    for p in skipped:
        print(f"  ! {p.name} ({p.target})  ERROR: {p.error}")

    game = args.game_dir or find_game_dir()
    if game:
        cooking = game / COOKING_SUBDIR
        if cooking.is_dir():
            print("\nHealth:")
            h = Health(cooking)
            st = h.load()
            print(f"  threshold = {st.threshold}")
            if not st.mods:
                print("  no crash records")
            for mid, body in sorted(st.mods.items()):
                tag = "DISABLED" if body.disabled_by_health else "ok"
                print(f"  [{tag:>8}] {mid:24}  crashes={body.crashes}")

            print("\nGame build:")
            exe = game / "Ravenswatch.exe"
            ok, msg = check_compat(exe, cooking)
            print(f"  [{'ok' if ok else '!!'}] {msg}")
        else:
            print(f"\n_Cooking not found at {cooking}; skipping live checks")
    else:
        print("\nGame install not autodetected; skipping live checks")

    print("\nPer-mod schema + i18n:")
    if not MODS_DIR.is_dir():
        print("  no mods/ dir")
        return 0
    for entry in sorted(MODS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        problems: list[str] = []
        schema = entry / "config_schema.toml"
        if schema.exists():
            try:
                ConfigSchema.load(schema)
            except ConfigError as e:
                problems.append(f"config_schema: {e}")
        try:
            b = I18nBundle.load(entry.name, entry)
            problems.extend(b.coverage_warnings())
        except Exception as e:
            problems.append(f"i18n: {e}")
        if problems:
            print(f"  ! {entry.name}")
            for p in problems[:5]:
                print(f"      {p}")
        else:
            print(f"  + {entry.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
