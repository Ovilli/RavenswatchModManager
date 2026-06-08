"""
Manifest dependency graph pre-validation (strategy §8 "Safe Overrides").

Standalone module — does not depend on `rsmm.cli.compat`. Reads every
`mods/<id>/manifest.toml` via `tomllib`, validates the resulting graph,
and produces a deterministic load order honoring `load_order` then
`priority` as a tiebreaker.

Public API:
    load_manifests(mods_dir)            -> dict[str, ManifestRecord]
    validate_graph(records)             -> list[GraphIssue]
    topo_order(records)                 -> list[str]
    format_issues(issues)               -> str

Issue codes:
    missing-dep, version-mismatch, hard-conflict, cycle,
    replace-shadow, dup-id, parse-error,
    missing-recommend, recommend-version, suggest

Dependency keys (fabric.mod.json analogs):
    requires   (depends)   hard — error if absent/disabled/out of range
    recommends (recommends) soft — warn, never blocks apply
    suggests   (suggests)   info — purely advisory
    conflicts  (breaks)    hard — error if the named mod is also enabled
    replaces               auto-disables the named older mod
Version ranges follow npm/Fabric semver: `>=1.2 <2.0`, `1.2.x`, `^1.2`,
`~1.2`, `*` — see `version_satisfies`.

Severities: error | warn | info
"""

from __future__ import annotations

import operator
import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ManifestRecord:
    """One mod's parsed manifest, only the fields the graph cares about."""

    id: str
    path: Path
    version: str = "0.0.0"
    enabled: bool = True
    load_order: int = 100
    priority: int = 0
    requires: list[str] = field(default_factory=list)
    recommends: list[str] = field(default_factory=list)
    suggests: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    replaces: list[str] = field(default_factory=list)
    parse_error: str | None = None


@dataclass(frozen=True)
class GraphIssue:
    severity: str            # "error" | "warn" | "info"
    code: str                # short token (missing-dep, cycle, ...)
    mods: tuple[str, ...]    # involved mod ids (may be empty for global)
    message: str
    fix: str | None = None


_VALID_SEVERITY = {"error", "warn", "info"}


# ---------------------------------------------------------------------------
# Version + dep-spec parsing
# ---------------------------------------------------------------------------


_OPS = {
    ">=": operator.ge,
    "<=": operator.le,
    ">":  operator.gt,
    "<":  operator.lt,
    "==": operator.eq,
    "=":  operator.eq,
    "!=": operator.ne,
}


def _parse_version(s: str) -> tuple[int, ...]:
    """Lenient semver: pull all integer runs. '1.2.3-rc1' -> (1, 2, 3, 1)."""
    parts = re.findall(r"\d+", s or "")
    return tuple(int(p) for p in parts) or (0,)


_DEP_RE = re.compile(r"^\s*([\w.\-:+]+)\s*(>=|<=|==|!=|>|<|=)?\s*([\d.\w\-]+)?\s*$")


def _parse_dep(spec: str) -> tuple[str, str | None, tuple[int, ...] | None]:
    """'mod-id >= 1.2' -> ('mod-id', '>=', (1, 2)).
       'mod-id'         -> ('mod-id', None, None).
    """
    m = _DEP_RE.match(spec or "")
    if not m:
        return (spec or "").strip(), None, None
    name, op, ver = m.group(1), m.group(2), m.group(3)
    if op and ver is not None:
        return name, op, _parse_version(ver)
    return name, None, None


def _version_ok(have: tuple[int, ...], op: str, want: tuple[int, ...]) -> bool:
    fn = _OPS.get(op)
    if fn is None:
        return True
    # Pad the shorter tuple with zeros so (1, 2) and (1, 2, 0) compare equal.
    n = max(len(have), len(want))
    h = have + (0,) * (n - len(have))
    w = want + (0,) * (n - len(want))
    return fn(h, w)


# ---------------------------------------------------------------------------
# Semver ranges (Fabric / npm style)
#
# `requires`/`recommends`/`conflicts` specs are "<mod-id> <range>" where the
# range is one of:
#   *  /  any            match any version
#   >=1.2  <2.0          space- or comma-separated comparators, ALL must hold
#   1.2.x  /  1.x        wildcard -> the implied [>=, <) window
#   1.2  /  1            partial bare version -> same window as the wildcard
#   1.2.3               full bare version -> exact match
#   ^1.2.3              caret  -> >=1.2.3 <2.0.0 (npm semantics, 0.x special)
#   ~1.2.3              tilde  -> >=1.2.3 <1.3.0
# `_parse_dep` (single-op only) is kept for back-compat; new call sites use
# `split_dep` + `version_satisfies`, which understand the full grammar.
# ---------------------------------------------------------------------------

