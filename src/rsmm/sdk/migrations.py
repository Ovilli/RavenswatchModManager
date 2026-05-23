"""Schema migration runner — bumps ContentDef payloads between schema
versions when a kind's binary format changes.

A migration lives at:

    src/rsmm/sdk/kinds/<kind>/migrations/<from>_to_<to>.py

with a top-level `def migrate(defn_fields: dict) -> dict:` that returns
the rewritten fields. The runner chains them: 1->2->3 etc.

Used by the applier on build to bring an older mod's `[[content]]`
block up to the current `schema_version`. Lets mods stay shipped against
old SDK versions and continue working after RSMM upgrades.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

MIGR_RE = re.compile(r"^(\d+)_to_(\d+)\.py$")
_KIND_RE = re.compile(r"^[a-z]+$")

CURRENT_SCHEMA: dict[str, int] = {
    "item":  1,
    "enemy": 1,
    "boss":  1,
    "map":   1,
    "hero":  1,
}


def chain(kind: str, from_v: int, to_v: int) -> list[int]:
    """Return [from_v, ..., to_v] if a valid migration chain exists, else []."""
    if not _KIND_RE.match(kind):
        raise ValueError(f"invalid kind: {kind!r}")
    if from_v > to_v:
        return []
    if from_v == to_v:
        return [from_v]
    path = Path(__file__).parent / "kinds" / kind / "migrations"
    if not path.is_dir():
        return [] if from_v != to_v else [from_v]
    available: dict[int, int] = {}
    for f in path.glob("*.py"):
        m = MIGR_RE.match(f.name)
        if m:
            available[int(m.group(1))] = int(m.group(2))
    cur = from_v
    out = [cur]
    seen: set[int] = {cur}
    while cur != to_v:
        nxt = available.get(cur)
        if nxt is None:
            return []
        if nxt in seen:
            raise RuntimeError(
                f"cycle in {kind} migrations at v{cur} -> v{nxt}"
            )
        seen.add(nxt)
        out.append(nxt)
        cur = nxt
    return out


def migrate(kind: str, defn_fields: dict[str, Any],
            from_v: int, to_v: int | None = None) -> dict[str, Any]:
    """Migrate `defn_fields` forward in-place-style. Returns new dict."""
    target = to_v if to_v is not None else CURRENT_SCHEMA.get(kind, from_v)
    steps = chain(kind, from_v, target)
    if not steps:
        raise RuntimeError(
            f"no migration chain for {kind} from v{from_v} to v{target}"
        )
    cur = dict(defn_fields)
    for a, b in zip(steps, steps[1:], strict=False):
        mod = importlib.import_module(
            f"rsmm.sdk.kinds.{kind}.migrations.{a}_to_{b}"
        )
        if not hasattr(mod, "migrate"):
            raise RuntimeError(
                f"migration {kind}.{a}_to_{b} has no migrate() function"
            )
        cur = mod.migrate(cur)
    return cur
