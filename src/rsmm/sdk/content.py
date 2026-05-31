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


@dataclass(frozen=True)
class ContentRef:
    """Typed handle to registered content — the rsmm analog of Forge's
    ``RegistryObject<T>`` / Fabric's registry holder.

    Returned by every typed registration (``m.item(...)`` etc.) and by
    :meth:`ContentRegistry.register`. Pass a ref anywhere another content
    id is expected (a drop table, a recipe input, a hero ability) — the
    registry derefs it to the raw game id at register time, so refs survive
    even if the id-naming scheme changes later.

    Stringifies to the namespaced id ``<mod>:<id>`` (à la Minecraft's
    ``ResourceLocation``); :attr:`resource` is the raw game resource name.
    """

    kind: str
    id: str
    mod_id: str

    def __str__(self) -> str:
        return f"{self.mod_id}:{self.id}"

    @property
    def resource(self) -> str:
        """Raw game resource name (what the cooked asset is keyed on)."""
        return self.id


def _deref(value):
    """Resolve ContentRefs (and refs nested in lists/dicts/tuples) to raw
    ids so a ref can be passed wherever a field expects another content id."""
    if isinstance(value, ContentRef):
        return value.resource
    if isinstance(value, list):
        return [_deref(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_deref(v) for v in value)
    if isinstance(value, dict):
        return {k: _deref(v) for k, v in value.items()}
    return value


@dataclass
class ContentRegistry:
    """Mod-scoped registry. One per mod-build pass."""

    mod_id: str
    defs: list[ContentDef] = field(default_factory=list)

    @sdk_export("ContentRegistry.register")
    def register(self, kind: str, *, id: str, schema_version: int = 1,
                 **fields) -> ContentRef:
        if kind not in KINDS:
            raise ContentError(
                f"unknown content kind {kind!r}; supported: {', '.join(KINDS)}"
            )
        if not id or not isinstance(id, str):
            raise ContentError(f"{kind}: id must be a non-empty string")
        if any(d.kind == kind and d.id == id for d in self.defs):
            raise ContentError(f"{kind}: duplicate id {id!r}")
        d = ContentDef(kind=kind, id=id, fields=_deref(fields),
                       schema_version=schema_version)
        self.defs.append(d)
        return ContentRef(kind=kind, id=id, mod_id=self.mod_id)

    def emit(self, out_dir: Path) -> list[Path]:
        """Materialize every registered def into `out_dir`. Returns written paths."""
        written: list[Path] = []
        for d in self.defs:
            mod = _load_kind(d.kind)
            try:
                paths = mod.emit(self.mod_id, d, out_dir)
            except AttributeError as e:
                raise ContentError(
                    f"kind {d.kind!r} module has no emit(): {e}"
                ) from e
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


