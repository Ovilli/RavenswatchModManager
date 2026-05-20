"""
Manifest compatibility graph.

Resolves `requires` / `conflicts` / `replaces` declarations across
every enabled mod before the applier runs. Output:

  - mods to auto-disable (because they were replaced by another mod)
  - hard conflicts (manifest pair listed each other as `conflicts`)
  - unmet requirements (declared `requires` mod missing or wrong version)
  - circular requirement cycles

See `docs/STRATEGY.md` §8.
"""

from __future__ import annotations
import operator
import re
from dataclasses import dataclass, field
from pathlib import Path

from rsmm.engine.paths import MODS_DIR
from rsmm.cli.merge import _toml_load


_OP = {
    ">=": operator.ge, "<=": operator.le,
    ">":  operator.gt, "<":  operator.lt,
    "==": operator.eq, "!=": operator.ne, "=": operator.eq,
}


def _parse_version(s: str) -> tuple[int, ...]:
    """Lenient semver parse. Non-numeric suffix dropped."""
    parts = re.findall(r"\d+", s)
    return tuple(int(p) for p in parts) or (0,)


def _parse_dep(spec: str) -> tuple[str, str, tuple[int, ...] | None]:
    """'mod-id >= 1.2' -> ('mod-id', '>=', (1, 2)).
       'mod-id'         -> ('mod-id', '*', None).
    """
    m = re.match(r"^\s*([\w.\-:+]+)\s*([><=!]{1,2})?\s*([\d.]+)?\s*$", spec)
    if not m:
        return spec.strip(), "*", None
    name, op, ver = m.group(1), m.group(2), m.group(3)
    if op and ver:
        return name, op, _parse_version(ver)
    return name, "*", None


def _version_ok(actual: str, op: str, wanted: tuple[int, ...] | None) -> bool:
    if op == "*" or wanted is None:
        return True
    fn = _OP.get(op)
    if not fn:
        return False
    return fn(_parse_version(actual), wanted)


@dataclass
class ModSummary:
    id: str
    version: str
    enabled: bool
    load_order: int
    multiplayer_scope: str
    requires: list[str]
    conflicts: list[str]
    replaces: list[str]
    path: Path


@dataclass
class CompatReport:
    summaries: list[ModSummary] = field(default_factory=list)
    auto_disabled: dict[str, str] = field(default_factory=dict)   # id -> reason
    unmet_requires: list[tuple[str, str]] = field(default_factory=list)
    hard_conflicts: list[tuple[str, str]] = field(default_factory=list)
    cycles: list[list[str]] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.unmet_requires or self.hard_conflicts or self.cycles)


def _summarize(entry: Path) -> ModSummary | None:
    mf = entry / "manifest.toml"
    if not mf.exists():
        return None
    try:
        t = _toml_load(mf)
    except Exception:
        return None
    m = t.get("mod", {})
    return ModSummary(
        id=m.get("id") or entry.name,
        version=str(m.get("version", "0.0.0")),
        enabled=bool(m.get("enabled", True)),
        load_order=int(m.get("load_order", 100)),
        multiplayer_scope=str(m.get("multiplayer_scope", "cosmetic")),
        requires=[str(x) for x in m.get("requires", []) or []],
        conflicts=[str(x) for x in m.get("conflicts", []) or []],
        replaces=[str(x) for x in m.get("replaces", []) or []],
        path=entry,
    )