#: A range token's leading operator (so `split_dep` can tell a glued
#: "<name><op><ver>" apart from a bare "<name>").
_RANGE_LEAD = "<>=!~^"


def split_dep(spec: str) -> tuple[str, str | None]:
    """Split a dep spec into (mod-id, range-string|None).

    Accepts both space-separated ("mod >=1.2 <2.0") and glued single-op
    ("mod>=1.2") forms. A bare "mod" yields (mod, None) = any version.
    """
    s = (spec or "").strip()
    if not s:
        return "", None
    parts = s.split(None, 1)
    if len(parts) == 1:
        m = re.match(rf"^([\w.\-:+]+?)\s*([{_RANGE_LEAD}].*)$", s)
        if m:
            return m.group(1), m.group(2).strip()
        return s, None
    return parts[0], parts[1].strip()


def _expand_token(tok: str) -> list[tuple[str, tuple[int, ...]]]:
    """One range token -> list of (op, version) comparators ANDed together.
    An empty list means "no constraint" (match anything)."""
    t = tok.strip()
    if not t or t in ("*", "x", "X", "any"):
        return []
    m = re.match(r"^(>=|<=|==|!=|>|<|=)\s*(.+)$", t)
    if m:
        op = "==" if m.group(1) == "=" else m.group(1)
        return [(op, _parse_version(m.group(2)))]
    if t[0] == "^":
        return _caret(t[1:])
    if t[0] == "~":
        return _tilde(t[1:])
    # wildcard (1.2.x) or partial bare (1.2) -> implied window; full bare exact.
    if re.search(r"\.(x|X|\*)$", t) or t.count(".") < 2:
        return _window(t)
    return [("==", _parse_version(t))]


