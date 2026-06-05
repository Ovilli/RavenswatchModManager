"""Symbol map loader + resolver.

``data/symbols.json`` is the canonical, human-authored map from semantic
names (``MagicalObject_SpawnAllObjects``) to engine functions/globals.
It is the source of truth — Ghidra names, the loader C++ header, and the
Python SDK constants are all generated from it (see ``rsmm symbols gen``).

Resolution forms, in order of version-resilience:

* ``raw``   — ``"FUN_<addr>"`` whose byte pattern lives in
  ``data/function_patterns.json``; the address survives game updates
  because the loader re-scans for the pattern (``fn_resolver.h``).
* ``anchor``— an inlined routine reached as ``parent_pattern + offset``;
  the parent's ``raw`` carries the pattern.
* ``va``    — a base-relative absolute (data globals have no code
  pattern; the loader rebases by image-base delta).

This module is stdlib-only so it is importable from the frozen sidecar.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from .paths import REPO_ROOT

SYMBOLS_PATH = REPO_ROOT / "data" / "symbols.json"
PATTERNS_PATH = REPO_ROOT / "data" / "function_patterns.json"

VALID_KINDS = {"function", "data"}
VALID_STATUS = {"ok", "va", "unverified"}


def _parse_hex(value: str) -> int:
    return int(str(value), 16)


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    category: str
    note: str = ""
    signature: str | None = None
    raw: str | None = None
    anchor: dict[str, str] | None = None
    va: str | None = None
    status: str = "unverified"
    refs: tuple[str, ...] = field(default_factory=tuple)

    @property
    def pattern_name(self) -> str | None:
        """The ``FUN_<addr>`` whose byte pattern resolves this symbol, if any."""
        if self.raw:
            return self.raw
        if self.anchor and self.anchor.get("raw"):
            return self.anchor["raw"]
        return None

    def preferred_addr(self, preferred_base: int) -> int:
        """Address at the canonical preferred base (``0x140000000``).

        For ``raw``/``va`` this is the literal address; for ``anchor`` it is
        ``parent + offset``. ``preferred_base`` is accepted for symmetry with
        the runtime resolver but only used to validate ``va`` is sane.
        """
        if self.raw:
            return _parse_hex(self.raw.split("_", 1)[1])
        if self.anchor:
            return _parse_hex(self.anchor["raw"].split("_", 1)[1]) + _parse_hex(
                self.anchor["offset"]
            )
        if self.va:
            return _parse_hex(self.va)
        raise ValueError(f"symbol {self.name!r} has no raw/anchor/va")


@dataclass(frozen=True)
class SymbolMap:
    preferred_base: int
    symbols: tuple[Symbol, ...]

    def by_name(self, name: str) -> Symbol | None:
        for s in self.symbols:
            if s.name == name:
                return s
        return None

    def by_category(self, category: str) -> list[Symbol]:
        return [s for s in self.symbols if s.category == category]

    @property
    def categories(self) -> list[str]:
        return sorted({s.category for s in self.symbols})


def _coerce(entry: dict[str, Any]) -> Symbol:
    return Symbol(
        name=entry["name"],
        kind=entry["kind"],
        category=entry.get("category", "misc"),
        note=entry.get("note", ""),
        signature=entry.get("signature"),
        raw=entry.get("raw"),
        anchor=entry.get("anchor"),
        va=entry.get("va"),
        status=entry.get("status", "unverified"),
        refs=tuple(entry.get("refs", ())),
    )


@lru_cache(maxsize=1)
def load_symbol_map(path: Path | None = None) -> SymbolMap:
    p = path or SYMBOLS_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    return SymbolMap(
        preferred_base=_parse_hex(data.get("preferred_base", "0x140000000")),
        symbols=tuple(_coerce(e) for e in data["symbols"]),
    )


@lru_cache(maxsize=1)
def _pattern_names() -> frozenset[str]:
    """Names present in ``function_patterns.json`` (the version-resilient set)."""
    if not PATTERNS_PATH.is_file():
        return frozenset()
    return frozenset(e["name"] for e in json.loads(PATTERNS_PATH.read_text(encoding="utf-8")))


def validate(smap: SymbolMap | None = None) -> list[str]:
    """Return a list of problems with the symbol map (empty == valid).

    Checks: unique names, valid kind/status, exactly one of raw/anchor/va,
    anchor shape, and that any ``status="ok"`` symbol's pattern actually
    exists in ``function_patterns.json`` (so "ok" never lies).
    """
    smap = smap or load_symbol_map()
    problems: list[str] = []
    seen: set[str] = set()
    pats = _pattern_names()
    for s in smap.symbols:
        if s.name in seen:
            problems.append(f"{s.name}: duplicate name")
        seen.add(s.name)
        if s.kind not in VALID_KINDS:
            problems.append(f"{s.name}: bad kind {s.kind!r}")
        if s.status not in VALID_STATUS:
            problems.append(f"{s.name}: bad status {s.status!r}")
        forms = [bool(s.raw), bool(s.anchor), bool(s.va)]
        if sum(forms) != 1:
            problems.append(f"{s.name}: need exactly one of raw/anchor/va")
        if s.anchor and not (s.anchor.get("raw") and s.anchor.get("offset")):
            problems.append(f"{s.name}: anchor needs raw+offset")
        if s.status == "ok":
            pn = s.pattern_name
            if not pn:
                problems.append(f"{s.name}: status=ok requires raw or anchor")
            elif pats and pn not in pats:
                problems.append(
                    f"{s.name}: status=ok but pattern {pn} not in function_patterns.json"
                )
    return problems
