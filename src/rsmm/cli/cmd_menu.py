"""`rsmm menu` — generate the in-game mod-list page (native book UI).

    rsmm menu build [--game-dir DIR] [--mods-dir DIR]   regenerate RSMMMenu
    rsmm menu remove [--mods-dir DIR]                   delete the menu mod

`build` reads the installed mods, clones the Tutorial tab's first quick-guide
page FROM THE USER'S INSTALL, swaps its label keys to RSMM ones, appends those
keys to the tutorial text bank, and writes it all as the `RSMMMenu` mod.
Run `rsmm apply` afterwards to install; the Tuto tab's first page then shows
the mod list. Re-run `build` whenever mods change.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from ..engine import mod_menu
from ..engine import paths as P
from .apply_mods import Mod, load_asset_map


def _load_mods(mods_dir: Path) -> list[dict]:
    out: list[dict] = []
    if not mods_dir.is_dir():
        return out
    for d in sorted(mods_dir.iterdir()):
        if not d.is_dir() or not (d / "manifest.toml").is_file():
            continue
        try:
            m = Mod(d)
        except (OSError, ValueError, KeyError):
            continue
        if m.id == mod_menu.MENU_MOD_ID:
            continue
        out.append({"id": m.id, "name": m.name, "version": m.version,
                    "enabled": m.enabled})
    return out


def cmd_build(args: argparse.Namespace) -> int:
    game_dir = Path(args.game_dir) if args.game_dir else P.default_game_dir()
    cooking = game_dir / "DarkTalesResources" / "_Cooking"
    if not cooking.is_dir():
        print(f"error: cooking dir not found: {cooking}", file=sys.stderr)
        return 2
    mods_dir = Path(args.mods_dir) if args.mods_dir else P.mods_dir()
    mods = _load_mods(mods_dir)

    try:
        assets = mod_menu.build_menu_assets(cooking, load_asset_map(), mods)
    except mod_menu.ModMenuError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    root = mods_dir / mod_menu.MENU_MOD_ID
    if root.exists():
        shutil.rmtree(root)
    (root / "assets").mkdir(parents=True)
    (root / "manifest.toml").write_text(mod_menu.manifest_toml(len(mods)),
                                        encoding="utf-8")
    for dec, blob in assets.items():
        dest = root / "assets" / Path(*dec.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)

    print(f"wrote {root} ({len(assets)} asset file(s), {len(mods)} mod(s) "
          f"listed).")
    print("Run 'rsmm apply' to install — the mod list appears on the "
          "Tutorial tab's first page.")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    mods_dir = Path(args.mods_dir) if args.mods_dir else P.mods_dir()
    root = mods_dir / mod_menu.MENU_MOD_ID
    if not root.is_dir():
        print("menu mod not present.")
        return 0
    shutil.rmtree(root)
    print(f"removed {root}. Run 'rsmm apply' to restore the tutorial page.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm menu",
                                 description="In-game mod-list page (native book UI)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="(re)generate the RSMMMenu mod")
    b.add_argument("--game-dir", help="Ravenswatch install dir (auto-detected)")
    b.add_argument("--mods-dir", help="mods directory (default: repo mods/)")
    b.set_defaults(fn=cmd_build)

    r = sub.add_parser("remove", help="delete the RSMMMenu mod")
    r.add_argument("--mods-dir", help="mods directory (default: repo mods/)")
    r.set_defaults(fn=cmd_remove)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
