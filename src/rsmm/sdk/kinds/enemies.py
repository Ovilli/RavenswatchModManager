"""Enemy content builder — two modes.

``mode = "clone"`` (default) spawns a **custom** non-boss enemy into vanilla
camps by cloning a vanilla ``oCDtEnemyDefinition`` (UID ``0x176debb7``,
library ``0x1414118c0``, cooked ext ``*.enemydef.ot``) and re-emitting it
under a new id. :func:`emit` writes one cooked record into the mod's
``assets/`` tree at
``Definitions/Enemies/<id>.enemydef.ot.DtEnemyDefinition.gen``; the generic
``apply_mods.py`` new-asset path then registers it in ``UsedRscList.ot`` so
the engine loads it (mirrors the item pipeline — see
:mod:`rsmm.sdk.kinds.items`).

``mode = "override"`` rewrites **retail** enemy definitions in place, the way
the ``reward`` and ``melody`` kinds do: the emitted asset lands at the vanilla
decoded path and ``rsmm apply`` backs the original up and replaces it. It
exists to repoint what a whole population *is* — every Dark Hills monster
becomes a treant, or every biome's roster is randomised against itself —
without touching the selector, the tribes or the pools. See
:func:`_emit_override` for why that is the only edit in the chain that is
safe to make wholesale.

Spawn linkage is by data, not by roster patch. The camp tier selector builds
its candidate enemy list from the **tribe's runtime roster vector** at
``oCDtEnemyTribeDefinition+0x2b8`` (builder ``FUN_14032de90`` → Stage-3 filter
``FUN_1403194c0``); the filter only trims that list by tier/tag/weight. That
roster is **runtime-populated** — the cooked tribe file's own entry vector
lives at ``+0x2a0`` and ships empty in all 25 vanilla tribes, so patching the
cooked tribe is useless (wrong vector). A loaded enemy whose ``tribe_ref``
resolves is bucketed into its tribe's ``+0x2b8`` roster, so a clone that keeps
the base's tribe (and a pooled entity) is considered wherever the base spawns.
See ``docs/_re/kinds/enemies.md`` and the ``enemy-spawn-model`` RE note
(corrected 2026-06-08 — the older ``flag-list selector`` / ``tribe_patch``
models were both wrong).

Not yet patchable: HP / damage / on-screen name live on the visual
``oCEntitySettings`` referenced by ``entity_ref`` (``+0x298``), not on the
enemy def — a clone shares its base's stats and name until entity cloning
lands. The byte-level codec is :data:`rsmm.engine.cooked_schemas.definitions`
``oCDtEnemyDefinition`` (round-trips byte-stable).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ...engine import cooked
from ...engine import enemy_pools as EP
from ...engine import rsc_cache as RC
from ...engine.cooked_schemas import definitions as _defs
from ...engine.paths import DATA_DIR
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C

_log = logging.getLogger(__name__)

#: Where the vanilla enemy definitions live in-repo (one cooked `.gen` per
#: enemy id). The clone source for a custom enemy.
_ENEMY_DIR = DATA_DIR / "uncooked" / "Definitions" / "Enemies"
_ENEMY_GEN_SUFFIX = ".enemydef.ot.DtEnemyDefinition.gen"
#: Decoded asset path (forward-slash) the apply pipeline registers in
#: UsedRscList. The stem is the enemy's library identity.
_ENEMY_ASSET_SUBDIR = "Definitions/Enemies"

#: Where the vanilla tribe definitions live in-repo — the set a custom enemy's
#: ``tribe`` must name, or the runtime roster won't resolve it (it would load
#: but never spawn). See :func:`_known_tribes`.
_TRIBE_DIR = DATA_DIR / "uncooked" / "Definitions" / "EnemyTribes"

#: ``spawn_weight`` guardrails. The weighted camp-roster selection overflowed
#: and crashed the game at weight ``9999`` (enemy-spawn-model note). Vanilla
#: weights are single- to low-double-digit (e.g. ``3.0``). Refuse anything
#: extreme; warn on merely-high values that would dominate a camp.
SPAWN_WEIGHT_MAX: Final[float] = 1000.0
SPAWN_WEIGHT_WARN: Final[float] = 100.0


def _known_tribes() -> set[str]:
    """The vanilla tribe names a custom enemy may join (stems under
    ``data/uncooked/Definitions/EnemyTribes``). Empty if the corpus is absent
    (frozen builds that don't bundle it) — callers skip the check then."""
    if not _TRIBE_DIR.is_dir():
        return set()
    return {p.name.split(".", 1)[0] for p in _TRIBE_DIR.glob("*.enemytribedef.*")}


def _tribe_of_ref(ref_path: str) -> str | None:
    """Tribe name from a ``tribe_ref`` path, e.g.
    ``EnemyTribes\\Gnolls.enemytribedef.ot`` -> ``Gnolls``. None if blank."""
    tail = (ref_path or "").replace("/", "\\").split("\\")[-1]
    return tail.split(".", 1)[0] or None

# --------------------------------------------------------------------------- #
# Class registry constants — confirmed via FUN_140229990 and the live Ghidra
# session. Mirror the table in docs/_re/MOD_HOOKS.md.
# --------------------------------------------------------------------------- #

ENEMY_DEF_UID: Final[int] = 0x176DEBB7
ENEMY_DEF_SIZE: Final[int] = 0x350
ENEMY_DEF_LIBRARY: Final[int] = 0x1414118C0
ENEMY_DEF_RESOURCE_EXT: Final[str] = "*.enemydef.ot"

ENEMY_TRIBE_DEF_LIBRARY: Final[int] = 0x141411200
ENEMY_TRIBE_DEF_RESOURCE_EXT: Final[str] = "*.enemytribedef.ot"

ENEMY_CAMP_TIER_DEF_UID: Final[int] = 0x176E18F8
ENEMY_CAMP_TIER_DEF_SIZE: Final[int] = 0x2A0
ENEMY_CAMP_TIER_DEF_LIBRARY: Final[int] = 0x141411560

#: ctor `FUN_1401db800` writes this to every unresolved name slot. The
#: deserializer treats it as an empty-string sentinel. Re-exported from
#: :mod:`rsmm.sdk.kinds._common` for module-local readability.
EMPTY_STRING_SENTINEL: Final[int] = C.EMPTY_STRING_SENTINEL
UNRESOLVED_NAME_HASH: Final[int] = C.UNRESOLVED_NAME_HASH

#: Schema version of the JSON intermediate written by :func:`emit`. Bump
#: whenever any field below moves or its semantics change so the migrations
#: pipeline (`src/rsmm/sdk/migrations.py`) can rewrite older mods.
ENEMY_MANIFEST_SCHEMA_VERSION: Final[int] = 1


# --------------------------------------------------------------------------- #
# `oCDtEnemyDefinition` (size 0x350) field offsets. Confirmed against
# FUN_1401db800 (ctor), FUN_1401db9b0 (dtor), and FUN_14030b000 (Stage-3
# filter that reads several of these directly). See docs/_re/kinds/enemies.md
# for the full per-offset writeup.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EnemyDefOffsets:
    """Byte offsets into the `oCDtEnemyDefinition` instance."""

    vftable: int = 0x000
    # oCDtDefinition parent (display-name slot, used by oIResourceManager
    # for path-based lookup via library vftable slot 3).
    display_name_ptr: int = 0x270        # ptr<char[]> in parent's body
    flags_word: int = 0x284              # u16 = 0x0101
    # oCDtEnemyDefinition body.
    name_ptr: int = 0x288                # ptr<char[]> — definition id
    name_hash: int = 0x290               # u32, default 0x80000000
    entity_asset_ptr: int = 0x298        # ptr<char[]> — visual entity ref
    entity_asset_hash: int = 0x2A0       # u32, default 0x80000000
    excluded_byte: int = 0x2B0           # u8 — Stage-3 filter reads this
    # MaxOccurence vector (tier curve, head — see filter line 263).
    # NOTE: filter reads {data_ptr@+0x2b8, count@+0x2c0}; the ctor expresses
    # the same span as the oCCustomFlagList vftable@+0x2c0 — these aliases
    # overlap. See enemies.md "Notes" for the reconciliation.
    max_occurrence_ptr: int = 0x2B8
    max_occurrence_count: int = 0x2C0
    flag_list_data_ptr: int = 0x2C8      # oCCustomFlagList::data
    flag_list_count: int = 0x2D0         # oCCustomFlagList::count
    flag_list_capacity: int = 0x2D8      # oCCustomFlagList::capacity, init 1
    min_tier_float: int = 0x2DC          # f32, init 0.1f
    tier_range: int = 0x2E0              # u64 = {u32 min, u32 max}
    has_tribe_byte: int = 0x310          # u8 — gate for tribe ptr read
    tribe_ptr: int = 0x318               # oCDtEnemyTribeDefinition* (raw)
    default_weight: int = 0x320          # f32, init -1.0f
    tier_weight_table_a_ptr: int = 0x328   # {u32 tier, f32 weight}[]
    tier_weight_table_a_count: int = 0x330  # u32
    secondary_weight: int = 0x338        # f32, init -1.0f
    tier_weight_table_b_ptr: int = 0x340
    tier_weight_table_b_count: int = 0x348


ENEMY_DEF: Final = EnemyDefOffsets()


# --------------------------------------------------------------------------- #
# Public emit() — see docstring at top of file for the JSON layout.
# --------------------------------------------------------------------------- #

# Fields accepted on a ContentDef.fields dict.
_CLONE_FIELDS = (
    "base", "name", "display_name", "tribe", "flags", "add_flags",
    "weight", "entity",
)

#: Fields accepted in ``mode = "override"``. Enforced (unknown key -> error),
#: because every one of these is a silent no-op when misspelled: the emit
#: succeeds, the assets install, and the run plays exactly like vanilla.
_OVERRIDE_FIELDS = (
    "mode", "pools", "enemies", "exclude", "entity", "mix", "seed", "weight",
    "cross_biome", "imports", "repoint_pools", "casts",
)


def _enemy_class() -> str:
    return "oCDtEnemyDefinition"


def _load_base_cooked(base_id: str) -> bytes | None:
    """Return the cooked bytes of a vanilla enemy def, or None if no such
    enemy ships under the in-repo enemy-definition tree."""
    return EP.corpus_read(EP.cooked_rel_for(base_id))


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Dispatch on ``mode`` — see :func:`_emit_clone` / :func:`_emit_override`."""
    mode = defn.fields.get("mode", "clone")
    if mode == "override":
        return _emit_override(mod_id, defn, out_dir)
    if mode != "clone":
        raise ContentError(
            f"enemy {defn.id}: unknown mode {mode!r}; use \"clone\" (add a new "
            f"enemy) or \"override\" (rewrite retail enemies in place)."
        )
    return _emit_clone(mod_id, defn, out_dir)


def _emit_clone(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize a single custom enemy as a cooked ``oCDtEnemyDefinition``.

    Clone-and-patch: the cooked bytes of a vanilla ``base`` enemy are
    decoded, the spawn-relevant body fields are overridden, and the
    record is re-emitted under a NEW filename. The stem of that filename
    is the enemy's library identity; ``apply_mods.py`` registers it in
    ``UsedRscList`` so the engine loads it. Because the camp spawn
    selector picks enemies by ``flags`` + ``tribe`` (not by id — see
    docs/_re/kinds/enemies.md and the enemy-spawn-model note), a clone
    that keeps the base's flags + tribe is considered by every camp the
    base spawns in.

    Required fields:
        ``base``   id of a vanilla enemy to clone (e.g. ``Gnoll_Shielded``).

    Optional fields (each defaults to the base's value):
        ``tribe``  tribe name → repoints ``tribe_ref`` at
                   ``EnemyTribes\\<tribe>.enemytribedef.ot``.
        ``flags``  replace the ``oCCustomFlagList`` tag list outright.
        ``add_flags`` extend the base's tag list (ignored if ``flags`` set).
        ``weight`` spawn weight (float) the selector uses to bias picks.
        ``entity`` raw ``entity_ref`` path override (advanced; default
                   reuses the base's visual entity, so the clone looks
                   like its base). HP/damage/name live on that entity —
                   not yet patchable, so a clone shares the base's stats
                   and on-screen name until entity cloning lands.

    Returns ``[<out_dir>/Definitions/Enemies/<id>.enemydef.ot.DtEnemyDefinition.gen]``.
    """
    base = defn.fields.get("base")
    if not base or not isinstance(base, str):
        raise ContentError(
            f"enemy {defn.id}: needs a 'base' (vanilla enemy id) to clone, "
            f"e.g. base=\"Gnoll_Shielded\". See docs/_re/kinds/enemies.md."
        )
    try:
        C.validate_id("enemy", defn.id)
    except ValueError as e:
        raise ContentError(str(e)) from e

    base_cooked = _load_base_cooked(base)
    if base_cooked is None:
        raise SchemaNotMined(
            f"enemy {defn.id}: base {base!r} not found under "
            f"{_ENEMY_DIR} — pass a vanilla enemy id whose cooked def is "
            f"bundled (run `rsmm enemies` to list bases)."
        )

    spec = _defs._SPECS[_enemy_class()]
    try:
        cf = cooked.parse(base_cooked)
        body = spec.decode_body(cf.sections[-1].payload)
    except (ValueError, IndexError) as e:
        raise ContentError(
            f"enemy {defn.id}: failed to decode base {base!r}: {e}"
        ) from e

    # --- patch body ------------------------------------------------------- #
    tribe = defn.fields.get("tribe")
    if tribe is not None:
        if not isinstance(tribe, str) or not C.ID_PATTERN.match(tribe):
            raise ContentError(
                f"enemy {defn.id}: 'tribe' must match {C.ID_PATTERN.pattern}."
            )
        # The runtime tribe roster (oCDtEnemyTribeDefinition+0x2b8) is what the
        # camp selector reads; an enemy is bucketed into it only if its
        # tribe_ref resolves to a real tribe. A typo'd tribe loads but never
        # spawns — fail loudly instead.
        known = _known_tribes()
        if known and tribe not in known:
            raise ContentError(
                f"enemy {defn.id}: tribe {tribe!r} is not a vanilla tribe, so "
                f"the runtime roster won't resolve it and the enemy will never "
                f"spawn. Known tribes: {', '.join(sorted(known))}."
            )
        # Cross-tribe clones keep the base's *entity*, which is pooled for the
        # base's biome — not the new tribe's. Likely never appears. Warn.
        base_tribe = _tribe_of_ref(body["tribe_ref"][1] or "")
        if base_tribe and base_tribe != tribe:
            _log.warning(
                "enemy %s/%s: tribe rewrite %s->%s is cross-tribe; the clone "
                "still uses the base's entity %r, which is pooled for %s's "
                "biome, not %s's, so it may never spawn there. Clone a base "
                "that already belongs to %s, or pass 'entity' pointing at one "
                "pooled in the target biome.",
                mod_id, defn.id, base_tribe, tribe, body["entity_ref"][1],
                base_tribe, tribe, tribe,
            )
        ns = body["tribe_ref"][0] or "Definitions"
        body["tribe_ref"] = [ns, f"EnemyTribes\\{tribe}.enemytribedef.ot"]
        body["base_flags"] = [1, 1]  # has-tribe gate on

    if defn.fields.get("flags") is not None:
        flags = list(defn.fields["flags"])
    else:
        flags = list(body.get("flags") or [])
        flags += list(defn.fields.get("add_flags") or [])
    if not all(isinstance(t, str) and C.ID_PATTERN.match(t) for t in flags):
        raise ContentError(
            f"enemy {defn.id}: every flag must match {C.ID_PATTERN.pattern} "
            f"(game-side tag strings are strict)."
        )
    # de-dupe preserving order
    body["flags"] = list(dict.fromkeys(flags))

    weight = defn.fields.get("weight")
    if weight is not None:
        w = float(weight)
        if w > SPAWN_WEIGHT_MAX:
            raise ContentError(
                f"enemy {defn.id}: spawn weight {w:g} exceeds the safe ceiling "
                f"{SPAWN_WEIGHT_MAX:g}. Extreme weights overflow the weighted "
                f"camp-roster selection and crashed the game at 9999 — use "
                f"single- to low-double-digit weights (vanilla is ~3)."
            )
        if w > SPAWN_WEIGHT_WARN:
            _log.warning(
                "enemy %s/%s: spawn weight %g is very high (vanilla ~3); it "
                "will dominate the camp roster and may destabilise spawning.",
                mod_id, defn.id, w,
            )
        body["spawn_weight"] = w

    entity = defn.fields.get("entity")
    if entity is not None:
        if not isinstance(entity, str):
            raise ContentError(f"enemy {defn.id}: 'entity' must be a string path.")
        ns = body["entity_ref"][0] or "EntitySettings"
        body["entity_ref"] = [ns, entity]

    # --- re-emit cooked record under the new id --------------------------- #
    cf.sections[-1] = cooked.Section(payload=spec.encode_body(body))
    new_cooked = cooked.emit(cf)

    decoded_rel = f"{_ENEMY_ASSET_SUBDIR}/{defn.id}{_ENEMY_GEN_SUFFIX}"
    dest = out_dir / Path(*decoded_rel.split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(new_cooked)
    _log.info(
        "enemy %s/%s: emitted cooked def (base=%s, tribe=%s, flags=%s, weight=%s)",
        mod_id, defn.id, base, body["tribe_ref"][1], body["flags"],
        body["spawn_weight"],
    )
    return [dest]


# --------------------------------------------------------------------------- #
# mode = "override" — repoint retail populations.
# --------------------------------------------------------------------------- #
#
# Of the four things that decide which monster you meet — the camp's tribe
# entry, the tribe's runtime roster, the Stage-3 tier/flag filter, and the
# definition's `entity_ref` — only the last is safe to rewrite in bulk:
#
# * Merging tribes (repointing many defs at one `tribe_ref`) empties the
#   rosters the other tribes' camps read. `FUN_1401c2fd0(&cand, tribe+0x2b8,
#   tribe+0x2c0)` with count 0 hands the Stage-3 filter and then the weighted
#   picker an empty candidate vector. Nothing proves that path is survivable,
#   and the cost of being wrong is a crash at camp build.
# * Tier ranges live in `_tail_hex`; the codec does not type them yet, so
#   editing them is a byte-splice against an unmined layout.
# * `entity_ref` is a typed, round-tripped field, and swapping it changes only
#   which prefab the camp instantiates. The selector, the roster, the tiers
#   and the weights all keep working on exactly the data they had.
#
# Two invariants make the swap safe, and both are enforced below rather than
# documented and hoped for:
#
# 1. **Stay inside one biome pool.** An entity is streamed only for the biome
#    whose `Map_<Biome>_EntityPooling_Settings.level` lists it. Give a Storm
#    Island gnoll a treant and the def resolves to a prefab that biome never
#    loaded. Candidates are therefore drawn per-pool, never across pools.
# 2. **Carry the resource cache with the swap.** Every enemydef ships a
#    sibling `*.UsedRscCache.ot` holding its transitive preload closure (81 of
#    81). Repointing `entity_ref` without it leaves the new prefab's meshes,
#    animations and materials unlisted — a resource the def asks for that the
#    cache never named resolves to null, and the teardown loop at
#    `0x140476f60` destroys it unchecked (access violation at `0x1401273b6`,
#    nowhere near this edit). So each rewritten def gets the sorted union of
#    its own cache and its donor's. Union, not replacement: a surplus line
#    costs one wasted preload of a real shipped file, a missing one crashes.
#    Sorting is load-bearing — the engine looks up rather than scans.

#: Enemy definitions never rewritten, whatever the scope asks for. Every one
#: is reachable only through a script that also owns its encounter, so a swap
#: here breaks a boss fight or a quest rather than the wandering population.
#: Pool membership already excludes most of them; these are the ones that sit
#: in a pool because a boss arena streams them.
_OVERRIDE_NEVER: Final[frozenset[str]] = frozenset({
    "Baba_Yaga_Tentacle_Summon",
})


def _pool_groups(defn_id: str, pools_req, enemies_req, exclude) -> dict[str, list[str]]:
    """Resolve the requested scope to ``biome -> [enemy id, ...]``.

    Grouping by biome is not a convenience — it is invariant 1. Callers get
    one candidate set per pool and cannot accidentally mix them.
    """
    index = EP.enemy_index()
    if not index:
        raise SchemaNotMined(
            f"enemy {defn_id}: no enemy definitions found — mode=\"override\" "
            f"reads the cooked defs from the uncooked mirror or, failing that, "
            f"straight out of the game install, and neither is available. "
            f"Point rsmm at the game (`rsmm doctor`), or build the mirror with "
            f"python scripts/extract_uncooked.py."
        )
    open_world = {b for b in EP.pools() if b not in EP.BOSS_ARENA_POOLS}

    if pools_req is None and enemies_req is None:
        wanted_pools = set(open_world)
    else:
        wanted_pools = set()
        for name in pools_req or ():
            if name not in EP.pools():
                raise ContentError(
                    f"enemy {defn_id}: unknown pool {name!r}. Biome pools: "
                    f"{', '.join(sorted(EP.pools()))} (`rsmm enemies pools`)."
                )
            wanted_pools.add(name)

    skip = set(exclude or ()) | _OVERRIDE_NEVER
    for name in exclude or ():
        if name not in index:
            raise ContentError(
                f"enemy {defn_id}: exclude names {name!r}, which is not an "
                f"enemy definition (`rsmm enemies list`)."
            )

    groups: dict[str, list[str]] = {}
    for enemy_id, row in index.items():
        biome = row["biome"]
        if biome is None or enemy_id in skip:
            # No pool streams this prefab, so no camp selector rolls it: it is
            # a boss, a summon or a quest enemy, placed by whatever scripted
            # it. Rewriting one changes an encounter, not the population.
            continue
        if biome in wanted_pools or enemy_id in (enemies_req or ()):
            groups.setdefault(biome, []).append(enemy_id)

    for name in enemies_req or ():
        if name not in index:
            raise ContentError(
                f"enemy {defn_id}: {name!r} is not an enemy definition "
                f"(`rsmm enemies list`)."
            )
        if index[name]["biome"] is None and name not in skip:
            raise ContentError(
                f"enemy {defn_id}: {name!r} is not in any biome spawn pool, so "
                f"it is placed by a boss or quest script rather than rolled by "
                f"a camp. Rewriting it would change that encounter — drop it "
                f"from 'enemies'."
            )

    for biome in groups:
        groups[biome].sort()
    return {b: ids for b, ids in sorted(groups.items()) if ids}


def _biome_casts(defn_id: str, groups: dict[str, list[str]], entity, seed,
                 cross_biome: bool, imports: int | None = None) -> dict[str, list[str]]:
    """``biome -> the creatures that biome will stream`` after the edit.

    Without ``cross_biome`` a biome's cast is what it already had, and the
    randomiser can only permute it — which is invisible to a player, because
    Storm Island still shows crabs and gnolls. With it, each biome draws a
    fresh cast from every creature in the game, and :func:`_emit_pool` rewrites
    the biome's ``EntityPooling`` asset so those creatures are actually
    streamed there.

    The cast is sized to the biome's **def-owned** pool slots. Repointing is
    all the ``oCGameStream`` codec supports — a ref edit is absorbed into its
    section, but the vector cannot grow — so a biome can host exactly as many
    distinct creatures as it already did. That is 10-15 per biome, drawn from
    50 game-wide.
    """
    index = EP.enemy_index()
    if not cross_biome:
        return {b: [index[i]["entity"] for i in ids] for b, ids in groups.items()}

    global_pool = EP.spawnable_entities()
    out: dict[str, list[str]] = {}
    if entity is not None:
        # A fixed prefab everywhere is the one configuration that CANNOT keep
        # the pools disjoint — the whole point is that every biome streams the
        # same creature. Left as the author asked for; see the partition note
        # below for what that costs.
        return {biome: [entity] for biome in groups}

    # BOUNDED IMPORTS. `imports` caps how many of a biome's slots hold a
    # foreign creature; the rest keep the creature they shipped with.
    #
    # Two reasons to want that. The obvious one is taste — a full deal
    # replaces a biome's ENTIRE cast, so Storm Island stops being Storm Island.
    # The load-bearing one is the chapter-transition crash. CORRECTED
    # 2026-08-31: the abort is NOT a time budget (an earlier reading of
    # `FUN_140516cd0` as a frame budget was wrong). It is a CANCEL — every
    # loader calls `LevelLoad_AbortPredicate`, which returns 1 when two
    # booleans on the oe::Engine singleton (+0x18 and +0x19) are both set, and
    # then bails BEFORE opening the stream. `LevelObject_LoadOrCreate` treats
    # that as failure and destroys the half-built level, whose teardown walks
    # the object vector with no null check. So the crash is the cleanup of a
    # CANCELLED load, which is why every asset-integrity hypothesis came back
    # clean. The one +0x18 writer found sets it and then drains a work queue —
    # a teardown shape — so the cancel plausibly arrives as the OLD chapter is
    # torn down, and a load still in flight at that moment is the one that
    # dies. Less new streaming = a narrower window to be caught in. That is the
    # variable this knob controls; it does not remove the race.
    #
    # ⚠ UNPROVEN as a fix for that crash — it is a hypothesis with a mechanism,
    # which is exactly what the last two "fixes" were. It is offered as a knob
    # and an experiment, not as a repair.
    #
    # Implemented as SWAPS between biomes rather than a fresh draw, because the
    # partition is what the disjoint-pool work bought and a fresh draw can
    # break it: picking a foreigner from the global set can pick a creature the
    # biome that owns it is also keeping, putting one entity in two pools. A
    # swap moves a creature from one biome to another and is partition-
    # preserving by construction — every creature still lands in exactly one
    # pool, and each swap makes exactly one slot foreign on each side.
    if imports is not None:
        cast = {b: [index[i]["entity"] for i in ids] for b, ids in groups.items()}
        movable = {b: [e for e in ents] for b, ents in cast.items()}
        biomes = [b for b in sorted(cast) if movable[b]]
        if len(biomes) >= 2 and imports > 0:
            rng = _rng(seed, "swap")
            # Each swap gives one import to each of two biomes, so this many
            # swaps lands ~`imports` foreigners in every biome.
            n_swaps = max(1, round(imports * len(biomes) / 2))
            for _ in range(n_swaps):
                a, b = rng.sample(biomes, 2)
                ia = rng.randrange(len(movable[a]))
                ib = rng.randrange(len(movable[b]))
                movable[a][ia], movable[b][ib] = movable[b][ib], movable[a][ia]
        return {b: sorted(ents) for b, ents in movable.items()}

    # ONE global deal, not an independent draw per biome.
    #
    # The shipped pools PARTITION: no entity is in two of them (measured, 0 of
    # 57). Drawing each biome's cast independently from the same 50-entity set
    # broke that — 12 of 39 entities ended up in two to four pools at once —
    # and a shared entity is a shared lifetime. Chapter 1 has nothing before it
    # and loads fine; every later chapter tears the previous biome's pool down
    # while building its own, so an entity both of them list can be freed out
    # from under the incoming preload vector. That is the same null-in-the-
    # preload-vector shape the tiledef cache work hit, and it presents as a
    # black screen entering chapter 2 with chapter 1 perfectly healthy.
    #
    # Dealing one permutation across the biomes keeps the invariant by
    # construction. It fits exactly: 50 def-owned slots, 50 spawnable
    # creatures, so a full-scope roll uses every creature exactly once.
    order = sorted(groups)
    rng = _rng(seed, "cast")
    deck = list(global_pool)
    rng.shuffle(deck)
    at = 0
    for biome in order:
        want = len(_def_owned_slots(biome))
        take = deck[at:at + want]
        at += len(take)
        if len(take) < want:
            # More slots than creatures in scope. Reuse rather than leave a
            # slot pointing at a creature no definition owns, and accept the
            # duplication that the partition otherwise avoids.
            take += [deck[i % len(deck)] for i in range(want - len(take))]
        out[biome] = sorted(take)
    return out


def _def_owned_slots(biome: str) -> list[int]:
    """Indices into a pool's enemy refs that some enemy definition owns.

    The other entries are that biome's projectiles, attack zones and VFX
    trails (``Gargoyle_Fire_Attack_Zone``, ``Projectile_Witches_Poison_Apple``,
    ``Dullahan_Gallop_Trail``). They are not creatures and nothing rolls them —
    repointing one would delete the visual or hitbox a real attack needs, so
    they are never touched.
    """
    owned = {r["entity"].lower() for r in EP.enemy_index().values()}
    return [i for i, e in enumerate(EP.pools()[biome]) if e.lower() in owned]


def _creature_entity(defn_id: str, name: str) -> str:
    """One entry of a hand-written cast -> the entity ref it means.

    Authors think in monster names, not in cooked prefab paths, so all three
    spellings of the same creature are accepted: the definition id
    (``Elite_Wolf_Alpha``), the prefab's stem, and the full entity ref
    (``Enemies\\Wolves\\Elite_Wolf_Alpha.entity.ot``). Whatever comes in,
    an entity ref goes out — that is the only thing an ``entity_ref`` edit and
    a pool slot can hold.

    Only camp-spawnable creatures resolve. A boss, a summon or a quest enemy
    has no pool streaming it and no definition of its own to borrow a preload
    closure from, so naming one would emit a def pointing at a prefab that is
    never there.
    """
    idx = EP.enemy_index()
    spawnable = EP.spawnable_entities()
    row = idx.get(name)
    if row is not None and row["entity"] and row["biome"] is not None:
        return row["entity"]
    key = str(name).replace("/", "\\").lower()
    by_ref = {e.lower(): e for e in spawnable}
    if key in by_ref:
        return by_ref[key]
    by_stem = {e.replace("/", "\\").split("\\")[-1].split(".", 1)[0].lower(): e
               for e in spawnable}
    if key in by_stem:
        return by_stem[key]
    raise ContentError(
        f"enemy {defn_id}: {name!r} in 'casts' is not a camp-spawnable "
        f"creature. Name a definition id (`rsmm enemies list`), a prefab stem "
        f"or a full entity ref from `rsmm enemies pool <biome>`. Bosses, "
        f"summons and quest enemies are placed by script and cannot be cast."
    )


def _explicit_casts(defn_id: str, raw, groups: dict[str, list[str]],
                    cross_biome: bool) -> dict[str, list[str]]:
    """Validate a hand-written ``casts`` table -> ``biome -> [entity ref]``.

    ``casts`` is the manual counterpart of the roll: instead of dealing each
    chapter a cast, the author writes one. Everything downstream is unchanged
    — the cast is still what the chapter streams and still what
    :func:`_assignment` hands to that chapter's definitions — so a listed
    chapter behaves exactly as if the seed had happened to deal those
    creatures.
    """
    if not isinstance(raw, dict):
        raise ContentError(
            f"enemy {defn_id}: 'casts' must be a table of "
            f"chapter -> [monster, ...], e.g. "
            f"[content.casts] / Dark_Hills = [\"Elite_Wolf_Alpha\"]. "
            f"Got {type(raw).__name__}."
        )
    out: dict[str, list[str]] = {}
    for biome, names in raw.items():
        if biome not in EP.pools():
            raise ContentError(
                f"enemy {defn_id}: casts names unknown chapter {biome!r}. "
                f"Chapters: {', '.join(sorted(EP.pools()))} "
                f"(`rsmm enemies pools`)."
            )
        if biome not in groups:
            # Silent no-op otherwise: the cast would be built and no
            # definition in scope would ever be assigned from it.
            raise ContentError(
                f"enemy {defn_id}: casts covers {biome!r}, which this scope "
                f"leaves alone. Add it to 'pools' (or drop 'pools' to cover "
                f"every chapter) so its definitions are actually rewritten."
            )
        if not isinstance(names, (list, tuple)) or not names:
            raise ContentError(
                f"enemy {defn_id}: casts[{biome!r}] must be a non-empty list "
                f"of monsters. An empty cast leaves nothing for the chapter's "
                f"definitions to point at."
            )
        if not all(isinstance(n, str) for n in names):
            raise ContentError(
                f"enemy {defn_id}: casts[{biome!r}] must contain monster "
                f"names as strings."
            )
        ents = [_creature_entity(defn_id, n) for n in names]
        native = EP.pool_of_entity()
        foreign = sorted({e for e in ents if native.get(e.lower()) != biome})
        if foreign and not cross_biome:
            raise ContentError(
                f"enemy {defn_id}: casts[{biome!r}] lists {foreign[0]!r}, "
                f"which {biome} does not stream. Set cross_biome = true "
                f"(with repoint_pools = false) to pull creatures across "
                f"chapters, or cast only monsters from "
                f"`rsmm enemies pool {biome}`."
            )
        # Sorted + de-duplicated for the same reason the dealt cast is: the
        # emitted bytes are the roll, so two authors writing the same set in a
        # different order must install identical assets.
        out[biome] = sorted(set(ents))
    return out


def _config_casts(mod_root: Path) -> dict[str, list[str]]:
    """The player's per-chapter picks from the mod's config panel.

    A `multiselect` field named after a biome pool (``Dark_Hills``, ``Avalon``,
    …) is that chapter's cast. Only non-empty selections are returned: an empty
    picker means "I have not chosen for this chapter", which leaves it on the
    manifest's cast or the roll. That is the opposite of the item ban, where an
    empty selection is the meaningful state "nothing banned" — here an empty
    cast is not a configuration at all, it is a chapter with nothing to spawn.

    Everything is best-effort: a mod with no schema, an unreadable
    ``config.toml`` or a field naming no pool simply contributes nothing, so a
    hand-authored mod behaves exactly as it did before the panel existed.
    """
    from ..config import ConfigError, ConfigStore

    if not (mod_root / "config_schema.toml").is_file():
        return {}
    try:
        store = ConfigStore(mod_root)
    except (OSError, ConfigError, ValueError):
        return {}
    by_key = {b.lower(): b for b in EP.pools()}
    out: dict[str, list[str]] = {}
    for name, fld in store.schema.fields.items():
        biome = by_key.get(name.lower())
        if biome is None or fld.type != "multiselect":
            continue
        picked = store.get(name) or []
        if isinstance(picked, (list, tuple)) and picked:
            out[biome] = [str(x) for x in picked]
    return out


def _rng(seed, *parts: str):
    """Seeded RNG namespaced by ``parts``.

    Namespacing per biome means adding a pool to the scope does not reshuffle
    the pools already in it — an author tuning one biome keeps the rest.
    """
    import random

    return random.Random(f"{seed}:" + ":".join(parts))


def _emit_pool(biome: str, cast: list[str], out_dir: Path,
               defn_id: str) -> Path | None:
    """Rewrite a biome's ``EntityPooling`` asset to stream ``cast``.

    Repoints the def-owned slots and leaves every support entry alone. Returns
    the written override, or None when the pool already streams the cast.

    Verified byte-behaviour: an identity edit reproduces the shipped file
    exactly, and a length-changing ref edit is absorbed into the section that
    holds it, so the vector's own layout never moves.
    """
    from ...engine.cooked_schemas.asset_refs import _decode, _encode

    rel = EP.pool_cooked_rel(biome)
    raw = EP.corpus_read(rel)
    if raw is None:
        raise SchemaNotMined(
            f"enemy {defn_id}: {rel} is missing from the corpus and the game "
            f"install, so {biome}'s pool cannot be rewritten."
        )
    doc = _decode(raw, "oCGameStream")
    refs = list(doc["asset_refs"])

    # `_def_owned_slots` indexes the ENEMY refs; map those onto the full ref
    # list, which also carries the biome's props.
    enemy_idx = [i for i, r in enumerate(refs) if r.lower().startswith("enemies\\")]
    slots = [enemy_idx[i] for i in _def_owned_slots(biome)]

    if len(cast) == 1:
        # A fixed entity needs one slot, not the whole pool rewritten.
        if any(refs[i].lower() == cast[0].lower() for i in slots):
            return None
        refs[slots[0]] = cast[0]
    else:
        for slot, ent in zip(slots, cast, strict=False):
            refs[slot] = ent

    if refs == doc["asset_refs"]:
        return None
    doc["asset_refs"] = refs
    dest = out_dir / Path(*rel.split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_encode(json.dumps(doc).encode("utf-8")))
    _log.info("enemy %s: repointed %d pool slot(s) in %s", defn_id, len(cast), biome)
    return dest


def _assignment(defn_id: str, groups: dict[str, list[str]],
                casts: dict[str, list[str]], entity, mix, seed) -> dict[str, str]:
    """``enemy id -> the entity_ref it should end up pointing at``.

    Draws from the pool that will actually stream the def, so the result is
    streamed there by construction rather than by a check that could be
    forgotten.

    WHICH pool that is, is the whole subtlety, and it is settled by the spawn
    chain rather than by the entity: a def is rolled by a camp because its
    TRIBE's runtime roster is what the tier selector reads, and neither the
    tribe nor the camps move when this kind rewrites an ``entity_ref``. So a
    def keeps spawning in the biome it shipped in — the biome it is keyed
    under in ``groups`` — and its donor must come from THAT biome's cast,
    which is exactly what :func:`_emit_pool` makes the biome stream.

    ⚠ It was keyed the other way for one day (690df15, reverted 2026-08-31):
    "a def is reached through the ENTITY it owns, so key by where that entity
    was dealt". That inverts cause and effect. The entity is a consequence of
    the def, not the route to it, and after this function runs the def does
    not own that entity any more — the ownership map it keyed on describes
    only the vanilla state it is in the middle of replacing. The metric it
    was justified by (40 of 57 pool entries "resolving outside their pool")
    is that same wrong model measuring itself, and it did not change the
    chapter-2 crash it was written for.

    What it DID do is silently drop defs: it replaced ``groups`` with the
    owners of the cast, so a scoped run (``pools = ["Dark_Hills"]``, whose
    cast is dealt from every biome) emitted 7 of the 15 Dark Hills defs and 8
    out-of-scope ones instead. The 8 unemitted defs kept pointing at vanilla
    entities the repointed pool no longer streams, so they could not spawn —
    the population looked untouched, which is how it was found.
    """
    if entity is not None:
        return {eid: entity for ids in groups.values() for eid in ids}

    out: dict[str, str] = {}
    for biome, ids in groups.items():
        candidates = casts[biome]
        rng = _rng(seed, biome)
        if mix == "shuffle" and len(candidates) == len(ids):
            # A permutation: every creature appears exactly once, so the
            # biome keeps its composition and only the labels move.
            picks = list(candidates)
            rng.shuffle(picks)
            if len(picks) > 1 and picks == [EP.enemy_index()[i]["entity"] for i in ids]:
                picks.append(picks.pop(0))
        elif mix == "shuffle":
            picks = rng.sample(candidates, k=min(len(ids), len(candidates)))
            while len(picks) < len(ids):
                picks.append(rng.choice(candidates))
        else:
            # "random": an independent draw per definition. Duplicates are the
            # point — a camp can come up all one creature.
            picks = [rng.choice(candidates) for _ in ids]
        out.update(zip(ids, picks, strict=True))
    return out


def _override_one(enemy_id: str, new_entity: str, weight, out_dir: Path,
                  defn_id: str) -> list[Path]:
    """Rewrite one retail def + its resource cache. Returns written paths."""
    spec = _defs._SPECS[_enemy_class()]
    # From the mirror on an authoring checkout, from the install's own cooked
    # tree everywhere else — see `enemy_pools.corpus_read`. The bytes are the
    # same either way, and the install copy read is the pristine `.rsmm.bak`
    # when a previous apply left one, so a re-apply re-derives from vanilla
    # instead of stacking an override on an override.
    raw = EP.corpus_read(EP.cooked_rel_for(enemy_id))
    if raw is None:
        raise SchemaNotMined(
            f"enemy {defn_id}: no cooked definition for {enemy_id!r} in the "
            f"corpus or the game install."
        )
    try:
        cf = cooked.parse(raw)
        body = spec.decode_body(cf.sections[-1].payload)
    except (OSError, ValueError, IndexError) as e:
        raise ContentError(
            f"enemy {defn_id}: failed to decode retail {enemy_id!r}: {e}"
        ) from e

    old_entity = body["entity_ref"][1] or ""
    body["entity_ref"] = [body["entity_ref"][0] or "EntitySettings", new_entity]
    if weight is not None:
        body["spawn_weight"] = float(weight)
    cf.sections[-1] = cooked.Section(payload=spec.encode_body(body))
    new_bytes = cooked.emit(cf)

    # A "random" draw can hand a definition back its own prefab, and a fixed
    # entity always covers the definition that already owned it. Re-encoding
    # is byte-stable, so those come out identical to the shipped file —
    # installing one would back up a file and replace it with itself, for a
    # backup the restore path then has to carry. Emit nothing instead.
    if new_bytes == raw:
        return []

    written: list[Path] = []
    dest = out_dir / Path(*EP.cooked_rel_for(enemy_id).split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(new_bytes)
    written.append(dest)

    if new_entity.lower() != old_entity.lower():
        written.append(_emit_merged_cache(enemy_id, new_entity, out_dir, defn_id))
    return written


def _emit_merged_cache(enemy_id: str, new_entity: str, out_dir: Path,
                       defn_id: str) -> Path:
    """Union this def's cache with the cache of the def that owns
    ``new_entity``, and write it beside the override.

    Borrowing the donor's whole cache beats deriving the prefab's closure: the
    donor is the definition the engine itself preloads that entity for, so its
    cache is guaranteed to contain the closure, mesh and animations included.
    Same trade :mod:`rsmm.engine.rsc_cache` already makes by being additive.
    """
    owner = None
    for eid, row in EP.enemy_index().items():
        if row["entity"].lower() == new_entity.lower():
            owner = eid
            break
    if owner is None:
        raise ContentError(
            f"enemy {defn_id}: no enemy definition owns entity {new_entity!r}, "
            f"so there is no shipped resource cache to borrow its preload "
            f"closure from. Without one the prefab's meshes resolve to null at "
            f"level build. Pick an entity some enemy def already uses."
        )

    own_rel = RC.cache_path_for(EP.cooked_rel_for(enemy_id))
    donor_rel = RC.cache_path_for(EP.cooked_rel_for(owner))
    lines: set[str] = set()
    for rel in (own_rel, donor_rel):
        # A `.UsedRscCache.ot` is in neither `UsedRscList.ot` nor `asset_map`;
        # `corpus_read` falls through to `resolve_special`, which ciphers the
        # path by the same convention the engine uses to find it.
        blob = EP.corpus_read(rel)
        if blob is None:
            raise SchemaNotMined(
                f"enemy {defn_id}: {rel} is missing from the corpus and the "
                f"game install, so the preload closure for {enemy_id} cannot "
                f"be assembled."
            )
        lines |= set(RC.parse(blob))

    dest = out_dir / Path(*own_rel.split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Sorted, because the engine binary-searches this file rather than
    # scanning it — an out-of-order line is a line the lookup never reaches.
    dest.write_bytes(RC.render(sorted(lines)))
    return dest


def _emit_override(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Rewrite retail enemy definitions in place — fixed swap or randomised.

    Fields:
        ``pools``   biome pools to cover (default: every open-world pool, i.e.
                    all but the boss arenas). ``rsmm enemies pools``.
        ``enemies`` extra enemy ids to include beyond ``pools``.
        ``exclude`` enemy ids to leave alone.
        ``entity``  one prefab every target becomes ("everything is a treant").
                    Mutually exclusive with ``mix``.
        ``mix``     ``"random"`` (independent draw per enemy — duplicates are
                    the point) or ``"shuffle"`` (a permutation, so the roster
                    keeps its composition and only the labels move).
        ``seed``    int, required with ``mix``. The randomisation happens at
                    ``rsmm apply`` time, not per run: the emitted assets are
                    the roll. That is what keeps co-op consistent — every peer
                    installs the same bytes. Re-roll by changing the seed.
        ``weight``  uniform ``spawn_weight`` for every target, flattening the
                    weighted pick to near-uniform.
        ``cross_biome``
                    draw candidates from every creature in the game instead of
                    only the biome's own cast, and rewrite each biome's
                    ``EntityPooling`` asset so those creatures are streamed
                    there. Without it the randomiser can only permute a
                    biome's existing cast, which is invisible to a player —
                    Storm Island still shows crabs and gnolls. Each biome can
                    host as many distinct creatures as it already had (10-15),
                    because a pool ref can be repointed but the vector cannot
                    grow.
        ``casts``   table of ``chapter -> [monster, ...]`` — the manual
                    counterpart of the roll. A listed chapter draws only from
                    the monsters written there instead of from the dealt or
                    vanilla cast; unlisted chapters are untouched. Monsters
                    may be named by definition id (``Elite_Wolf_Alpha``),
                    prefab stem, or full entity ref. ``mix`` still decides how
                    that cast is spread over the chapter's definitions, so a
                    one-monster cast makes the whole chapter that monster.
                    Casting a creature from another chapter needs
                    ``cross_biome = true`` (and ``repoint_pools = false``,
                    which is the combination that ships today).
        ``repoint_pools``
                    default true, and **false is the one that works**. Set
                    it false to draw the cast game-wide WITHOUT rewriting any
                    ``EntityPooling`` asset — the imported prefab is reached
                    through the definition's merged resource cache instead,
                    which is sufficient on its own (proven in-game
                    2026-09-01). The pool repoint is this kind's only edit to
                    a level asset and the only cause of the chapter-transition
                    failure; it is kept solely so the old behaviour stays
                    expressible.
    """
    unknown = sorted(set(defn.fields) - set(_OVERRIDE_FIELDS))
    if unknown:
        raise ContentError(
            f"enemy {defn.id}: unknown field(s) {', '.join(unknown)} in "
            f"mode=\"override\"; accepted: {', '.join(_OVERRIDE_FIELDS)}."
        )

    entity = defn.fields.get("entity")
    mix = defn.fields.get("mix")
    seed = defn.fields.get("seed")
    weight = defn.fields.get("weight")
    cross_biome = bool(defn.fields.get("cross_biome"))
    imports = defn.fields.get("imports")
    if imports is not None:
        if not isinstance(imports, int) or isinstance(imports, bool) or imports < 0:
            raise ContentError(
                f"enemy {defn.id}: imports must be a non-negative whole number "
                f"(creatures per biome drawn from other chapters), got "
                f"{imports!r}."
            )
        if not cross_biome:
            raise ContentError(
                f"enemy {defn.id}: imports = {imports} only means anything with "
                f"cross_biome = true — without it no creature crosses a biome "
                f"boundary at all, so there is nothing to bound."
            )

    repoint_pools = defn.fields.get("repoint_pools", True)
    if not isinstance(repoint_pools, bool):
        raise ContentError(
            f"enemy {defn.id}: repoint_pools must be true or false, got "
            f"{repoint_pools!r}."
        )
    if not repoint_pools and not cross_biome:
        raise ContentError(
            f"enemy {defn.id}: repoint_pools = false only means anything with "
            f"cross_biome = true — without it no creature crosses a biome "
            f"boundary, so no pool would be repointed either way."
        )

    # The config panel's picks are merged over the manifest's, per chapter: the
    # panel is where a PLAYER edits this mod, so a chapter they picked for wins
    # over the cast the author wrote, while a chapter they left empty keeps it.
    casts_req = defn.fields.get("casts")
    picked = _config_casts(out_dir.parent)
    if picked and (casts_req is None or isinstance(casts_req, dict)):
        casts_req = {**(casts_req or {}), **picked}
    if entity is not None and casts_req is not None:
        raise ContentError(
            f"enemy {defn.id}: 'entity' (one fixed prefab everywhere) and "
            f"'casts' (a hand-written cast per chapter) are mutually "
            f"exclusive — pick one."
        )
    if entity is not None and mix is not None:
        raise ContentError(
            f"enemy {defn.id}: 'entity' (one fixed prefab) and 'mix' "
            f"(randomised) are mutually exclusive — pick one."
        )
    if entity is None and mix is None:
        raise ContentError(
            f"enemy {defn.id}: mode=\"override\" needs either entity = "
            f"\"Enemies\\\\...\" (turn the scope into one monster) or "
            f"mix = \"random\" | \"shuffle\" with a seed. 'casts' picks "
            f"WHICH monsters a chapter draws from; 'mix' is still what "
            f"spreads them over that chapter's definitions."
        )
    if entity is not None and not isinstance(entity, str):
        raise ContentError(f"enemy {defn.id}: 'entity' must be a string path.")
    if mix is not None:
        if mix not in ("random", "shuffle"):
            raise ContentError(
                f"enemy {defn.id}: mix must be \"random\" or \"shuffle\", "
                f"got {mix!r}."
            )
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise ContentError(
                f"enemy {defn.id}: mix = {mix!r} needs an integer 'seed'. The "
                f"roll happens once at apply time and is baked into the "
                f"emitted assets, so the seed is what every peer must share."
            )
    if weight is not None:
        w = float(weight)
        if w > SPAWN_WEIGHT_MAX:
            raise ContentError(
                f"enemy {defn.id}: spawn weight {w:g} exceeds the safe ceiling "
                f"{SPAWN_WEIGHT_MAX:g} (9999 crashed the weighted camp-roster "
                f"selection). Vanilla weights are ~1-20."
            )
        if w > SPAWN_WEIGHT_WARN:
            _log.warning("enemy %s/%s: uniform weight %g is very high "
                         "(vanilla ~1-20)", mod_id, defn.id, w)

    groups = _pool_groups(defn.id, defn.fields.get("pools"),
                          defn.fields.get("enemies"), defn.fields.get("exclude"))
    if not groups:
        raise ContentError(
            f"enemy {defn.id}: the requested scope covers no camp-spawnable "
            f"enemy. Check pools/enemies against `rsmm enemies pools`."
        )
    if entity is not None:
        # The fixed prefab has to be a creature some definition owns, or there
        # is no shipped cache to borrow its preload closure from.
        # Pooled somewhere open-world, which is both "a definition owns it, so
        # its preload closure can be borrowed" and "it is a wandering monster
        # rather than a boss or a summon".
        if entity.lower() not in {e.lower() for e in EP.spawnable_entities()}:
            raise ContentError(
                f"enemy {defn.id}: entity {entity!r} is not in any biome spawn "
                f"pool, so it is placed by a boss or quest script rather than "
                f"rolled by a camp. Pick one from `rsmm enemies pool <biome>`."
            )
        target_pool = EP.pool_of_entity().get(entity.lower())
        bad = [b for b in groups if b != target_pool]
        if bad and not cross_biome:
            raise ContentError(
                f"enemy {defn.id}: entity {entity!r} is pooled for "
                f"{target_pool}, but the scope also covers {', '.join(bad)}. "
                f"An entity is only streamed for its own biome — narrow the "
                f"scope with pools = [\"{target_pool}\"], or set "
                f"cross_biome = true to repoint those pools so they stream it."
            )

    if cross_biome and repoint_pools and entity is None:
        # A scoped cross_biome run CANNOT keep the pools disjoint. The cast is
        # dealt from every spawnable creature in the game, but only the pools
        # in scope are rewritten — so a creature dealt in from Storm Island is
        # now listed by BOTH Dark Hills and Storm Island, whose pool nothing
        # touched. MEASURED with pools = ["Dark_Hills"], seed 1337: 8 of the
        # 15 dealt entities ended up in two pools at once.
        #
        # That is precisely the shared-lifetime shape the partition work
        # removed: every chapter after the first tears the previous biome's
        # pool down while building its own, so a creature both list can be
        # freed out from under the incoming preload vector — a black screen
        # entering chapter 2 with chapter 1 healthy. Narrowing the scope was
        # tried as a way to make cross_biome safer; it re-creates the exact
        # bug instead, so refuse rather than plant it.
        open_world = {b for b in EP.pools() if b not in EP.BOSS_ARENA_POOLS}
        missing = sorted(open_world - set(groups))
        if missing:
            raise ContentError(
                f"enemy {defn.id}: cross_biome deals creatures from every "
                f"biome, so it has to rewrite every biome's pool — but this "
                f"scope leaves {', '.join(missing)} untouched. Those pools "
                f"would keep listing creatures now also pooled for "
                f"{', '.join(sorted(groups))}, and an entity in two pools is "
                f"freed out from under whichever chapter loads second. Drop "
                f"'pools' to cover every biome, set repoint_pools = false "
                f"so no pool is rewritten at all, or use cross_biome = false "
                f"for a within-biome shuffle."
            )

    casts = _biome_casts(defn.id, groups, entity, seed, cross_biome, imports)

    if casts_req is not None:
        # A hand-written cast REPLACES the dealt one for the chapters it
        # names, and leaves every other chapter on whatever the roll (or
        # vanilla) gave it. Overlaid here rather than inside `_biome_casts`
        # so the deal stays one pure function of the seed: an author who
        # pins Dark Hills does not reshuffle Avalon.
        casts.update(_explicit_casts(defn.id, casts_req, groups, cross_biome))
        if cross_biome and repoint_pools:
            # Both of these are only hazards when a POOL is rewritten, which
            # is exactly this branch. With repoint_pools = false nothing but
            # the definitions and their merged caches move, so a hand-written
            # cast of any size or overlap is fine.
            for biome, cast in sorted(casts.items()):
                slots = len(_def_owned_slots(biome))
                if len(cast) > slots:
                    raise ContentError(
                        f"enemy {defn.id}: casts[{biome!r}] lists "
                        f"{len(cast)} monsters but {biome} has {slots} pool "
                        f"slots, and a pool ref can be repointed while the "
                        f"vector cannot grow — the surplus would never be "
                        f"streamed. Cut the cast to {slots}, or set "
                        f"repoint_pools = false (recommended) so no pool is "
                        f"rewritten and the count stops mattering."
                    )
            seen: dict[str, str] = {}
            for biome, cast in sorted(casts.items()):
                for ent in cast:
                    first = seen.setdefault(ent.lower(), biome)
                    if first != biome:
                        raise ContentError(
                            f"enemy {defn.id}: {ent!r} is cast in both "
                            f"{first} and {biome}. The shipped pools "
                            f"partition (no entity in two), and a shared "
                            f"entity is a shared lifetime: the chapter that "
                            f"loads second can have it freed out from under "
                            f"its preload vector — a black screen on the "
                            f"transition. Give each chapter its own "
                            f"monsters, or set repoint_pools = false so no "
                            f"pool is rewritten at all."
                        )

    written: list[Path] = []
    if cross_biome and not repoint_pools:
        # NO POOL IS REWRITTEN. The imported prefab reaches the biome through
        # the definition's own resource cache instead.
        #
        # `_emit_merged_cache` already unions the DONOR definition's cache into
        # the one beside the override, and a definition's cache lists its own
        # `.entity.ot` — measured 56 of 56, no exceptions. So the imported
        # prefab and its whole closure are preloaded by the definition that
        # points at it, with no edit to any `EntityPooling` level at all.
        #
        # That matters because the pool repoint is the ONLY thing this kind
        # does to a LEVEL asset, and the only failure is a chapter TRANSITION
        # (chapter 1 renders imports fine — confirmed in-game 2026-08-28).
        # Skipping it leaves the transition path byte-identical to vanilla.
        #
        # PROVEN IN-GAME 2026-09-01, and it settles the question the old design
        # never got to ask: POOL MEMBERSHIP IS NOT A GATE for a def-owned
        # entity. A full game-wide deal with no pool rewritten at all played
        # through with the imported creatures spawning and no chapter failure.
        # The repoint was never what made cross-biome work — it was only ever
        # the thing that broke the transition.
        _log.info(
            "enemy %s: cross_biome with repoint_pools = false — imported "
            "prefabs are preloaded by each definition's merged resource cache "
            "and no EntityPooling asset is touched", defn.id,
        )
    elif cross_biome:
        # KNOWN BROKEN — repointing a pool still crashes entering chapter 2.
        # The engine fails to load one of the newly-pooled entities and then
        # tears the half-built vector down through the destroy loop at
        # 0x140476f60, which has no null check (dump a8bb7d8c: 12 entries,
        # null at index 8 = Storm Island's Standard_Thief_Marksman, dealt in
        # from Common). Ruled out: the entity assets exist and resolve; the
        # emitted caches match the engine's own sort order; every pooled
        # entity is listed in its owning def's cache; and the
        # destination-keyed assignment fix below (40/57 -> 0/57 out-of-pool
        # resolutions) did NOT change the crash. Why that one load fails is
        # still unknown, so warn loudly rather than pretend this is safe.
        _log.warning(
            "enemy %s: cross_biome repoints biome spawn pools, which is known "
            "to crash on chapter transition on the current build. The cause is "
            "not understood yet — see the note in this function. Use "
            "cross_biome = false for a within-biome shuffle that ships today.",
            defn.id,
        )
        # Repoint each biome's pool FIRST: an entity_ref is only meaningful if
        # the biome streams that prefab, and this is what makes it do so.
        for biome, cast in sorted(casts.items()):
            pool = _emit_pool(biome, cast, out_dir, defn.id)
            if pool is not None:
                written.append(pool)

    assignment = _assignment(defn.id, groups, casts, entity, mix, seed)
    changed = 0
    index = EP.enemy_index()
    for enemy_id, new_entity in sorted(assignment.items()):
        paths = _override_one(enemy_id, new_entity, weight, out_dir, defn.id)
        written += paths
        if paths and new_entity.lower() != index[enemy_id]["entity"].lower():
            changed += 1
    _log.info(
        "enemy %s/%s: scope %d retail def(s) across %s — %d repointed, "
        "%d file(s) (entity=%s, mix=%s, seed=%s, weight=%s)",
        mod_id, defn.id, len(assignment), ", ".join(groups), changed,
        len(written), entity, mix, seed, weight,
    )
    return written
