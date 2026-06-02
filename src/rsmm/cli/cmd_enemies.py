#!/usr/bin/env python3
"""`rsmm enemies` — discover vanilla enemies for enemy modding.

Modders authoring a custom enemy (``[[content]] kind="enemy"``) need to know
which ``base`` ids exist, which ``tribe`` each belongs to, and which ``flags``
its camp flag-list selector matches on. This command surfaces all of that from
the in-repo cooked corpus (``data/uncooked``), no game install required.

  rsmm enemies                      # list every base enemy
  rsmm enemies list --tribe Gnolls --grep elite
  rsmm enemies show Gnoll_Shielded  # tribe, entity, flags, spawn weight
  rsmm enemies tribes               # list tribe names usable as `tribe=...`
"""

from __future__ import annotations

import argparse
import sys

from rsmm.engine import cooked
from rsmm.engine.cooked_schemas import definitions as _defs
from rsmm.engine.paths import DATA_DIR

_ENEMY_DIR = DATA_DIR / "uncooked" / "Definitions" / "Enemies"
_TRIBE_DIR = DATA_DIR / "uncooked" / "Definitions" / "EnemyTribes"
_GEN_SUFFIX = ".enemydef.ot.DtEnemyDefinition.gen"
_TRIBE_SUFFIX = ".enemytribedef.ot.DtEnemyTribeDefinition.gen"


def _tribe_name(tribe_ref) -> str:
    """'EnemyTribes\\Gnolls.enemytribedef.ot' -> 'Gnolls' (or '-' if none)."""
    leaf = (tribe_ref or ["", ""])[1] or ""
    leaf = leaf.replace("\\", "/").rsplit("/", 1)[-1]
    return leaf.split(".enemytribedef", 1)[0] if leaf else "-"


def _decode(path):
    """Return the decoded enemy body, or None on parse failure."""
    try:
        cf = cooked.parse(path.read_bytes())
        return _defs._SPECS["oCDtEnemyDefinition"].decode_body(cf.sections[-1].payload)
    except (ValueError, IndexError, KeyError):
        return None


def _iter_enemies():
    """Yield (id, body, path) for every vanilla enemy def."""
    if not _ENEMY_DIR.is_dir():
        return
    for p in sorted(_ENEMY_DIR.glob(f"*{_GEN_SUFFIX}")):
        body = _decode(p)
        if body is not None:
            yield p.name[: -len(_GEN_SUFFIX)], body, p


def _find_enemy(enemy_id: str):
    low = enemy_id.lower()
    for eid, body, p in _iter_enemies():
        if eid == enemy_id or eid.lower() == low:
            return eid, body, p
    return None


def _cmd_list(args) -> int:
    rows = []
    for eid, body, _p in _iter_enemies():
        tribe = _tribe_name(body.get("tribe_ref"))
        if args.tribe and tribe.lower() != args.tribe.lower():
            continue
        if args.grep and args.grep.lower() not in eid.lower():
            continue
        rows.append((tribe, eid, body.get("spawn_weight", 0.0)))
    if not rows:
        print("(no enemies found — does data/uncooked/ exist?)", file=sys.stderr)
        return 1
    for tribe, eid, weight in rows:
        print(f"  [{tribe:>18s}]  {eid:<34s}  weight={weight:g}")
    print(f"\n{len(rows)} enemy(ies)")
    return 0


def _cmd_show(args) -> int:
    found = _find_enemy(args.id)
    if not found:
        print(f"unknown enemy: {args.id} (try `rsmm enemies list`)", file=sys.stderr)
        return 1
    eid, body, _p = found
    print(f"  id          : {eid}")
    print(f"  tribe       : {_tribe_name(body.get('tribe_ref'))}")
    print(f"  entity_ref  : {(body.get('entity_ref') or ['', ''])[1]}")
    print(f"  flags       : {', '.join(body.get('flags') or []) or '-'}")
    print(f"  spawn_weight: {body.get('spawn_weight', 0.0):g}")
    print(f'\n  e.g.  [[content]] kind="enemy" id="My_{eid}" base="{eid}"')
    return 0


def _cmd_tribes(args) -> int:
    names = set()
    if _TRIBE_DIR.is_dir():
        for p in _TRIBE_DIR.glob(f"*{_TRIBE_SUFFIX}"):
            names.add(p.name[: -len(_TRIBE_SUFFIX)])
    # also harvest tribes actually referenced by enemies (covers odd paths)
    for _eid, body, _p in _iter_enemies():
        t = _tribe_name(body.get("tribe_ref"))
        if t != "-":
            names.add(t)
    if args.grep:
        names = {n for n in names if args.grep.lower() in n.lower()}
    if not names:
        print("(no tribes found)", file=sys.stderr)
        return 1
    for n in sorted(names):
        print(f"  {n}")
    print(f"\n{len(names)} tribe(s). Use as e.g.  tribe = \"{sorted(names)[0]}\"")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm enemies",
                                 description="Discover vanilla enemies.")
    sub = ap.add_subparsers(dest="cmd")

    pl = sub.add_parser("list", help="list base enemies")
    pl.add_argument("--tribe", help="filter by tribe name")
    pl.add_argument("--grep", help="substring filter on id")

    ps = sub.add_parser("show", help="show one enemy's tribe, entity, flags")
    ps.add_argument("id")

    pt = sub.add_parser("tribes", help="list tribe names usable as tribe=...")
    pt.add_argument("--grep", help="substring filter on tribe name")

    args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    if args.cmd == "show":
        return _cmd_show(args)
    if args.cmd == "tribes":
        if not hasattr(args, "grep"):
            args.grep = None
        return _cmd_tribes(args)
    if args.cmd in (None, "list"):
        if not hasattr(args, "tribe"):
            args.tribe = args.grep = None
        return _cmd_list(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
