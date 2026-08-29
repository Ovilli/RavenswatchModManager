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
  rsmm items catalog               # what the INSTALL actually offers, with names
  rsmm items ban --add Armor_Per_Object   # edit the managed ban list

`list`/`show`/`icons` read the in-repo corpus and serve item AUTHORING.
`catalog`/`ban` read the install and serve item BANNING — a different set,
because the corpus carries templates and unreleased items the game never
offers, and only what the catalog lists can be banned.
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
    """Resolve a base id to (id, rarity, cooked_path).

    Accepts both the bare id (``Armor_Per_Object``) and the rarity-qualified
    path form the corpus is laid out in (``Common/Armor_Per_Object``) — the
    latter is what the enemy kind uses for its donors, and the docs teach it
    for items too. A wrong rarity prefix does not match, so a typo still
    surfaces as "unknown item" rather than resolving to the wrong file.
    """
    want_rarity, _, stem = str(item_id).replace("\\", "/").rpartition("/")
    low = stem.lower()
    want_low = want_rarity.lower()
    for iid, rarity, p in _iter_items():
        if iid.lower() != low:
            continue
        if want_rarity and rarity.lower() != want_low:
            continue
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
    # Labels whose inline value is shadowed by a selector/reference — patching
    # them via value_patches is a silent no-op. Cross-referenced from the
    # before-END scanner so the primary listing carries the warning too.
    from rsmm.engine.talent_values import list_talent_values
    shadowed = {tv.label for tv in list_talent_values(data) if tv.is_overridden}
    fields = cook.list_value_fields(data)
    if fields:
        print("  value_patches targets (label -> default):")
        for label, val in fields:
            mark = "  [shadowed: editing has NO effect]" if label in shadowed else ""
            print(f"      {val:>12g}  {label!r}{mark}")
        live = [(lab, d) for lab, d in fields if lab not in shadowed]
        lbl, dflt = (live or fields)[0]
        print(f'\n  e.g.  value_patches = [["{lbl}", {dflt:g}, <new>]]')
    else:
        msg = "  (no value_patches fields via the standard scanner"
        print(msg + (")" if args.raw else "; try --raw)"))
    if args.raw:
        # Broader before-END scan (also picks up int32 counts + stat nodes the
        # after-label value_patches scanner misses). Useful for items that show
        # nothing above.
        from rsmm.engine.talent_values import list_talent_values
        seen = {lbl for lbl, _ in fields}
        extra = [tv for tv in list_talent_values(data) if tv.label not in seen]
        print("\n  --raw (before-END scan; int nodes tagged):")
        if not extra:
            print("      (nothing additional)")
        any_shadowed = False
        for tv in extra:
            shown = int(tv.value) if tv.is_int else f"{tv.value:g}"
            tag = " [int]" if tv.is_int else ""
            if tv.is_overridden:
                tag += " [shadowed]"
                any_shadowed = True
            print(f"      {shown:>12}  {tv.label!r}{tag}")
        if any_shadowed:
            print("\n  [shadowed] = value sourced from a selector/reference; "
                  "editing the inline\n  number has NO in-game effect. Use "
                  "talent_values.clear_value_override()\n  to make it "
                  "authoritative (drops its selector/curve binding).")
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


def _cmd_catalog(args) -> int:
    """What the install's catalog actually offers, with display names + icons."""
    from rsmm.engine import item_catalog as IC

    if args.json:
        print(IC.to_json(icons=args.icons, lang=args.lang))
        return 0
    items = IC.catalog(lang=args.lang)
    if not items:
        print("no install reachable (or no LiveOps manifest found)", file=sys.stderr)
        return 1
    banned = set(_bans(args))
    for it in items:
        if args.rarity and it.rarity.lower() != args.rarity.lower():
            continue
        hay = f"{it.id} {it.name or ''}".lower()
        if args.grep and args.grep.lower() not in hay:
            continue
        mark = "BANNED" if it.id in banned else ""
        print(f"  [{it.rarity:<10}] {(it.name or '—'):<28} {it.id:<44} {mark}")
    return 0


def _bans(args) -> list[str]:
    from rsmm.engine import item_bans
    return item_bans.read_bans(getattr(args, "mod", None) or item_bans.DEFAULT_MOD_ID)


def _cmd_ban(args) -> int:
    """Read or edit the managed ban list."""
    import json as _json

    from rsmm.engine import item_bans

    mod = args.mod or item_bans.DEFAULT_MOD_ID
    current = set(item_bans.read_bans(mod))

    if args.set is not None:
        wanted = {x for x in args.set.split(",") if x.strip()}
    else:
        wanted = set(current)
        wanted |= {x for x in (args.add or "").split(",") if x.strip()}
        wanted -= {x for x in (args.remove or "").split(",") if x.strip()}

    changed = wanted != current
    if changed:
        try:
            path = item_bans.write_bans(sorted(wanted), mod)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    else:
        path = item_bans.manifest_path(mod)

    if args.json:
        print(_json.dumps({"ok": True, "mod": mod, "items": sorted(wanted),
                           "changed": changed, "path": str(path)}, indent=1))
        return 0
    if not wanted:
        print(f"{mod}: no items banned")
    else:
        print(f"{mod}: {len(wanted)} item(s) banned")
        for i in sorted(wanted):
            print(f"  {i}")
    if changed:
        print("\nRun `rsmm apply` to write it to the game.")
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
    ps.add_argument("--raw", action="store_true",
                    help="also dump a broad before-END value scan (catches "
                         "int counts + items the standard scanner misses)")

    pi = sub.add_parser("icons", help="list usable icon stems")
    pi.add_argument("--grep", help="substring filter on stem")

    pc = sub.add_parser("catalog",
                        help="items the INSTALL offers, with display names")
    pc.add_argument("--json", action="store_true", help="machine-readable output")
    pc.add_argument("--icons", action="store_true",
                    help="with --json, inline each icon as a base64 PNG data URL")
    pc.add_argument("--lang", default="EN", help="display-name language (default EN)")
    pc.add_argument("--rarity", help="filter: " + ", ".join(_RARITIES))
    pc.add_argument("--grep", help="substring filter on id or display name")
    pc.add_argument("--mod", help="ban-list mod to mark against (default: managed)")

    pb = sub.add_parser("ban", help="read or edit the managed item ban list")
    pb.add_argument("--add", help="comma-separated item ids to ban")
    pb.add_argument("--remove", help="comma-separated item ids to un-ban")
    pb.add_argument("--set", help="comma-separated ids to ban, replacing the list")
    pb.add_argument("--mod", help="mod folder to edit (default: banned-items)")
    pb.add_argument("--json", action="store_true", help="machine-readable output")

    args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    if args.cmd == "show":
        return _cmd_show(args)
    if args.cmd == "icons":
        return _cmd_icons(args)
    if args.cmd == "catalog":
        return _cmd_catalog(args)
    if args.cmd == "ban":
        return _cmd_ban(args)
    # default (no subcommand or `list`)
    if args.cmd in (None, "list"):
        if not hasattr(args, "rarity"):
            args.rarity = args.grep = None
        return _cmd_list(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
