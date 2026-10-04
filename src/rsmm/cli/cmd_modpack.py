"""rsmm modpack — the identity of this install's applied mod set.

What the desktop app reads before launching, to put in the login ticket the
multiplayer backend matches parties on. Not `rsmm pack`, which bundles one mod
for distribution.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rsmm.engine.modpack import read_modpack
from rsmm.engine.paths import default_game_dir


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="rsmm modpack",
        description="Print the fingerprint of the mods applied to an install.",
    )
    # Resolved at call time, not as an argparse default: `default_game_dir()`
    # reads RSMM_GAME_DIR when it is called, and a default evaluated at import
    # would freeze whatever the environment looked like then.
    ap.add_argument("--game-dir", type=Path, default=None,
                    help="install to inspect (default: the detected one)")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable output, for the desktop app")
    args = ap.parse_args(argv)

    game_dir = args.game_dir or default_game_dir()
    pack = read_modpack(game_dir)

    if args.json:
        json.dump({"id": pack.id, "label": pack.label, "status": pack.status}, sys.stdout)
        sys.stdout.write("\n")
        return 0

    if pack.status == "vanilla":
        print("mod pack: none — nothing applied, this install is vanilla")
        return 0

    if pack.status == "unknown":
        # Deliberately not reported as vanilla: mods may well be applied, and
        # saying otherwise would send the player into a party they desync in.
        print("mod pack: unknown — mods are applied but could not be fingerprinted")
        if pack.label:
            print(f"mods:     {pack.label}")
        print("          the apply journal is missing, unreadable, or predates 0.1.12;")
        print("          run `rsmm apply` to rewrite it")
        return 1

    print(f"mod pack: {pack.id}")
    print(f"mods:     {pack.label or '(none recorded)'}")
    print("          players matched online must show this same fingerprint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