def analyze() -> CompatReport:
    rep = CompatReport()
    if not MODS_DIR.is_dir():
        return rep
    for entry in sorted(MODS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        s = _summarize(entry)
        if s:
            rep.summaries.append(s)

    by_id = {s.id: s for s in rep.summaries}

    # 1. Replaces: any enabled mod whose `replaces` lists another
    #    present mod auto-disables the older one.
    for s in rep.summaries:
        if not s.enabled:
            continue
        for spec in s.replaces:
            name, _, _ = _parse_dep(spec)
            if name in by_id and by_id[name].enabled and name != s.id:
                rep.auto_disabled[name] = f"replaced by {s.id}"

    # Treat replaced mods as disabled for the rest of the analysis.
    def is_active(mid: str) -> bool:
        if mid not in by_id:
            return False
        if not by_id[mid].enabled:
            return False
        if mid in rep.auto_disabled:
            return False
        return True

    # 2. Hard conflicts: pair both ways or one-sided.
    for s in rep.summaries:
        if not is_active(s.id):
            continue
        for spec in s.conflicts:
            name, _, _ = _parse_dep(spec)
            if is_active(name):
                pair = tuple(sorted((s.id, name)))
                if pair not in {tuple(sorted(p)) for p in rep.hard_conflicts}:
                    rep.hard_conflicts.append(pair)

    # 3. Unmet requires.
    for s in rep.summaries:
        if not is_active(s.id):
            continue
        for spec in s.requires:
            name, op, ver = _parse_dep(spec)
            if name not in by_id:
                rep.unmet_requires.append((s.id, f"missing dep {spec!r}"))
                continue
            if not is_active(name):
                rep.unmet_requires.append((s.id, f"dep disabled: {name}"))
                continue
            if not _version_ok(by_id[name].version, op, ver):
                rep.unmet_requires.append((
                    s.id,
                    f"dep version mismatch: need {spec!r}, "
                    f"got {by_id[name].version}"))

    # 4. Cycles among requires.
    graph: dict[str, list[str]] = {}
    for s in rep.summaries:
        if not is_active(s.id):
            continue
        graph[s.id] = []
        for spec in s.requires:
            name, _, _ = _parse_dep(spec)
            if is_active(name):
                graph[s.id].append(name)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {k: WHITE for k in graph}
    stack: list[str] = []

    def dfs(node: str) -> None:
        color[node] = GRAY
        stack.append(node)
        for nxt in graph.get(node, []):
            if color.get(nxt, WHITE) == GRAY:
                # Cycle: extract from stack
                i = stack.index(nxt)
                rep.cycles.append(stack[i:] + [nxt])
            elif color.get(nxt, WHITE) == WHITE:
                dfs(nxt)
        color[node] = BLACK
        stack.pop()

    for node in graph:
        if color[node] == WHITE:
            dfs(node)

    return rep


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Analyze mod compatibility graph (requires / conflicts / replaces)",
    )
    ap.add_argument("--fail-on-error", action="store_true",
                    help="exit non-zero if any hard conflict / cycle / unmet dep")
    args = ap.parse_args()

    rep = analyze()
    if not rep.summaries:
        print("No mods discovered.")
        return 0

    print(f"{len(rep.summaries)} mod(s):")
    for s in rep.summaries:
        active = (s.enabled and s.id not in rep.auto_disabled)
        mark = "ON " if active else "off"
        extras = []
        if s.requires:
            extras.append(f"requires={s.requires}")
        if s.conflicts:
            extras.append(f"conflicts={s.conflicts}")
        if s.replaces:
            extras.append(f"replaces={s.replaces}")
        if extras:
            print(f"  [{mark}] {s.id} {s.version}  {' '.join(extras)}")
        else:
            print(f"  [{mark}] {s.id} {s.version}")

    if rep.auto_disabled:
        print("\nauto-disabled:")
        for mid, why in rep.auto_disabled.items():
            print(f"  - {mid}: {why}")
    if rep.unmet_requires:
        print("\nunmet requires:")
        for mid, msg in rep.unmet_requires:
            print(f"  - {mid}: {msg}")
    if rep.hard_conflicts:
        print("\nhard conflicts:")
        for a, b in rep.hard_conflicts:
            print(f"  - {a}  <-->  {b}")
    if rep.cycles:
        print("\nrequires cycles:")
        for c in rep.cycles:
            print(f"  - {' -> '.join(c)}")

    if args.fail_on_error and rep.has_errors:
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
