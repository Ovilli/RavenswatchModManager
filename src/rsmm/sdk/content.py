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
         "game_mode", "reward", "melody", "poi", "mesh", "tilegen", "shop")

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
    "item": "confirmed",      # mode="clone" verified in compendium + drops (2026-06-02).
                              # mode="ban" (dropping vanilla entries from the same
                              # LiveOps MO vector) is the exact inverse of that proven
                              # write and is refused at emit for an id the corpus does
                              # not have, but is NOT yet in-game proven. Rating stays
                              # confirmed because downgrading it would newly require
                              # experimental=true from every working clone mod.
    "talent": "confirmed",    # plain in-place magnitude override, tested
    "enemy": "confirmed",     # mode="override" PROVEN in game 2026-08-28 (entity_ref is what
                              # the camp instantiates; cross_biome pool repoint places
                              # foreign-chapter creatures). mode="clone" PROVEN 2026-09-24: a
                              # Gnoll clone with a Mud Crab body spawned in Storm Island gnoll
                              # camps once its `power` (cost) stayed within the camp budget.
    "hero": "experimental",   # ROSTER PROVEN IN GAME 2026-09-24: a Piper clone (herodef + own
                              # cache + versiondef hero-vector entry) showed as a 13th hero on
                              # the select screen. Not yet proven: playing a run AS the clone
                              # (index 12 has no unlock bit or per-hero save data).
    "map": "experimental",    # clone + chapter resref PROVEN IN GAME 2026-09-19 (chapter 0
                              # resolved to the clone and the run started in it); the clone
                              # still generates from the base's pool (tilegen backref) and
                              # `tribe` showed no effect
    "skill": "confirmed",     # relabel PROVEN IN GAME 2026-09-18 (Aladdin's Attack Dive read
                              # "TEST Meteor" in the Skill Menu and on the card). It is the only
                              # mode emitted: repoint was playtested inert (2026-09-12) and clone
                              # crashed the game (2026-09-11), so both are refused.
    "boss": "confirmed",      # boss SWAP, PROVEN IN GAME 2026-09-19 (session 324f): with
                              # Boss_White_Lady -> Boss_Crab, activating the Dark Hills White Lady
                              # shrine raised its arena, spawned Boss_Crab, and paid out the
                              # shrine's reward when it died. Arenas select their boss by the
                              # per-boss FLAG and nothing else names the entity (corpus scan,
                              # re-asserted by a slow test); bosses failing that are refused.
    "modifier": "experimental",  # a cloned def REACHES THE CHALLENGE SCREEN (in game 2026-09-18,
                              # "TEST Double XP" row, after the text-bank fix); its effect in a run
                              # is unproven (rows ARE spawner-driven — m_oGameModifierUiSpawner)
    "game_mode": "confirmed", # PROVEN IN GAME: skipping (SeedRunsChapter3 [2,3], 2026-07-11) and a
                              # DESCENDING order ([1,0] played Storm Island then Dark Hills,
                              # 2026-09-19). Repeats are refused: [0,0,1] skipped the duplicate.
                              # Always an in-place override of All_Chapters.
    "reward": "confirmed",    # PROVEN IN GAME 2026-09-19 (Camp_Rewards_Dark_Hills_Update5): counts
                              # [3,3] placed exactly 3 astrolabs (vanilla 0..1) and a DreamCrystal
                              # ban placed 0 (vanilla 1..3), counted off the live scene. The
                              # 2026-07-12 "ban unreliable" result edited the plain
                              # Camp_Rewards_<Biome> defs too, which nothing references; emit now
                              # refuses those and names the _Update5 def the game rolls from.
    "mesh": "confirmed",      # in-place override of a shipped mesh: one cooked file, no new
                              # resource name, so nothing but the geometry cook is exercised.
                              # PROVEN IN-GAME TWICE, by both routes the cook has:
                              #   * 2026-09-13 — a mod-supplied .glb written over a shipped
                              #     mesh's own cooked path rendered on the shipped entity that
                              #     places it, which is this kind exactly.
                              #   * 2026-09-17 — the same cook carrying `poi`'s `prop` drew
                              #     upright, textured, on a mod-owned entity in a generated
                              #     tile (see the `poi` note below).
                              # What the old rating was waiting on was a sighting, not a
                              # missing mechanism: there is no registration step to get wrong
                              # here — every entity, material, level, tile and resource cache
                              # keeps referring to the same resource name.
                              # ⚠ Still author-beware, and neither is a confidence problem:
                              # the override is GLOBAL (every other tile using that mesh
                              # changes too), and a CHARACTER replacement needs the right
                              # `transform.skin` or the model is shredded on the first
                              # animation frame (`rsmm.sdk.kinds.meshes` documents the three).
    "poi": "confirmed",       # PROVEN END TO END IN-GAME 2026-09-17, every link of the chain
                              # on a MOD-OWNED entity: the tile generates (four copies in one
                              # chapter, reported by R.poi.placed), the mod's own mesh and
                              # textures render upright, its minimap icon draws, the hold
                              # prompt appears on the prop, and the full interaction protocol
                              # runs -- validate -> request -> local_success -> success, with
                              # `canceled` on an early release. A mod can also tell ITS OWN
                              # POI from every chest in the run: `ev.pos` vs the placements
                              # R.poi.placed recorded matched at 2.0-3.6 units, repeatably.
                              # What each earlier rating was waiting on, and why it is settled:
                              #   * "a mod-added tiledef has never been observed placed" --
                              #     measured 2026-09-04 off the spawner's own placed set
                              #     (TileSpawn_PlaceTiles), both tiles instantiated.
                              #   * "a level cannot reference a mod-owned ENTITY" -- DISPROVED
                              #     2026-09-11: every asset in the additive chain, the mod's
                              #     own entity included, is requested and resolved. The old
                              #     note claiming otherwise, and that a POI needs a donor that
                              #     already places a marker-bearing entity, was wrong.
                              #   * the orphan bug that made appended objects inert -- fixed
                              #     2026-09-08 (_object_vector) and confirmed in-game.
                              # ⚠ Two things that are NOT limitations but do surprise authors:
                              # a pool entry can be placed SEVERAL times per map (copies=1 gave
                              # four), and this works on a `SceneryObjects_*` host, so the
                              # "scenery is never interactive" corpus rule describes shipped
                              # content rather than an engine gate.
    "tilegen": "confirmed",   # PROVEN IN GAME 2026-09-24: Camp count 2 + no 40x40/64x64 fill
                              # gave exactly 2 recipe camps (was 8-9) and left the spare slots
                              # empty. Camps have THREE sources (TileSpawn_PlaceTiles): the kind
                              # pass (count), the footprint-group FILL pass, and tile distance
                              # constraints (a story tile like Wood_House forces 3 Treant camps).
                              # The earlier "count is ignored" reading was the fill pass.
    "shop": "confirmed",      # Sandman shop prices + offer generators, overridden in place.
                              # Field meaning is read off the live exe's generator (0x1402d9280),
                              # quality roll and price function (0x1402d4200), and every edit
                              # round-trips byte-for-byte. PROVEN IN GAME 2026-09-13
                              # (sandman-shop-test): edited prices of 1 were what the shop
                              # charged. Minor must roll >= 2 items or opening the shop
                              # divides by zero (enforced by shops._check_rollable).
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
        # A field the kind does not read is a typo, and a typo here used to be
        # a mod that installs and silently does nothing.
        from .manifest_spec import content_fields, describe_unknown, unknown_keys
        allowed = content_fields(kind)
        if allowed is not None:
            bad = unknown_keys(fields, allowed)
            if bad:
                raise ContentError(
                    f"{kind} {id}: unknown field(s) {describe_unknown(bad)}; "
                    f"{kind} accepts: {', '.join(sorted(allowed - {'kind', 'id'}))}"
                )
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
    "mesh": "meshes",
    "poi": "poi",
    "tilegen": "tilegen",
    "shop": "shops",
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


