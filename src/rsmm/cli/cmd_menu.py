"""`rsmm menu` — generate and inspect the in-game mod-list page (native book UI).

    rsmm menu build [--game-dir DIR] [--mods-dir DIR]   regenerate RSMMMenu
    rsmm menu remove [--mods-dir DIR]                   delete the menu mod
    rsmm menu inspect LEFT [RIGHT] [--diff]             summarize or compare

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

from ..engine import entity_inspect as EI
from ..engine import mod_menu, mods_modal, mods_tab
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

    tab_note = ""
    if not args.no_tab:
        try:
            tab_assets = mods_tab.build_tab_assets(cooking, load_asset_map())
        except mods_tab.ModsTabError as e:
            print(f"warning: page buttons skipped: {e}", file=sys.stderr)
        else:
            overlap = set(assets) & set(tab_assets)
            # Both builders write distinct assets; same-key collision would
            # mean silent asset loss, so refuse loudly.
            if overlap:
                print(f"error: menu/button asset overlap: {sorted(overlap)}",
                      file=sys.stderr)
                return 2
            assets.update(tab_assets)
            tab_note = " + page buttons (experimental)"

    if args.bookmark:
        try:
            bm_assets = mods_tab.build_bookmark_assets(cooking, load_asset_map())
        except mods_tab.ModsTabError as e:
            print(f"warning: 6th bookmark skipped: {e}", file=sys.stderr)
        else:
            overlap = set(assets) & set(bm_assets)
            if overlap:
                print(f"error: bookmark asset overlap: {sorted(overlap)}",
                      file=sys.stderr)
                return 2
            assets.update(bm_assets)
            tab_note += " + 6th bookmark (experimental)"

    root = mods_dir / mod_menu.MENU_MOD_ID
    if root.exists():
        shutil.rmtree(root)
    (root / "assets").mkdir(parents=True)
    (root / "manifest.toml").write_text(mod_menu.manifest_toml(len(mods)),
                                        encoding="utf-8")
    (root / "init.lua").write_text(mod_menu.init_lua(), encoding="utf-8")
    for dec, blob in assets.items():
        dest = root / "assets" / Path(*dec.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)

    print(f"wrote {root} ({len(assets)} asset file(s), {len(mods)} mod(s) "
          f"listed){tab_note}.")
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


def cmd_modal(args: argparse.Namespace) -> int:
    """Build the STANDALONE mods menu — a custom entity that the book's Tuto
    tab is pointed at. Ships as its own mod; the vanilla tutorial page asset
    is left untouched on disk, only the tab binding moves."""
    game_dir = Path(args.game_dir) if args.game_dir else P.default_game_dir()
    cooking = game_dir / "DarkTalesResources" / "_Cooking"
    if not cooking.is_dir():
        print(f"error: cooking dir not found: {cooking}", file=sys.stderr)
        return 2
    mods_dir = Path(args.mods_dir) if args.mods_dir else P.mods_dir()
    mods = _load_mods(mods_dir)

    try:
        assets = mods_modal.build_modal_assets(
            cooking, load_asset_map(), mods, trigger=not args.no_trigger,
            probe=args.probe, probe_append=args.probe_append)
    except mods_modal.ModsModalError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    root = mods_dir / mods_modal.MODAL_MOD_ID
    if root.exists():
        shutil.rmtree(root)
    (root / "assets").mkdir(parents=True)
    (root / "manifest.toml").write_text(mods_modal.manifest_toml(len(mods)),
                                        encoding="utf-8")
    for dec, blob in assets.items():
        dest = root / "assets" / Path(*dec.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)

    host = ("" if args.no_trigger
            else f", host override {mods_modal.PAGE_HOST_NAME}")
    print(f"wrote {root} ({len(assets)} asset file(s), {len(mods)} mod(s)"
          f"{host}).")
    if not args.no_trigger:
        print("The book's Tutorial tab will open the mod menu instead of the "
              "tutorial page (the tutorial asset itself is not modified).")
    print("Run 'rsmm apply' to install, then open the book in-game.")
    return 0


def cmd_modal_remove(args: argparse.Namespace) -> int:
    mods_dir = Path(args.mods_dir) if args.mods_dir else P.mods_dir()
    root = mods_dir / mods_modal.MODAL_MOD_ID
    if not root.is_dir():
        print("modal mod not present.")
        return 0
    shutil.rmtree(root)
    print(f"removed {root}. Run 'rsmm apply' to restore the host entity.")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    game_dir = Path(args.game_dir) if args.game_dir else P.default_game_dir()
    cooking = game_dir / "DarkTalesResources" / "_Cooking"
    if not cooking.is_dir():
        print(f"error: cooking dir not found: {cooking}", file=sys.stderr)
        return 2

    dec2enc = load_asset_map()
    try:
        left_path, left_bytes = EI.load_entity_asset(cooking, dec2enc, args.left)
        right_path, right_bytes = EI.load_entity_asset(cooking, dec2enc, args.right)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.diff:
        report = EI.format_diff(
            EI.diff_entities(
                left_bytes, right_bytes,
                left_path=left_path.as_posix(),
                right_path=right_path.as_posix(),
            ),
            max_strings=args.max_strings,
        )
    else:
        report = EI.format_summary(
            EI.summarize_entity(left_bytes, path=left_path.as_posix()),
            max_strings=args.max_strings,
        )
    print("\n".join(report))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm menu",
                                 description="In-game mod-list page (native book UI)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="(re)generate the RSMMMenu mod")
    b.add_argument("--game-dir", help="Ravenswatch install dir (auto-detected)")
    b.add_argument("--mods-dir", help="mods directory (default: repo mods/)")
    b.add_argument("--no-tab", action="store_true",
                   help="skip the experimental RSMM page buttons (list only)")
    b.add_argument("--bookmark", action="store_true",
                   help="include the experimental (in-game inert so far) "
                        "6th physical book bookmark")
    b.set_defaults(fn=cmd_build)

    r = sub.add_parser("remove", help="delete the RSMMMenu mod")
    r.add_argument("--mods-dir", help="mods directory (default: repo mods/)")
    r.set_defaults(fn=cmd_remove)

    m = sub.add_parser("modal", help="build the standalone mods menu "
                       "(custom entity on the book's Tuto tab)")
    m.add_argument("--game-dir", help="Ravenswatch install dir (auto-detected)")
    m.add_argument("--mods-dir", help="mods directory (default: repo mods/)")
    m.add_argument("--no-trigger", action="store_true",
                   help="ship the modal asset alone, without the host "
                        "override that points the Tuto tab at it")
    m.add_argument("--probe", action="store_true",
                   help="diagnostic: point the trigger chain at the RETAIL "
                        "Modal_Warning instead of ours. If that modal opens "
                        "with the book, the chain fires and the fault is in "
                        "our modal asset; if nothing opens, the chain is inert")
    m.add_argument("--probe-append", action="store_true",
                   help="diagnostic: append ONE component using only classes "
                        "the host already has. Separates 'appending is inert' "
                        "from 'the injected classes are the problem'")
    m.set_defaults(fn=cmd_modal)

    mr = sub.add_parser("modal-remove", help="delete the RSMMModal mod")
    mr.add_argument("--mods-dir", help="mods directory (default: repo mods/)")
    mr.set_defaults(fn=cmd_modal_remove)

    i = sub.add_parser("inspect", help="summarize or diff cooked entity assets")
    i.add_argument("left", help="decoded asset path for the left entity")
    i.add_argument("right", nargs="?", help="decoded asset path for the right entity")
    i.add_argument("--game-dir", help="Ravenswatch install dir (auto-detected)")
    i.add_argument("--diff", action="store_true",
                   help="compare two entities instead of summarizing one")
    i.add_argument("--max-strings", type=int, default=12,
                   help="limit string samples in the output")
    i.set_defaults(fn=cmd_inspect)

    args = ap.parse_args(argv)
    if args.cmd == "inspect" and args.diff and not args.right:
        ap.error("inspect --diff requires two entity paths")
    if args.cmd == "inspect" and not args.diff:
        args.right = args.left
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
