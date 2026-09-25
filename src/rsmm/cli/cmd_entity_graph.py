"""`rsmm entity-graph` — read an entity's components and their links.

    rsmm entity-graph Piper                          groups and their sizes
    rsmm entity-graph Piper --group "Ability Primary"      one group, with links
    rsmm entity-graph Piper --closure "Ability Primary"    everything it pulls in
    rsmm entity-graph Piper --show "Ability Secondary Active Timer"   one component's body
    rsmm entity-graph Piper --json piper.json              the whole graph

An argument is a hero name (Piper, Juliet, ...) or an entity reference
(``Heroes\\Hero_Piper\\Hero_Piper_Projectile.entity.ot``). This is the reader
the ability editor is built on (engine/entity_graph.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _entity_rel(arg: str) -> tuple[str, str] | None:
    from rsmm.engine import corpus
    if arg.endswith(".entity.ot"):
        rel = "EntitySettings/" + arg.replace("\\", "/") + ".EntitySettingsResource.gen"
        return rel, arg.rsplit("\\", 1)[-1][:-len(".entity.ot")]
    for folder in sorted({r.split("/")[2] for r in corpus.rels("EntitySettings/Heroes/Hero_")}):
        if folder.replace("_", "").lower() == ("hero" + arg).replace("_", "").lower():
            rel = f"EntitySettings/Heroes/{folder}/{folder}.entity.ot.EntitySettingsResource.gen"
            return rel, folder
    return None


def _describe(c, index) -> list[str]:
    lines = [f"  {c.name}  ({c.cls.removeprefix('oCEntityCpnt').removesuffix('Settings')})"]
    if c.override:
        lines.append(f"      overrides {c.override.path}")
    for r in c.refs:
        where = "" if r.guid in index else "  [outside]"
        lines.append(f"      -> {r.path}{where}")
    for lit in c.literals[:6]:
        lines.append(f"      = {lit}")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm entity-graph", description=__doc__.split("\n\n")[0])
    ap.add_argument("entity", help="hero name or entity reference")
    ap.add_argument("--group", help="list one group's components with their links")
    ap.add_argument("--closure", help="list everything a group transitively pulls in")
    ap.add_argument("--show", help="one component's body as typed tokens (refs, values, ...)")
    ap.add_argument("--json", type=Path, help="write the whole graph as JSON")
    args = ap.parse_args(argv)

    from rsmm.engine import corpus
    from rsmm.engine import entity_graph as EG

    found = _entity_rel(args.entity)
    raw = corpus.read(found[0]) if found else None
    if raw is None:
        print(f"no entity {args.entity!r} in the corpus or the game install", file=sys.stderr)
        return 1
    g = EG.parse(raw, found[1])
    index = g.by_guid()
    groups = g.groups()

    if args.json:
        args.json.write_text(json.dumps({"entity": g.name, "components": [
            {"index": c.index, "class": c.cls, "group": c.group, "name": c.name,
             "guid": c.guid.hex(),
             "override": c.override.path if c.override else None,
             "refs": [{"path": r.path, "guid": r.guid.hex(), "internal": r.guid in index}
                      for r in c.refs],
             "literals": c.literals} for c in g.components]}, indent=1), encoding="utf-8")
        print(f"{args.json}: {len(g.components)} components")
        return 0

    if args.show:
        hits = [c for c in g.components if c.name == args.show]
        if not hits:
            print(f"no component named {args.show!r}", file=sys.stderr)
            return 1
        for c in hits:
            print(f"{c.group}\\{c.name}  ({c.cls})")
            for t in EG.tokens(c):
                print(f"  +{t.offset:<5} {t.kind:7} {t.text}")
        return 0

    for flag in (args.group, args.closure):
        if flag and flag not in groups:
            print(f"no group {flag!r}; have: {', '.join(sorted(groups))}", file=sys.stderr)
            return 1
    if args.group:
        for c in groups[args.group]:
            print("\n".join(_describe(c, index)))
        return 0
    if args.closure:
        got = g.closure(groups[args.closure])
        by: dict[str, int] = {}
        for c in got:
            by[c.group] = by.get(c.group, 0) + 1
        print(f"{args.closure}: pulls in {len(got)} components across {len(by)} groups")
        for grp, n in sorted(by.items(), key=lambda kv: -kv[1]):
            print(f"  {n:4}  {grp}")
        return 0

    edges = sum(len(c.refs) for c in g.components)
    print(f"{g.name}: {len(g.components)} components, {edges} links, {len(groups)} groups")
    for grp, cs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(cs):4}  {grp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
