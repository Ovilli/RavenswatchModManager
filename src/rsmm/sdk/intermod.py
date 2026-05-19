"""Inter-mod API registry — Python-host mirror of the Lua-side R.api.

A mod exposes a table of callables via `expose(mod_id, table, version)`.
Another mod consumes it via `require(name, version_spec)` and gets a
proxy that:

  * `try/except`s every call so a producer crash can't bring down the
    consumer (errors are logged + re-raised as `InterModError`),
  * semver-checks once at require-time,
  * is read-only — no attribute mutation through the proxy.

This is the authoritative Python implementation. The Lua side mirrors
the same shape for in-process mods; host-side scripts (Python mods,
tests) use this module directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .api import satisfies, sdk_export


class InterModError(RuntimeError):
    """Raised when a consumed API call fails or is missing."""


@dataclass
class _Entry:
    mod_id: str
    version: str
    table: dict[str, Callable]


@dataclass
class InterModRegistry:
    _by_name: dict[str, _Entry] = field(default_factory=dict)

    @sdk_export("InterModRegistry.expose")
    def expose(self, mod_id: str, table: dict[str, Callable],
               version: str = "0.0.0", *, api_name: str | None = None) -> None:
        """Publish a table under `api_name` (defaults to `mod_id`)."""
        name = api_name or mod_id
        if name in self._by_name:
            raise InterModError(f"API name already taken: {name!r}")
        if not isinstance(table, dict) or not all(callable(v) for v in table.values()):
            raise InterModError(f"{mod_id}: expose() needs a dict of callables")
        self._by_name[name] = _Entry(mod_id=mod_id, version=version, table=dict(table))

    @sdk_export("InterModRegistry.require")
    def require(self, name: str, version_spec: str = "") -> "InterModProxy":
        entry = self._by_name.get(name)
        if entry is None:
            raise InterModError(f"API not found: {name!r}")
        if version_spec and not satisfies(entry.version, version_spec):
            raise InterModError(
                f"{name!r} {entry.version} does not satisfy {version_spec!r}"
            )
        return InterModProxy(entry)

    def has(self, name: str) -> bool:
        return name in self._by_name

    def list(self) -> dict[str, tuple[str, str]]:
        """`{api_name: (mod_id, version)}` snapshot."""
        return {n: (e.mod_id, e.version) for n, e in self._by_name.items()}


class InterModProxy:
    """Read-only proxy around an exposed table. Catches producer errors."""

    __slots__ = ("_entry",)

    def __init__(self, entry: _Entry):
        object.__setattr__(self, "_entry", entry)

    def __getattr__(self, key: str) -> Callable:
        e: _Entry = object.__getattribute__(self, "_entry")
        if key not in e.table:
            raise InterModError(f"{e.mod_id!r} does not expose {key!r}")
        fn = e.table[key]

        def safe_call(*a, **kw) -> Any:
            try:
                return fn(*a, **kw)
            except Exception as exc:
                raise InterModError(
                    f"{e.mod_id}.{key}() raised: {exc!s}"
                ) from exc

        return safe_call

    def __setattr__(self, *_a, **_kw) -> None:
        raise InterModError("InterModProxy is read-only")