def _nums(v: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", v)]


def _window(t: str) -> list[tuple[str, tuple[int, ...]]]:
    """`1.2.x` / `1.x` / `1.2` / `1` -> [>=lo, <hi). Bare `x`/`*` -> any."""
    p = _nums(t)
    if not p:
        return []
    if len(p) >= 3:                       # fully fixed -> exact
        return [("==", tuple(p))]
    if len(p) == 2:                       # 1.2.x / 1.2  -> >=1.2.0 <1.3.0
        return [(">=", (p[0], p[1], 0)), ("<", (p[0], p[1] + 1, 0))]
    return [(">=", (p[0], 0, 0)), ("<", (p[0] + 1, 0, 0))]   # 1.x / 1


def _caret(v: str) -> list[tuple[str, tuple[int, ...]]]:
    p = _nums(v)
    if not p:
        return []
    major = p[0]
    minor = p[1] if len(p) > 1 else 0
    patch = p[2] if len(p) > 2 else 0
    lo = (major, minor, patch)
    if major > 0:
        hi = (major + 1, 0, 0)
    elif minor > 0:
        hi = (0, minor + 1, 0)
    elif patch > 0:
        hi = (0, 0, patch + 1)
    else:                                  # all-zero: bound by precision given
        hi = (0, 0, 1) if len(p) >= 3 else ((0, 1, 0) if len(p) == 2 else (1, 0, 0))
    return [(">=", lo), ("<", hi)]


def _tilde(v: str) -> list[tuple[str, tuple[int, ...]]]:
    p = _nums(v)
    if not p:
        return []
    major = p[0]
    minor = p[1] if len(p) > 1 else 0
    patch = p[2] if len(p) > 2 else 0
    lo = (major, minor, patch)
    hi = (major, minor + 1, 0) if len(p) >= 2 else (major + 1, 0, 0)
    return [(">=", lo), ("<", hi)]


def version_satisfies(have: str, range_spec: str | None) -> bool:
    """True if version string `have` falls inside `range_spec` (None/`*` = any)."""
    if not range_spec or range_spec.strip() in ("*", "any"):
        return True
    comps: list[tuple[str, tuple[int, ...]]] = []
    for tok in re.split(r"[\s,]+", range_spec.strip()):
        if tok:
            comps.extend(_expand_token(tok))
    if not comps:
        return True
    hv = _parse_version(have)
    return all(_version_ok(hv, op, want) for op, want in comps)


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def load_manifests(mods_dir: Path) -> dict[str, ManifestRecord]:
    """Scan `mods_dir` for `<id>/manifest.toml`, parse each, return by id.

    Records with parse errors are still included (so `validate_graph` can
    report them) with `parse_error` populated and `enabled=False`.

    Directories beginning with `_` or `.` are skipped (internal scratch).
    If two folders declare the same `id`, both are kept under unique
    synthetic keys (folder-name) so `dup-id` can report them.
    """
    out: dict[str, ManifestRecord] = {}
    if not mods_dir.is_dir():
        return out
    for entry in sorted(mods_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        mf = entry / "manifest.toml"
        if not mf.exists():
            continue
        rec = _load_one(mf, fallback_id=entry.name)
        # Avoid clobbering on duplicate id: synth a key but keep rec.id real.
        key = rec.id if rec.id not in out else f"{rec.id}@{entry.name}"
        out[key] = rec
    return out


def _load_one(path: Path, fallback_id: str) -> ManifestRecord:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return ManifestRecord(
            id=fallback_id, path=path, enabled=False, parse_error=str(e),
        )
    meta = data.get("mod", {}) or {}
    return ManifestRecord(
        id=str(meta.get("id", fallback_id)),
        path=path,
        version=str(meta.get("version", "0.0.0")),
        enabled=bool(meta.get("enabled", True)),
        load_order=int(meta.get("load_order", 100)),
        priority=int(meta.get("priority", 0)),
        requires=list(meta.get("requires", []) or []),
        recommends=list(meta.get("recommends", []) or []),
        suggests=list(meta.get("suggests", []) or []),
        conflicts=list(meta.get("conflicts", []) or []),
        replaces=list(meta.get("replaces", []) or []),
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_graph(records: dict[str, ManifestRecord]) -> list[GraphIssue]:
    """Return every issue found in the graph. Deterministic ordering.

    Severities:
        error  - missing-dep, version-mismatch, hard-conflict, cycle,
                 dup-id, parse-error
        info   - replace-shadow (loader auto-disables; not a hard failure)
    """
    issues: list[GraphIssue] = []

    # Parse errors first.
    for rec in records.values():
        if rec.parse_error:
            issues.append(GraphIssue(
                severity="error",
                code="parse-error",
                mods=(rec.id,),
                message=f"{rec.id}: manifest.toml failed to parse: {rec.parse_error}",
                fix="Fix the TOML syntax; run `python3 -c 'import tomllib; "
                    "tomllib.load(open(...,\"rb\"))'` to pinpoint the line.",
            ))

    # Build id -> rec map (preferring real ids, ignoring synthetic dup keys).
    by_id: dict[str, list[ManifestRecord]] = {}
    for rec in records.values():
        by_id.setdefault(rec.id, []).append(rec)

    # Dup-id detection.
    for mod_id, recs in sorted(by_id.items()):
        if len(recs) > 1:
            paths = ", ".join(str(r.path) for r in recs)
            issues.append(GraphIssue(
                severity="error",
                code="dup-id",
                mods=tuple(sorted({r.id for r in recs})),
                message=f"two or more manifests declare id={mod_id!r}: {paths}",
                fix="Rename one of the folders + change its `id` field.",
            ))

    # First-wins lookup for ALL further checks (after dup-id is reported).
    primary: dict[str, ManifestRecord] = {mid: recs[0] for mid, recs in by_id.items()}
    enabled_ids = {mid for mid, r in primary.items() if r.enabled}

    # replace-shadow (info): replaces-target is enabled.
    for rec in _enabled_sorted(primary):
        for spec in rec.replaces:
            target, _ = split_dep(spec)
            if target in enabled_ids and target != rec.id:
                issues.append(GraphIssue(
                    severity="info",
                    code="replace-shadow",
                    mods=(rec.id, target),
                    message=f"{rec.id} replaces {target}; loader will auto-disable {target}.",
                    fix=f"Set `enabled = false` on {target} to silence this notice.",
                ))

    # missing-dep + version-mismatch (hard `requires`) and the soft tiers
    # `recommends` (warn) / `suggests` (info), mirroring fabric.mod.json.
    for rec in _enabled_sorted(primary):
        # Hard dependencies: error on missing/disabled/out-of-range.
        for spec in rec.requires:
            name, rng = split_dep(spec)
            target = primary.get(name)
            if target is None or not target.enabled:
                issues.append(GraphIssue(
                    severity="error",
                    code="missing-dep",
                    mods=(rec.id, name),
                    message=f"{rec.id} requires {spec!r}, but {name} is "
                            f"{'absent' if target is None else 'disabled'}.",
                    fix=f"Install/enable {name}"
                        + (f" (need version {rng})" if rng else "")
                        + ", or remove the requires entry.",
                ))
                continue
            if rng and not version_satisfies(target.version, rng):
                issues.append(GraphIssue(
                    severity="error",
                    code="version-mismatch",
                    mods=(rec.id, name),
                    message=f"{rec.id} requires {name} {rng}, "
                            f"but installed {name} is {target.version}.",
                    fix=f"Upgrade {name} to a matching version "
                        "or relax the requires constraint.",
                ))

        # Soft recommendations: warn if absent/disabled or out of range, but
        # never block the apply.
        for spec in rec.recommends:
            name, rng = split_dep(spec)
            target = primary.get(name)
            if target is None or not target.enabled:
                issues.append(GraphIssue(
                    severity="warn",
                    code="missing-recommend",
                    mods=(rec.id, name),
                    message=f"{rec.id} recommends {spec!r}, but {name} is "
                            f"{'absent' if target is None else 'disabled'}.",
                    fix=f"Install/enable {name} for the intended experience, "
                        "or ignore this notice.",
                ))
            elif rng and not version_satisfies(target.version, rng):
                issues.append(GraphIssue(
                    severity="warn",
                    code="recommend-version",
                    mods=(rec.id, name),
                    message=f"{rec.id} recommends {name} {rng}, "
                            f"but installed {name} is {target.version}.",
                    fix=f"Upgrade {name} to a matching version, or ignore.",
                ))

        # Suggestions: purely informational.
        for spec in rec.suggests:
            name, _ = split_dep(spec)
            target = primary.get(name)
            if target is None or not target.enabled:
                issues.append(GraphIssue(
                    severity="info",
                    code="suggest",
                    mods=(rec.id, name),
                    message=f"{rec.id} suggests {name} (optional companion mod).",
                    fix=f"Try {name} if you want the extra integration.",
                ))

    # hard-conflict: any enabled pair where either lists the other.
    seen_pairs: set[tuple[str, str]] = set()
    for rec in _enabled_sorted(primary):
        for spec in rec.conflicts:
            target_name, _ = split_dep(spec)
            target = primary.get(target_name)
            if target is None or not target.enabled or target.id == rec.id:
                continue
            pair = tuple(sorted((rec.id, target.id)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            issues.append(GraphIssue(
                severity="error",
                code="hard-conflict",
                mods=pair,
                message=f"{pair[0]} and {pair[1]} declare a hard conflict.",
                fix=f"Disable one of: {pair[0]}, {pair[1]}.",
            ))

    # cycle: among enabled mods only, on requires edges.
    for cyc in _find_cycles(primary, enabled_ids):
        issues.append(GraphIssue(
            severity="error",
            code="cycle",
            mods=tuple(cyc),
            message="requires cycle: " + " -> ".join(cyc + [cyc[0]]),
            fix="Break the cycle by removing one `requires` edge.",
        ))

    return issues


def _enabled_sorted(primary: dict[str, ManifestRecord]) -> list[ManifestRecord]:
    return sorted(
        (r for r in primary.values() if r.enabled),
        key=lambda r: r.id,
    )


def _find_cycles(
    primary: dict[str, ManifestRecord],
    enabled_ids: set[str],
) -> list[list[str]]:
    """Return one canonical (lex-min rotation) representation of each
    distinct simple cycle in the `requires` graph, deterministically.

    Only edges where both endpoints are enabled + present count.
    """
    # Build adjacency: src_id -> sorted list of target ids.
    adj: dict[str, list[str]] = {}
    for mid in sorted(enabled_ids):
        rec = primary[mid]
        edges: list[str] = []
        for spec in rec.requires:
            name, _ = split_dep(spec)
            if name in enabled_ids and name != mid:
                edges.append(name)
        adj[mid] = sorted(set(edges))

    found: set[tuple[str, ...]] = set()
    cycles: list[list[str]] = []

    # DFS from each node; record back-edges as cycles.
    def dfs(start: str, node: str, stack: list[str], on_stack: set[str]) -> None:
        for nxt in adj.get(node, ()):
            if nxt == start and len(stack) >= 1:
                cyc = stack[:]
                canon = _canonical_rotation(cyc)
                if canon not in found:
                    found.add(canon)
                    cycles.append(list(canon))
            elif nxt not in on_stack:
                on_stack.add(nxt)
                stack.append(nxt)
                dfs(start, nxt, stack, on_stack)
                stack.pop()
                on_stack.discard(nxt)

    for src in sorted(adj):
        dfs(src, src, [src], {src})

    cycles.sort()
    return cycles


def _canonical_rotation(cyc: list[str]) -> tuple[str, ...]:
    """Rotate `cyc` so it starts at its lexicographically smallest node."""
    if not cyc:
        return ()
    i = min(range(len(cyc)), key=lambda k: cyc[k])
    return tuple(cyc[i:] + cyc[:i])


# ---------------------------------------------------------------------------
# Topological order
# ---------------------------------------------------------------------------


def topo_order(records: dict[str, ManifestRecord]) -> list[str]:
    """Deterministic load order honoring `load_order` then `priority` as
    tiebreakers. Within equal keys, falls back to alphabetical `id`.

    Mods involved in unresolved cycles are SKIPPED. Disabled mods are
    omitted. Missing-dep edges are simply ignored at sort time (the
    issue is already reported by `validate_graph`).
    """
    primary: dict[str, ManifestRecord] = {}
    for rec in records.values():
        primary.setdefault(rec.id, rec)
    enabled_ids = {mid for mid, r in primary.items() if r.enabled}

    # Drop nodes participating in any cycle (transitively).
    cyclic: set[str] = set()
    for cyc in _find_cycles(primary, enabled_ids):
        cyclic.update(cyc)
    nodes = enabled_ids - cyclic

    # Build adjacency (only present, enabled, non-cyclic edges).
    in_deg: dict[str, int] = {n: 0 for n in nodes}
    succs: dict[str, list[str]] = {n: [] for n in nodes}
    for n in nodes:
        rec = primary[n]
        for spec in rec.requires:
            name, _ = split_dep(spec)
            if name in nodes:
                # requires edge: name must come before n.
                succs[name].append(n)
                in_deg[n] += 1

    # Kahn's algorithm with deterministic tie-break by sort key.
    def sort_key(mid: str) -> tuple[int, int, str]:
        r = primary[mid]
        return (r.load_order, -r.priority, r.id)

    ready = sorted([n for n, d in in_deg.items() if d == 0], key=sort_key)
    out: list[str] = []
    while ready:
        cur = ready.pop(0)
        out.append(cur)
        for s in succs[cur]:
            in_deg[s] -= 1
            if in_deg[s] == 0:
                ready.append(s)
        ready.sort(key=sort_key)
    return out


# ---------------------------------------------------------------------------
# Pretty output for `doctor`
# ---------------------------------------------------------------------------


# Plain ANSI codes. No dependency on any color helper. If RSMM grows
# one, swap the constants below in one place.
_C_RED    = "\033[31m"
_C_YELLOW = "\033[33m"
_C_CYAN   = "\033[36m"
_C_BOLD   = "\033[1m"
_C_RESET  = "\033[0m"

_LABEL = {
    "error": ("ERROR", _C_RED),
    "warn":  ("WARN ", _C_YELLOW),
    "info":  ("INFO ", _C_CYAN),
}


def format_issues(issues: Iterable[GraphIssue], *, color: bool = True) -> str:
    """One-line-per-issue render, severity-grouped. Empty when no issues."""
    items = list(issues)
    if not items:
        return ""
    # Sort: error first, then warn, then info. Stable on (code, mods).
    order = {"error": 0, "warn": 1, "info": 2}
    items.sort(key=lambda i: (order.get(i.severity, 9), i.code, i.mods))

    lines: list[str] = []
    for it in items:
        tag, col = _LABEL.get(it.severity, ("?    ", ""))
        if color:
            head = f"{col}{_C_BOLD}[{tag.strip()}]{_C_RESET}"
        else:
            head = f"[{tag.strip()}]"
        lines.append(f"  {head} {it.code:<17} {it.message}")
        if it.fix:
            lines.append(f"            fix: {it.fix}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Convenience: one-shot check used by `doctor` / `apply` wiring.
# ---------------------------------------------------------------------------


def has_blocking(issues: Iterable[GraphIssue]) -> bool:
    """True if any issue has severity == 'error'. Used by `apply` to refuse."""
    return any(i.severity == "error" for i in issues)
