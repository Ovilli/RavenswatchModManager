"""``rsmm.sdk.engine`` — authoring-time view of the engine symbol map.

Lets SDK code, tooling, and tests reference engine functions / globals /
events by stable semantic name (``"Resource_LookupByPath"``,
``"level_up"``) instead of raw ``FUN_xxxxxxxx`` addresses or magic numbers.

This is introspection only. Actually *calling* an engine function happens
at runtime in the loader — Lua ``R.engine.call(name, ...)`` or C++
``engine::Name()``. Here you discover what exists, validate a name before
a mod ships, or resolve a preferred-base address for docs/diagnostics.

The canonical data is ``data/symbols.json`` (see ``rsmm symbols``).
"""

from __future__ import annotations

from rsmm.engine.symbols import Symbol, SymbolMap, load_symbol_map

#: Events the loader always emits, independent of the gameplay-event catalog.
BUILTIN_EVENTS: tuple[str, ...] = ("setup", "ready", "tick", "exit")


def _map() -> SymbolMap:
    return load_symbol_map()


def symbols() -> list[Symbol]:
    """Every symbol in the map."""
    return list(_map().symbols)


def symbol(name: str) -> Symbol | None:
    """The symbol with this semantic name, or ``None``."""
    return _map().by_name(name)


def callables() -> list[str]:
    """Names with a typed accessor (cabi + byte pattern) — the functions a
    mod can call via ``R.engine.call`` / C++ ``engine::``."""
    return sorted(s.name for s in _map().callable_symbols)


def events() -> list[str]:
    """Lua event names a mod can subscribe to with ``R.on(name, cb)`` —
    built-in lifecycle events plus the RE'd gameplay events."""
    gameplay = {s.lua_event for s in _map().events if s.lua_event}
    return sorted(set(BUILTIN_EVENTS) | gameplay)


def is_event(name: str) -> bool:
    return name in events()


def is_callable(name: str) -> bool:
    s = symbol(name)
    return bool(s and s.callable)


def resolve(name: str) -> int:
    """Preferred-base address of a symbol. Raises ``KeyError`` if unknown.

    Note: this is the canonical (link-time) address, not the live runtime
    one — the loader re-resolves pattern-backed symbols at injection time.
    """
    m = _map()
    s = m.by_name(name)
    if s is None:
        raise KeyError(f"no such engine symbol: {name!r}")
    return s.preferred_addr(m.preferred_base)
