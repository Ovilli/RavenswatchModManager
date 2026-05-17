"""
rsmm build — full pipeline.

Runs every step needed to go from a fresh checkout to a state where
mods can be installed:

    1. Build the asset map (if missing).
    2. Build the loader DLL (if missing or out of date).
    3. Compose [[patch]] blocks across mods into mods/_merged/.
    4. Run the applier (unless --skip-apply).

Use `rsmm build && rsmm run` to launch the game immediately after.
"""

from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

from rsmm.engine.paths import (
    REPO_ROOT, ASSET_MAP_JSON, DIST_DIR,
    DEFAULT_GAME_DIR as DEFAULT_GAME,
)
from rsmm.cli.merge import build_merged_mod


def _build_loader() -> int:
    build_sh = REPO_ROOT / "src" / "loader" / "build.sh"
    if not build_sh.exists():
        print(f"loader build script not found: {build_sh}", file=sys.stderr)
        return 1
    print(f"==> building loader DLL ({build_sh})")
    return subprocess.call([str(build_sh)])


def _rebuild_map() -> int:
    print("==> rebuilding asset map")
    return subprocess.call([sys.executable, str(REPO_ROOT / "rsmm"),
                            "rebuild-asset-map"])


def _apply(game_dir: Path) -> int:
    return subprocess.call([sys.executable, str(REPO_ROOT / "rsmm"), "apply",
                            "--game-dir", str(game_dir)])


def main() -> int:
    ap = argparse.ArgumentParser(description="Build everything, then apply")
    ap.add_argument("--game-dir", type=Path, default=DEFAULT_GAME)
    ap.add_argument("--skip-loader", action="store_true",
                    help="don't try to rebuild dist/winhttp.dll")
    ap.add_argument("--skip-apply", action="store_true",
                    help="stop before running ./rsmm apply")
    args = ap.parse_args()

    if not ASSET_MAP_JSON.exists():
        rc = _rebuild_map()
        if rc:
            return rc

    if not args.skip_loader:
        dll = DIST_DIR / "winhttp.dll"
        build_sh = REPO_ROOT / "src" / "loader" / "build.sh"
        need_build = (not dll.exists()) or (
            build_sh.exists() and
            dll.exists() and
            dll.stat().st_mtime < build_sh.stat().st_mtime
        )
        if need_build:
            rc = _build_loader()
            if rc:
                print("loader build failed", file=sys.stderr)
                return rc
        else:
            print("==> loader DLL up to date (skipping rebuild)")

    print("==> composing [[patch]] blocks into mods/_merged/")
    out, conflicts = build_merged_mod(args.game_dir)
    if out is None:
        print("    (no [[patch]] blocks to merge)")
    else:
        print(f"    wrote {out}")
        for kind, key, m in conflicts:
            print(f"    [conflict] [{kind}] {key}  {m}")

    if args.skip_apply:
        print("==> skipping apply (--skip-apply)")
        return 0
    print("==> applying mods to game install")
    return _apply(args.game_dir)


if __name__ == "__main__":
    sys.exit(main())
