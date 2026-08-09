---
title: Enemies
description: The enemy definition layout, the tribe roster that actually drives camp spawns, and why registering in UsedRscList is the entire contract for a custom enemy.
---

:::note
Status: load chain closed statically — a loaded enemy def **self-registers** into
its tribe's runtime roster, so the existing apply pipeline is sufficient. Scope is
non-boss `oCDtEnemyDefinition`; bosses share the class but route through the
BossTimer controller ([Bosses](/reverse-engineering/bosses/)).
:::

## Class anchors

| Class | UID | Size | Library | Cooked ext |
|---|---|---|---|---|
| `oCDtEnemyDefinition` | `0x176debb7` | `0x350` | `0x1414118c0` | `*.enemydef.ot` |
| `oCDtEnemyTribeDefinition` | `0x176dc2eb` | `0x2d8` | `0x141411200` | `*.enemytribedef.ot` |
| `oCDtEnemyCampTierDefinition` | `0x176e18f8` | `0x2a0` | `0x141411560` | `*.enemycamptierdef.ot` |
| `oCDtEnemyCampDifficultyDefinition` | — | — | `0x141411710` | — |
| `oCDtEnemyCampEntitySelectorToSpawnEntityCpntSettings` | `0x16b7d175` | ≥ `0x440` | — | — |
| `oCDtEnemyCampEntitySelectorToSpawnTribeEntrySettings` | `0x16b81d80` | — | — | — |
| `oCDtEnemyFlagListEntitySelectorToSpawnEntityCpntSettings` | `0x17019bf9` | — | — | — |

The registrar confirms size `0x350`; the schema-declarer only sets the display
name and extension — the full field schema lives in the deserializer's
UID-versioned reader.

## `oCDtEnemyDefinition` layout

`+0x288` and `+0x2e8` are **0x38-byte typed resource-ref blocks**:

```
{ char* name, u32 hash, char* parentPath, u32 hash2,
  void* classDescriptor @+0x20, u8 resolved @+0x28, void* resolvedPtr @+0x30 }
```

| Offset | Field |
|---|---|
| `+0x000` | vftable chain (`oISerializable → oIResource → oCDtDefinition → oCDtEnemyDefinition`) |
| `+0x008..+0x280` | base-class members (refcount `+0x10`; name/hash `+0x270..+0x284`) |
| `+0x284` | `{u8 flagA=1, u8 flagB=1}` — `oCDtDefinition` flags |
| `+0x288` | **entity ref block** (descriptor default `DAT_14146f740`, override `+0x2a8`, resolved-flag `+0x2b0`, resolved entity `+0x2b8`) |
| `+0x2c0` | `oCCustomFlagList` — vftable here, data `+0x2c8`, count `+0x2d0`, capacity `+0x2d8` |
| `+0x2dc` | `f32` minTier (init `0.1f`) |
| `+0x2e0` / `+0x2e4` | tier range `{min, max}` (init `{0,5}`) |
| `+0x2e8` | **tribe ref block** (tribe class descriptor at `+0x308`, resolved-flag `+0x310`, resolved `oCDtEnemyTribeDefinition*` `+0x318`) |
| `+0x320` | `f32` weightA (init `-1.0f`) — default weight |
| `+0x328` / `+0x330` | tier-weight table A: `{u32 tier, f32 weight}` pairs, 16 B/entry + count |
| `+0x338` | `f32` weightB (init `-1.0f`) — alternate spawn-mode weight |
| `+0x340` / `+0x348` | tier-weight table B + count |

:::caution[Superseded readings]
An earlier pass read `+0x2b8` as a `MaxOccurence` vector and `+0x2b0` as
`isElite`. Both were wrong: `+0x2b8` is the **resolved entity pointer** and
`+0x2b0` its resolved-flag. "Elite" is tag membership in the `oCCustomFlagList`,
not a dedicated bit.
:::

**HP / damage / move speed are not on the enemy def.** They live on the
`oCEntitySettings` referenced by the entity-ref block; the 0x350 budget is spent
on tag lists, tier curves and resource refs. Adjusting stats means editing the
referenced entity.

## Tribe layout

Flag list `+0x288`; **cooked** entry vector `+0x2a0`/`+0x2a8` (resolved by the
tribe post-load; empty in all 25 vanilla tribes); **runtime roster**
`+0x2b8`/`+0x2c0` (zero-init, written only by `EnemyDef_PostLoad`); tier
aggregates `+0x2c8` (min, FLT_MAX init), `+0x2cc` (max, -FLT_MAX), `+0x2d0` (u32
max tier-hi).

## Camp pipeline

```
oCDtEnemyDefinition         ──┐
   (one stat block + tags)    │
                              ▼
oCDtEnemyTribeDefinition (one tribe groups N enemies)
   - +0x288 oCCustomFlagList (tribe-wide tag set)
   - +0x2b8 runtime roster (the actual candidate list)
                              │
                              ▼
oCDtEnemyCampTierDefinition (which tribes show up at this tier, +0x290)
                              │
                              ▼
oCDtEnemyCampDifficultyDefinition (curves multipliers per tier)
                              │
                              ▼
oCDtEnemyCampEntitySelectorToSpawnEntityCpntSettings (UID 0x16b7d175)
   - +0x0f8 oCCustomFlagFilter A  (must-have / must-not-have tags)
   - +0x400 oCCustomFlagFilter B  (second pass, elite override?)
   - several oCResourceRef + float weights (10.0f, 20.0f, 1.0f)
```

