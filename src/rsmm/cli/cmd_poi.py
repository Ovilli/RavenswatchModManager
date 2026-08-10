#!/usr/bin/env python3
"""`rsmm poi` — browse the tiles and kinds a `poi` content def can use.

A POI (point of interest) is a *tile*: one placeable chunk of a generated map —
a shrine, cauldron, teleporter, enemy camp, ruin. A ``poi`` def clones one of
these and adds it to the tile pool of whichever chapters you name, which is what
makes a structure show up somewhere it never did in vanilla.

  rsmm poi                          # chapters, pool sizes, tile counts
  rsmm poi list                     # every clonable tile
  rsmm poi list --grep cauldron     # filter by name
  rsmm poi list --chapter Avalon    # only tiles Avalon already pools
  rsmm poi list --icon              # only tiles that show on the minimap
  rsmm poi kinds Dark_Hills         # kinds that chapter can place
  rsmm poi show Avalon/40x40_Avalon_Cauldron_T1
"""

from __future__ import annotations

import argparse
import sys

from rsmm.engine import map_pool as MP
from rsmm.engine import tile_cook as TC
from rsmm.sdk.kinds import poi as P


def _tile(base: str) -> TC.TileDef | None:
    p = P._tile_path(base)
    if not p.is_file():
        return None
    try:
        return TC.read(p.read_bytes())
    except TC.TileCookError:
        return None


def _pool_of(chapter: str) -> set[str]:
    """Tile stems (`<Biome>/<Name>`) already pooled by ``chapter``."""
    stem = P.CHAPTERS[chapter]
    gen = P._MAPS_DIR / f"{stem}{MP.GEN_SUFFIX}"
    if not gen.is_file():
        return set()
    out = set()
    for path in MP.read_pool(gen.read_bytes()) or []:
        parts = path.replace("\\", "/").split("/")
        if len(parts) >= 3:
            out.add(f"{parts[-2]}/{parts[-1].removesuffix('.tiledef.ot')}")
    return out


def _cmd_overview() -> int:
    tiles = P.known_tiles()
    if not tiles:
        print("no tile corpus — run `python scripts/extract_uncooked.py` first",
              file=sys.stderr)
        return 1
    print(f"{len(tiles)} clonable tiles across "
          f"{len({t.split('/')[0] for t in tiles})} biome directories\n")
    print(f"  {'chapter':<14} {'pooled':>7} {'kinds':>7}")
    for ch in sorted(P.CHAPTERS):
        print(f"  {ch:<14} {len(_pool_of(ch)):>7} {len(P.chapter_kinds(ch)):>7}")
    print("\n  Baba_Yaga      —  scripted boss arena, not tile-generated "
          "(no pool to add to)")
    print("\nrsmm poi list          every tile you can clone"
          "\nrsmm poi kinds <chapter>   what that chapter can place")
    return 0


def _cmd_list(args) -> int:
    tiles = P.known_tiles()
    if args.chapter:
        if args.chapter not in P.CHAPTERS:
            print(f"unknown chapter {args.chapter!r}; valid: "
                  f"{', '.join(sorted(P.CHAPTERS))}", file=sys.stderr)
            return 1
        pooled = _pool_of(args.chapter)
        tiles = [t for t in tiles if t in pooled]
    grep = args.grep.lower() if args.grep else None
    rows = []
    for t in tiles:
        if grep and grep not in t.lower():
            continue
        td = _tile(t)
        if td is None or (args.icon and not td.has_icon):
            continue
        rows.append((t, td))
    if not rows:
        print("(no tiles matched)")
        return 0
    for t, td in rows:
        size = f"{td.width}x{td.height}"
        icon = "*" if td.has_icon else " "
        print(f" {icon} {t:<62} {size:>7}  t={td.weight:<5.3g} "
              f"{', '.join(td.kinds)}")
    print(f"\n{len(rows)} tile(s).  '*' = shows on the minimap.")
    return 0


def _cmd_kinds(args) -> int:
    if args.chapter not in P.CHAPTERS:
        print(f"unknown chapter {args.chapter!r}; valid: "
              f"{', '.join(sorted(P.CHAPTERS))}", file=sys.stderr)
        return 1
    kinds = sorted(P.chapter_kinds(args.chapter))
    if not kinds:
        print("no corpus — run `python scripts/extract_uncooked.py` first",
              file=sys.stderr)
        return 1
    others = set()
    for ch in P.CHAPTERS:
        if ch != args.chapter:
            others |= P.chapter_kinds(ch)
    print(f"{args.chapter}: {len(kinds)} placeable kinds "
          f"('!' = only this chapter)\n")
    for k in kinds:
        print(f"  {'!' if k not in others else ' '} {k}")
    return 0


def _cmd_show(args) -> int:
    td = _tile(args.tile)
    if td is None:
        print(f"no such tile {args.tile!r} (try: rsmm poi list)", file=sys.stderr)
        return 1
    print(f"{args.tile}")
    print(f"  kinds     {', '.join(td.kinds)}")
    print(f"  footprint {td.width}x{td.height}")
    print(f"  weight    {td.weight:g}   (tier field: T1 0.0 / T2 0.33 / T3 0.667,"
          f" NOT a spawn rate)")
    print(f"  icon      {td.icon[2] or '(none — not shown on the minimap)'}")
    print(f"  prefab    {td.entity_ref[1] if len(td.entity_ref) > 1 else '?'}")
    if td.children:
        print(f"  children  {len(td.children)} nested composite block(s)")
    inchap = [c for c in sorted(P.CHAPTERS) if args.tile in _pool_of(c)]
    print(f"  pooled by {', '.join(inchap) or '(no chapter)'}")
    can = [c for c in sorted(P.CHAPTERS)
           if set(td.kinds) & P.chapter_kinds(c) and c not in inchap]
    if can:
        print(f"\n  can be added to: {', '.join(can)}")
        print(f"""
  [[content]]
  kind     = "poi"
  id       = "MyPoi"
  base     = "{args.tile}"
  chapters = [{', '.join(f'"{c}"' for c in can)}]""")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="rsmm poi",
        description="browse map tiles / POIs a `poi` content def can clone")
    sub = ap.add_subparsers(dest="cmd")

    lst = sub.add_parser("list", help="every clonable tile")
    lst.add_argument("--grep", help="filter by name (substring, case-insensitive)")
    lst.add_argument("--chapter", help="only tiles this chapter already pools")
    lst.add_argument("--icon", action="store_true",
                     help="only tiles that show on the minimap")

    kd = sub.add_parser("kinds", help="kinds a chapter can place")
    kd.add_argument("chapter")

    sh = sub.add_parser("show", help="one tile in detail")
    sh.add_argument("tile", help="<Biome>/<Name>")

    args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    if args.cmd == "list":
        return _cmd_list(args)
    if args.cmd == "kinds":
        return _cmd_kinds(args)
    if args.cmd == "show":
        return _cmd_show(args)
    return _cmd_overview()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
