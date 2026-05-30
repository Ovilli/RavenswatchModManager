"""Per-class cooked-payload schemas.

Each class that ships in a cooked container has its own Serialize() method in
Ravenswatch.exe. This package holds the reverse-engineered decoders/encoders
for the section payloads of those classes.

Container framing is handled by `rsmm.engine.cooked` (already byte-stable).
Schemas live here so the container codec stays format-agnostic and the per-
class work can land incrementally without touching it.

Schemas register themselves on import via `register(handler)`. Lookup happens
by the leaf class name reported in the cooked file's class table. Use
`get(class_name)` to dispatch; a missing class returns a `RawHandler` that
emits/consumes raw bytes (always works, no schema knowledge required).

Reverse-engineering progress lives in `docs/RE_NOTES.md` — read that for the
state of each schema. NotReversedError is the contract for "we know about this
class but haven't finished the schema yet".
"""

from __future__ import annotations

from .base import NotReversedError, RawHandler, SchemaHandler

_REGISTRY: dict[str, SchemaHandler] = {}


def register(handler: SchemaHandler) -> None:
    _REGISTRY[handler.class_name] = handler


def get(class_name: str) -> SchemaHandler:
    return _REGISTRY.get(class_name, RawHandler(class_name))


def known() -> list[str]:
    return sorted(_REGISTRY)


# Side-effect imports — each module registers on import.
from . import (  # noqa: E402,F401
    animation,
    asset_refs,
    definitions,
    entity_settings,
    geometry,
    global_values,
    material,
    mesh,
    meshbuffer,
    resource,
    skeleton,
    texture,
    vertex_layer,
)

__all__ = [
    "NotReversedError",
    "RawHandler",
    "SchemaHandler",
    "get",
    "known",
    "register",
]
