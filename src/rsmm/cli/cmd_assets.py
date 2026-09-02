#!/usr/bin/env python3
"""`rsmm assets` — find a cooked asset by its readable path.

The game stores every asset under ``DarkTalesResources/_Cooking/<encoded>``,
where the name is the readable path run through a fixed substitution cipher.
So the install is a directory of 43k unreadable filenames, and "where does the
wolf enemy live" has no answer you can reach with `ls` or `grep`.

`data/asset_map.json` already holds the whole decoded <-> encoded mapping (it
is derived from the engine's own `UsedRscList.ot`), so the answer is a lookup
rather than a scan — no decryption, no guessing at the alphabet, and it works
with no game install present.

  rsmm assets search wolf                 # every path containing "wolf"
  rsmm assets search enemies wolf         # both terms, in any order
  rsmm assets search "Ui/*.png"           # glob when the query has * or ?
  rsmm assets search wolf --encoded       # also print the on-disk name
  rsmm assets show Definitions/Enemies/Standard_Wolf_Dire.enemydef.ot

Two families are deliberately NOT in the map, because the engine reaches them
by convention instead of through `UsedRscList.ot`: the 16 `Audio/*.bank` sound
banks and every `*.UsedRscCache.ot` preload manifest. `show` resolves those
anyway (the same path `apply` uses); `search` cannot list what was never
enumerated, and says so rather than implying the corpus is complete.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys

from rsmm.cli import _term

_LIMIT_DEFAULT = 40


def _norm(p: str) -> str:
    return p.replace("\\", "/")


def search_paths(index: dict[str, str], query: list[str]) -> list[str]:
    """Decoded paths matching every term in ``query``, case-insensitively.

    A term containing ``*`` or ``?`` is matched as a glob against the whole
    path; anything else is a plain substring. Terms are ANDed, so adding one
    narrows — which is how a person actually converges on an asset ("enemies",
    then "wolf", then "elite") without learning a query language.
    """
    # Terms are normalised the same way the paths are: cooked paths are written
    # with backslashes everywhere in the game's own data and in our docs, so a
    # pasted `Definitions\\Enemies\\...` must match rather than find nothing.
    terms = [_norm(t).lower() for t in query if t]
    if not terms:
        return []
    out = []
    for dec in index:
        low = _norm(dec).lower()
        if all(fnmatch.fnmatch(low, t) if ("*" in t or "?" in t) else t in low
               for t in terms):
            out.append(dec)
    return sorted(out, key=lambda p: (len(p), p.lower()))


def _index() -> dict[str, str]:
    from rsmm.engine.asset_map import decoded_to_encoded

    return decoded_to_encoded()


def _cmd_search(args) -> int:
    st = _term.Style(stream=sys.stdout)
    index = _index()
    if not index:
        print("no asset map — run `rsmm rebuild-asset-map` or `rsmm update-data`",
              file=sys.stderr)
        return 1

    hits = search_paths(index, args.query)
    if args.json:
        print(json.dumps([{"decoded": h, "encoded": index[h]} for h in hits], indent=2))
        return 0 if hits else 1

    if not hits:
        print(f"no asset path matches {' '.join(args.query)!r} "
              f"(searched {len(index)} paths)")
        return 1

    shown = hits if args.limit <= 0 else hits[: args.limit]
    for dec in shown:
        print(f"  {st.accent(_norm(dec))}")
        if args.encoded:
            print(f"    {st.dim(index[dec])}")
    tail = "" if len(shown) == len(hits) else f" (showing {len(shown)}, -n 0 for all)"
    print(st.dim(f"\n{len(hits)} match(es) of {len(index)} paths{tail}"))
    return 0


def _cmd_show(args) -> int:
    """Everything known about one readable path: where it lives, and whether
    the install actually has it."""
    from pathlib import Path

    from rsmm.cli.apply_mods import find_game_dir, resolve_special
    from rsmm.engine.paths import COOKING_SUBDIR

    st = _term.Style(stream=sys.stdout)
    index = _index()
    want = _norm(args.path)
    enc = index.get(want)
    origin = "UsedRscList.ot"
    if enc is None:
        # Caches and sound banks are ciphered by convention, never listed.
        enc = resolve_special(want, index)
        origin = "by convention (not in UsedRscList.ot)"
    if enc is None:
        # Try the leaf, then its stem: a typo is usually in the name, and the
        # suffix chain (`.enemydef.ot.DtEnemyDefinition.gen`) is long enough
        # that matching on the whole leaf finds nothing to suggest.
        leaf = want.rsplit("/", 1)[-1]
        near = (search_paths(index, [leaf]) or search_paths(index, [leaf.split(".", 1)[0]]))[:5]
        print(f"unknown asset path: {want}", file=sys.stderr)
        if near:
            print("did you mean:", file=sys.stderr)
            for n in near:
                print(f"  {_norm(n)}", file=sys.stderr)
        return 1

    print(f"  {st.bold('decoded')}  {_norm(want)}")
    print(f"  {st.bold('encoded')}  {enc}")
    print(f"  {st.bold('source')}   {origin}")

    game = find_game_dir()
    if game is None:
        print(st.dim("  install   not found — nothing to check against"))
        return 0
    p = Path(game) / COOKING_SUBDIR / enc.replace("\\", "/")
    bak = p.with_name(p.name + ".rsmm.bak")
    if not p.is_file():
        print(f"  {st.bold('install')}  {st.warn('absent')}")
        return 0
    size = _term.human_bytes(p.stat().st_size)
    state = st.warn("overridden by a mod (.rsmm.bak holds the original)") if bak.is_file() \
        else st.ok("vanilla")
    print(f"  {st.bold('install')}  {size}  {state}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm assets",
                                 description="find a cooked asset by readable path")
    sub = ap.add_subparsers(dest="cmd")

    ps = sub.add_parser("search", help="find readable asset paths by substring or glob")
    ps.add_argument("query", nargs="+", help="terms to match (ANDed); * or ? make it a glob")
    ps.add_argument("-n", "--limit", type=int, default=_LIMIT_DEFAULT,
                    help=f"max results, 0 for all (default {_LIMIT_DEFAULT})")
    ps.add_argument("--encoded", action="store_true", help="also print the on-disk name")
    ps.add_argument("--json", action="store_true", help="machine-readable output")

    pw = sub.add_parser("show", help="encoded path + install state for one asset")
    pw.add_argument("path", help="readable path, e.g. Definitions/Enemies/X.enemydef.ot")

    args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    if args.cmd == "search":
        return _cmd_search(args)
    if args.cmd == "show":
        return _cmd_show(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
