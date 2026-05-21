"""Plugin discovery via Python entry-points (PEP 621).

Third-party packages opt in by declaring:

    [project.entry-points."rsmm.plugins"]
    my_pack = "my_pack.entry:register"

`register(api)` is called once with the `rsmm.sdk.api.v1` namespace. The
plugin can:

  * declare new content kinds      api.content.register_kind(name, impl)
  * add CLI subcommands            api.cli.register(name, fn)
  * publish Lua-side files         api.lua.publish(filename, source)
  * register repo indices          api.repo.register(url)

A plugin that raises during `register` is skipped + logged; it does not
abort SDK startup.
"""

from __future__ import annotations

import importlib.metadata as md
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

ENTRY_POINT_GROUP = "rsmm.plugins"


@dataclass
class PluginInfo:
    name: str
    target: str            # "module:attr"
    error: str | None = None


def discover_plugins(api: Any) -> tuple[list[PluginInfo], list[PluginInfo]]:
    """Load every registered plugin. Return (loaded, skipped)."""
    loaded: list[PluginInfo] = []
    skipped: list[PluginInfo] = []
    try:
        entries = md.entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:
        # Python <3.10 fallback shape; we require 3.11+ but keep it sturdy.
        entries = md.entry_points().get(ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined]
    for ep in entries:
        info = PluginInfo(name=ep.name, target=str(ep.value))
        try:
            fn: Callable[[Any], None] = ep.load()
            fn(api)
            loaded.append(info)
        except Exception as exc:  # noqa: BLE001 — plugin code is untrusted
            info.error = f"{type(exc).__name__}: {exc}"
            skipped.append(info)
    return loaded, skipped
