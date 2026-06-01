#!/usr/bin/env python3
"""`rsmm items` — discover vanilla magical objects for item modding.

Modders authoring a new item (``[[content]] kind="item"``) need to know which
``base`` ids exist, which ``value_patches`` labels + defaults a base exposes,
and which ``icon`` stems are available. This command surfaces all of that from
the in-repo cooked corpus (``data/uncooked``), no game install required.

  rsmm items                       # list every base item
  rsmm items list --rarity Common --grep armor
  rsmm items show Armor_Per_Object # rarity, icon, editable value fields
  rsmm items icons [--grep arm]    # list usable icon stems
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rsmm.engine import magic_item_cook as cook
from rsmm.engine.paths import DATA_DIR

_MO_DIR = DATA_DIR / "uncooked" / "EntitySettings" / "Objects" / "Magical_Objects"
_ICON_DIR = DATA_DIR / "uncooked" / "Ui" / "Objects"
_RARITIES = ("Common", "Rare", "Epic", "Legendary", "Cursed", "Powerups")


def _iter_items():
    """Yield (id, rarity, cooked_path) for every vanilla magical object."""
    for rarity in _RARITIES:
        d = _MO_DIR / rarity
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.entity.ot.EntitySettingsResource.gen")):
            yield p.name.split(".entity.ot.", 1)[0], rarity, p


def _find_item(item_id: str):
    low = item_id.lower()
    for iid, rarity, p in _iter_items():
        if iid == item_id or iid.lower() == low:
            return iid, rarity, p
    return None


def _icon_stems(grep: str | None) -> list[str]:
    if not _ICON_DIR.is_dir():
        return []
    out = set()
    for p in _ICON_DIR.glob("UI_Object_*.png*"):
        stem = p.name[len("UI_Object_"):].split(".png", 1)[0]
        if grep is None or grep.lower() in stem.lower():
            out.add(stem)
    return sorted(out)


def _cmd_list(args) -> int:
    rows = []
    for iid, rarity, p in _iter_items():
        if args.rarity and rarity.lower() != args.rarity.lower():
            continue
        if args.grep and args.grep.lower() not in iid.lower():
            continue
        icon = cook.find_icon(p.read_bytes()) or ""
        rows.append((rarity, iid, icon))
    if not rows:
        print("(no items found — does data/uncooked/ exist?)", file=sys.stderr)
        return 1
    for rarity, iid, icon in rows:
        icon_stem = icon.split("UI_Object_", 1)[-1].split(".png", 1)[0] if icon else "-"
        print(f"  [{rarity:>9s}]  {iid:<34s}  icon={icon_stem}")
    print(f"\n{len(rows)} item(s)")
    return 0


def _cmd_show(args) -> int:
    found = _find_item(args.id)
    if not found:
        print(f"unknown item: {args.id} (try `rsmm items list`)", file=sys.stderr)
        return 1
    iid, rarity, p = found
    data = p.read_bytes()
    print(f"  id        : {iid}")
    print(f"  rarity    : {rarity}")
    print(f"  icon      : {cook.find_icon(data)}")
    fields = cook.list_value_fields(data)
    if fields:
        print("  value_patches targets (label -> default):")
        for label, val in fields:
            print(f"      {val:>12g}  {label!r}")
        lbl, dflt = fields[0]
        print(f'\n  e.g.  value_patches = [["{lbl}", {dflt:g}, <new>]]')
    else:
        print("  (no editable value fields discovered)")
    return 0


def _cmd_icons(args) -> int:
    stems = _icon_stems(args.grep)
    if not stems:
        print("(no icons found — does data/uncooked/Ui/Objects exist?)",
              file=sys.stderr)
        return 1
    for s in stems:
        print(f"  {s}")
    print(f"\n{len(stems)} icon(s). Use as e.g.  icon = \"{stems[0]}\"")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm items",
                                 description="Discover vanilla magical objects.")
    sub = ap.add_subparsers(dest="cmd")

    pl = sub.add_parser("list", help="list base items")
    pl.add_argument("--rarity", help="filter: " + ", ".join(_RARITIES))
    pl.add_argument("--grep", help="substring filter on id")

    ps = sub.add_parser("show", help="show one item's icon + value fields")
    ps.add_argument("id")

    pi = sub.add_parser("icons", help="list usable icon stems")
    pi.add_argument("--grep", help="substring filter on stem")

    args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    if args.cmd == "show":
        return _cmd_show(args)
    if args.cmd == "icons":
        return _cmd_icons(args)
    # default (no subcommand or `list`)
    if args.cmd in (None, "list"):
        if not hasattr(args, "rarity"):
            args.rarity = args.grep = None
        return _cmd_list(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
