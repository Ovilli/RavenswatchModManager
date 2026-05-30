"""Schema-handler contract for cooked-payload codecs.

Each concrete handler maps ONE cooked class name (e.g. `oCGeometry`,
`oCTexture`) to a source-format pair (e.g. glTF, DDS). Handlers are
section-payload-level — the cooked container around them is handled
generically by `rsmm.engine.cooked`.

The full pipeline for a mod author is:

    source-file -> handler.encode(bytes) -> payload bytes
    payload bytes -> wrapped in cooked container by rsmm.engine.cooked.emit
    cooked bytes -> placed under DarkTalesResources/_Cooking/<encoded> by apply

And inverse for inspection / extraction.
"""

from __future__ import annotations

from dataclasses import dataclass


class NotReversedError(NotImplementedError):
    """Raised when a class is known but its schema is not yet documented.

    Carries the class name + a pointer to the RE notes so the caller can
    surface a useful message to the user.
    """

    def __init__(self, class_name: str, status: str = "not yet reversed") -> None:
        super().__init__(
            f"{class_name}: {status}. See docs/RE_NOTES.md for progress."
        )
        self.class_name = class_name


@dataclass
class SchemaHandler:
    """Base class. Subclasses set `class_name` + `source_ext` and override
    `decode`/`encode`. Default behavior raises NotReversedError so partial
    registration still produces useful errors instead of silent corruption.

    A handler is *registered* via `cooked_schemas.register(handler)`; lookup
    is by `class_name`. There is no fallback chain — if a class is registered
    but its handler raises NotReversedError, the CLI surfaces that error
    rather than guessing.
    """

    class_name: str
    source_ext: str           # canonical source-format extension, e.g. "gltf"
    decoded: bool = False     # True once `decode` produces real output
    encoded: bool = False     # True once `encode` produces real output

    def decode(self, payload: bytes) -> bytes:
        raise NotReversedError(self.class_name, "decode not implemented")

    def encode(self, source: bytes) -> bytes:
        raise NotReversedError(self.class_name, "encode not implemented")


class RawHandler(SchemaHandler):
    """Fallback for classes with no registered schema. Round-trips raw bytes
    so the container can still be inspected / repacked without per-class
    knowledge. Useful for byte-replace mods.
    """

    def __init__(self, class_name: str) -> None:
        super().__init__(class_name=class_name, source_ext="bin",
                         decoded=True, encoded=True)

    def decode(self, payload: bytes) -> bytes:
        return payload

    def encode(self, source: bytes) -> bytes:
        return source
