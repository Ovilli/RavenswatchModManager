"""Content kinds registry — façade over per-kind builders.

A mod registers content via `ContentRegistry.register("item", id=..., ...)`
which delegates to the `kinds/<kind>.py` implementation. Each kind owns
its own template + field-patcher + emit step.

Kinds that aren't fully schema-mined yet (bosses, maps, heroes at v3.0)
register their builder but fail with a clear `SchemaNotMined` error on
emit, so authors see exactly which class needs RE work next.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path

from .api import sdk_export

KINDS = ("item", "enemy", "boss", "map", "hero")


class ContentError(ValueError):
    pass


class SchemaNotMined(NotImplementedError):
    """Raised when a kind's binary schema isn't extracted yet."""


@dataclass
class ContentDef:
    kind: str
    id: str
    fields: dict
    schema_version: int = 1


@dataclass
class ContentRegistry:
    """Mod-scoped registry. One per mod-build pass."""

    mod_id: str
    defs: list[ContentDef] = field(default_factory=list)

    @sdk_export("ContentRegistry.register")
    def register(self, kind: str, *, id: str, schema_version: int = 1,
                 **fields) -> ContentDef:
        if kind not in KINDS:
            raise ContentError(
                f"unknown content kind {kind!r}; supported: {', '.join(KINDS)}"
            )
        if not id or not isinstance(id, str):
            raise ContentError(f"{kind}: id must be a non-empty string")
        d = ContentDef(kind=kind, id=id, fields=fields, schema_version=schema_version)
        self.defs.append(d)
        return d

    def emit(self, out_dir: Path) -> list[Path]:
        """Materialize every registered def into `out_dir`. Returns written paths."""
        written: list[Path] = []
        for d in self.defs:
            mod = _load_kind(d.kind)
            paths = mod.emit(self.mod_id, d, out_dir)
            written.extend(paths)
        return written


_KIND_MODULES = {
    "item": "items",
    "enemy": "enemies",
    "boss": "bosses",
    "map": "maps",
    "hero": "heros",
}

def _load_kind(kind: str):
    """Lazy-import to keep startup cheap and let plugins override kinds."""
    mod_name = _KIND_MODULES.get(kind, f"{kind}s")
    try:
        return import_module(f"rsmm.sdk.kinds.{mod_name}")
    except ModuleNotFoundError as e:
        raise ContentError(f"no builder for kind {kind!r}: {e}") from e


# --- third-party kind extension ---------------------------------------

_EXTRA_KINDS: dict[str, ContentKindImpl] = {}


class ContentKindImpl:
    """Minimal interface a plugin must implement to add a new kind."""

    name: str = ""

    def emit(self, mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
        raise NotImplementedError


@sdk_export("content.register_kind")
def register_kind(name: str, impl: ContentKindImpl) -> None:
    """Plugin entry-point hook: add a new content kind at runtime."""
    if name in KINDS or name in _EXTRA_KINDS:
        raise ContentError(f"kind {name!r} already registered")
    _EXTRA_KINDS[name] = impl