The two filter slots explain how one camp expresses "normal-enemy filter + elite
filter" without a separate class. A custom enemy needs its tag list to match
**filter A** of the camps it should appear in, and to stay clear of **filter B**'s
negative list.

## The stage-3 filter

Invoked at level-load stage 3 ("Enemies settings loading"), it walks the candidate
vector and **removes** entries failing any of:

1. The resolved-flag/exclude check when the request is a special-spawn pass.
2. Tier check: `request_tier ∈ [tier_lo, tier_hi]`.
3. Minimum tier float: `enemy.minTier <= request_tier_float`.
4. Tag include/exclude against a locally built `EnemyDefInternal::SearchFilter`
   (set-intersection non-empty / empty helpers).
5. Tribe whitelist: if the tribe resolved-flag is 0 skip; else the resolved tribe
   pointer must be in the request's accept list.
6. Weight derivation: pick the largest `(tier, weight)` pair whose `tier <=
   request_tier` from table A (default pass) or table B (special pass); a
   resulting weight of `0.0` drops the entry.

This is the **only** filter between a registered enemy def and a camp roster.
There is no separate opt-in list.

## The candidate list is the tribe roster

The camp tier selector builds the candidate vector directly from the tribe's
roster, then hands it to the stage-3 filter:

```c
// tribe entry -> oCDtEnemyTribeDefinition*
FUN_1401c2fd0(&cand, tribe[+0x2b8], tribe_count[+0x2c0]); // candidates FROM tribe roster
FUN_1403194c0(&cand, &search_filter);                     // stage-3 trims by tier/tag/weight
```

Two consequences:

1. The stage-3 filter only **trims** what the roster holds — flags and tiers never
   *add* an enemy. Selection is tribe-roster-driven, not "flag-list selector by
   tag".
2. The roster at `+0x2b8` is **runtime-populated**, not read from the cooked tribe
   file. The cooked tribe's own entry vector deserializes to `+0x2a0` and ships
   `count == 0` in all 25 vanilla tribes — if `+0x2b8` were that vector, no enemy
   would ever spawn. **Patching the cooked tribe is useless** (wrong vector).

## The roster writer — enemies self-register

`EnemyDef_PostLoad` is the `oCDtEnemyDefinition` vftable slot at `+0x90`
(post-deserialize callback). It:

1. Resolves the tribe ref block via the generic `ResourceRef_Resolve` when the
   resolved-flag is 0, writing the live tribe pointer to `+0x318`. Resolution
   **loads the tribe def on demand** — tribes are excluded from the boot
   definitions scan.
2. If the tribe is loaded and valid, **push_backs self onto `tribe+0x2b8`/`+0x2c0`**
   — *the only roster write in the binary* — and folds the tier aggregates into
   `tribe+0x2c8`/`+0x2cc`/`+0x2d0`.
3. Registers the instance in the per-class registry via `Registry_RegisterInstance`;
   registries are enumerated by every selector.

What loads enemy defs at all is `InitialLoading_LoadAllDefinitions` (boot stage
"InitialLoading - Load all definitions"): it loads
`Versions/LiveOps5.versiondef.ot` first, then **directory-scans the `Definitions`
folder of the resource filesystem** (whose index is `UsedRscList.ot`) and creates
a load job for every definition file except 7 excluded classes. The tribe class is
excluded (lazy load); the enemy class is not.

:::tip[Contract for the apply step]
Registration in `UsedRscList.ot` — which `apply_mods.sync_usedrsclist` already
does with a 3-line record — is the **entire** contract. Boot scan → deserialize →
`EnemyDef_PostLoad` → tribe roster → camp tier selector candidate.
:::

The in-level spawner path (`Enemy_RuntimeSpawnPicker`) enumerates the **class
registry** rather than the tribe roster, filtered by an allowed-tribe pointer
list — so the registry registration in step 3 matters for both paths.

## Authoring recipe

1. Author an `oCDtEnemyDefinition` cooked record: name, entity ref (clone a
   vanilla enemy's entity if nothing custom), min tier, tier range, a
   `oCCustomFlagList` carrying the same tags as the vanilla enemy you want to sit
   beside, tribe ref pointing at the target tribe, and a sane tier-weight table.
2. Register it in `UsedRscList.ot` — nothing else.
3. Optional text-bank override for the visible name, namespaced
   `RSMM_<modid>_<id>_name`. The text key lives on the visual entity, so a custom
   name means cloning that entity and repointing its name key.

A historical custom enemy that never spawned had two confounds — a rewritten
`tribe_ref` and a spawn weight of `9999`. The SDK now guards both
(unknown-tribe reject, `SPAWN_WEIGHT_MAX`, cross-tribe warning).

## Open

- AI profile reference — likely another resource-ref slot; confirm by diffing two
  vanilla enemy defs.
- `oCResourcePath` byte layout: find-by-name uses `{char* name, u32 name_hash,
  char* parent_path}`, but the hash algorithm isn't confirmed.
- Tag string vocabulary — vanilla tag names need a string-pool scan to enumerate.
