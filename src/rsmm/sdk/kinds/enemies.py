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
    "cross_biome",
)


def _enemy_class() -> str:
    return "oCDtEnemyDefinition"


def _load_base_cooked(base_id: str) -> bytes | None:
    """Return the cooked bytes of a vanilla enemy def, or None if no such
    enemy ships under the in-repo enemy-definition tree."""
    p = _ENEMY_DIR / f"{base_id}{_ENEMY_GEN_SUFFIX}"
    return p.read_bytes() if p.is_file() else None


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
            f"enemy {defn_id}: no enemy definitions under {EP.ENEMY_DIR} — "
            f"mode=\"override\" needs the cooked corpus "
            f"(python scripts/extract_uncooked.py)."
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
                 cross_biome: bool) -> dict[str, list[str]]:
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
    raw = (DATA_DIR / "uncooked" / Path(*rel.split("/"))).read_bytes()
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

    Draws from the biome's own cast, so the result is streamed there by
    construction rather than by a check that could be forgotten.
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
    src = _ENEMY_DIR / f"{enemy_id}{_ENEMY_GEN_SUFFIX}"
    try:
        cf = cooked.parse(src.read_bytes())
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
    if new_bytes == src.read_bytes():
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
        p = DATA_DIR / "uncooked" / Path(*rel.split("/"))
        if not p.is_file():
            raise SchemaNotMined(
                f"enemy {defn_id}: {rel} is missing from the corpus, so the "
                f"preload closure for {enemy_id} cannot be assembled "
                f"(python scripts/extract_uncooked.py)."
            )
        lines |= set(RC.parse(p.read_bytes()))

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

    if entity is not None and mix is not None:
        raise ContentError(
            f"enemy {defn.id}: 'entity' (one fixed prefab) and 'mix' "
            f"(randomised) are mutually exclusive — pick one."
        )
    if entity is None and mix is None:
        raise ContentError(
            f"enemy {defn.id}: mode=\"override\" needs either entity = "
            f"\"Enemies\\\\...\" (turn the scope into one monster) or "
            f"mix = \"random\" | \"shuffle\" with a seed."
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

    casts = _biome_casts(defn.id, groups, entity, seed, cross_biome)

    written: list[Path] = []
    if cross_biome:
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
