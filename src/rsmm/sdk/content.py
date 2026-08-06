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

KINDS = ("item", "enemy", "boss", "map", "hero", "talent", "skill", "modifier",
         "game_mode", "reward", "melody")

#: Per-kind honesty rating — how much we trust the bytes this kind emits.
#:
#: * ``confirmed`` — verified in-game end-to-end; safe to ship.
#: * ``experimental`` — codecs round-trip and emit succeeds, but the
#:   in-game *apply/runtime* path is unproven (e.g. spawn selector or
#:   roster detour unconfirmed). May load but not appear/function.
#: * ``guess`` — byte layout is an educated guess from declaration order;
#:   the game may reject or crash. Do not ship without RE confirmation.
#:
#: A mod that registers any non-``confirmed`` kind must opt in via
#: ``sdk.Mod(..., experimental=True)`` (and the manifest records it), so
#: nobody ships speculative content believing it works. ``rsmm lint``
#: enforces this. Keep this table honest — it is the single source of
#: truth consumed by the SDK, the linter, and ``docs/MODDING.md``.
KIND_CONFIDENCE: dict[str, str] = {
    "item": "confirmed",      # verified in compendium + drops (2026-06-02)
    "talent": "confirmed",    # plain in-place magnitude override, tested
    "enemy": "experimental",  # codecs round-trip; spawn-apply step unproven
    "hero": "experimental",   # clones, but roster detour + library unproven
    "map": "experimental",    # emit only; no in-game load proof
    "skill": "guess",         # herodef skill-row clone/repoint; in-game hero-page load unproven
    "boss": "guess",          # BossTimer picker offsets deserializer-verified 2026-07-05, but emit
                              # still stages manifests (_pending_bosses), no cooked-asset output yet
    "modifier": "guess",      # gamemodifierdef clone loads; UI-slot appearance unproven (cap #16;
                              # rows ARE spawner-driven per Ghidra — m_oGameModifierUiSpawner)
    "game_mode": "experimental",  # chapter vector deserializer-verified 2026-07-05 (poly-ptr
                              # vector @def+0x290, ordered refs); in-game honoring unproven
    "reward": "experimental", # codec byte-verified, but 2026-07-12 playtest: emptying a
                              # reward_types row did NOT stop chests. Roll FUN_1401e9800 has 2
                              # blocks — a count-gated reward_types path (edit honoured) AND a
                              # guaranteed block on a different (context+0xa8) def that bypasses
                              # counts. Ban unreliable; needs a runtime def-dump to pin the
                              # def/field. See docs/_re/kinds/rewards.md
    "melody": "guess",        # all 12 retail melodydefs round-trip byte-for-byte and every
                              # mined exclusion string is an exact GameModifier stem, but
                              # neither lever (effect repoint, exclusion list) has been
                              # confirmed in-game. See docs/_re/kinds/melodies.md
}

CONFIDENCE_LEVELS = ("confirmed", "experimental", "guess")


def kind_confidence(kind: str) -> str:
    """Return the honesty rating for ``kind`` (see :data:`KIND_CONFIDENCE`).

    Unknown kinds are treated as ``guess`` — the safe default for anything
    not explicitly vetted."""
    return KIND_CONFIDENCE.get(kind, "guess")


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
    #: Author opted into unverified kinds via ``sdk.Mod(experimental=True)``.
    experimental: bool = False

    @sdk_export("ContentRegistry.register")
    def register(self, kind: str, *, id: str, schema_version: int = 1,
                 **fields) -> ContentRef:
        """Register a content definition of ``kind`` and return its :class:`ContentRef`.

        The low-level primitive behind :meth:`Mod.item` / :meth:`Mod.enemy`
        / etc. ``kind`` must be a known builder (``item``, ``enemy``,
        ``boss``, ``hero``, ``map``, …); non-``confirmed`` kinds require the
        mod to opt in with ``experimental=True``. ``id`` must be unique
        within the mod for that kind. Extra ``**fields`` are passed to the
        kind builder.
        """
        if kind not in KINDS:
            raise ContentError(
                f"unknown content kind {kind!r}; supported: {', '.join(KINDS)}"
            )
        conf = kind_confidence(kind)
        if conf != "confirmed" and not self.experimental:
            raise ContentError(
                f"kind {kind!r} is {conf!r}: its emitted bytes are not verified "
                "in-game and may not appear or may crash. To use it anyway, "
                "opt in with sdk.Mod(..., experimental=True). See "
                "docs/MODDING.md 'Content kinds & confidence'."
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
            # Check for emit() instead of catching AttributeError around the
            # call: an AttributeError raised INSIDE a builder (a typo, a None
            # where a def was expected) is a bug in that builder, and
            # reporting it as "this kind has no emit()" sent authors hunting
            # for a missing function that was there all along.
            emit = getattr(mod, "emit", None)
            if not callable(emit):
                raise ContentError(f"kind {d.kind!r} module has no emit()")
            written.extend(emit(self.mod_id, d, out_dir))
        return written


_KIND_MODULES = {
    "item": "items",
    "enemy": "enemies",
    "boss": "bosses",
    "map": "maps",
    "hero": "heros",
    "talent": "talents",
    "skill": "skills",
    "modifier": "modifiers",
    "game_mode": "game_modes",
    "melody": "melodies",
}

def _load_kind(kind: str):
    """Lazy-import to keep startup cheap and let plugins override kinds."""
    mod_name = _KIND_MODULES.get(kind, f"{kind}s")
    target = f"rsmm.sdk.kinds.{mod_name}"
    try:
        return import_module(target)
    except ModuleNotFoundError as e:
        # Only "the builder module itself is absent" means there is no
        # builder. A ModuleNotFoundError from an import INSIDE the builder
        # is a broken dependency in that builder, and swallowing it into
        # "no builder for kind" hid the real missing module.
        if e.name == target or (e.name and target.startswith(f"{e.name}.")):
            raise ContentError(f"no builder for kind {kind!r}: {e}") from e
        raise


