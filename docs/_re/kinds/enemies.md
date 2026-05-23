# Custom enemies (non-boss) — RE findings

> Scope: non-boss `oCDtEnemyDefinition` + the camp/tribe machinery that
> turns it into actual mob spawns. Bosses share the class but route
> through `oCDtBossTimerUiControllerEntityCpnt` and are out of scope
> here. Derived from `Ravenswatch.exe` bulk decompilation under
> `docs/_re/out/decompiled_all/` cross-checked against the live Ghidra
> MCP session. Anything not bit-for-bit verified is marked
> `TODO: confirm`.

## Class registry — anchors

| Class | UID | Size | Library | Cooked ext |
|---|---|---|---|---|
| `oCDtEnemyDefinition` | `0x176debb7` | `0x350` | `0x1414118c0` | `*.enemydef.ot` |
| `oCDtEnemyTribeDefinition` | — | (TBD) | `0x141411200` | `*.enemytribedef.ot` |
| `oCDtEnemyCampTierDefinition` | `0x176e18f8` | `0x2a0` | `0x141411560` | `*.enemycamptierdef.ot` |
| `oCDtEnemyCampDifficultyDefinition` | — | — | `0x141411710` | — |
| `oCDtEnemyCampEntitySelectorToSpawnEntityCpntSettings` | `0x16b7d175` | (≥`0x440`) | — | — |
| `oCDtEnemyCampEntitySelectorToSpawnTribeEntrySettings` | `0x16b81d80` | — | — | — |
| `oCDtEnemyFlagListEntitySelectorToSpawnEntityCpntSettings` | `0x17019bf9` | — | — | — |

Registrar for `oCDtEnemyDefinition`: `FUN_140229990` — confirms
size `0x350`, ctor-thunk `LAB_140244930` (wraps `FUN_1401db800`),
schema-declarer `FUN_14030a190` (just sets display name `"Enemy
definition"` and extension `*.enemydef.ot`; full field schema lives in
the deserializer's UID-versioned reader, e.g. `FUN_14030d010`).

## `oCDtEnemyDefinition` field layout (size `0x350`)

Derived from the ctor `FUN_1401db800` (`0x1401db800`), the dtor
`FUN_1401db9b0`, and the Stage-3 filter `FUN_14030b000` which reads
several offsets directly. Indices below are 8-byte `param_1[i]`
notation; the corresponding byte offset is `i * 8`.

| Offset | Index | Field | Source |
|---|---|---|---|
| `+0x000` | `[0]` | vftable chain (oISerializable → oIResource → oCDtDefinition → oCDtEnemyDefinition) | ctor |
| `+0x008..+0x280` | `[1..0x50]` | base-class members (oIResource ref-count at `+0x10`; oCDtDefinition's name/hash at `+0x270..+0x284`) | ctor |
| `+0x284` | — | `{u8 flagA=1, u8 flagB=1}` (oCDtDefinition flags) | ctor (`0x101`) |
| `+0x288` | `[0x51]` | **`displayName` / resource path** (`char*`, init `&DAT_140eb46d0` empty-string sentinel) | ctor |
| `+0x290` | `[0x52]` | name-hash for `[0x51]` (init `0x80000000` "unresolved") | ctor |
| `+0x294` | — | `u32` reserved (init 0) | ctor |
| `+0x298` | `[0x53]` | **`entityAsset` ref** (`char*` path to visual entity, init empty sentinel) | ctor |
| `+0x2a0` | `[0x54]` | name-hash for `[0x53]` (init `0x80000000`) | ctor |
| `+0x2a4` | — | `u32` reserved | ctor |
| `+0x2a8` | `[0x55]` | resource-list pointer (init `DAT_141446f38`, global empty list) | ctor |
| `+0x2b0` | `[0x56]` | `u8 isElite_or_excluded` (init `1`) — Stage-3 filter `FUN_14030b000` reads `*(char*)(enemy + 0x2b0)` to skip enemies when `param_2+8 != 0` (a special-spawn pass) | ctor + filter |
| `+0x2b8` | `[0x57]` | **`MaxOccurence[]` data ptr** (vector of `EnemyDefInternal::oCDtEnemyDefinitionMaxOccurence`, 16 B per entry; deserializer `FUN_14030d010` writes them here) | filter line 263 |
| `+0x2c0` | `[0x58]` | **`MaxOccurence` count (u32)** + immediately above this also the `oCCustomFlagList::vftable` of the **tag list** (the ctor writes `oCCustomFlagList::vftable` to `[0x58]`; the filter reads `count` from `+0x2c0`). Conflict: ctor and filter disagree. See note. | ctor + filter |
| `+0x2c8` | `[0x59]` | flag-list data ptr (init 0) | ctor |
| `+0x2d0` | `[0x5a]` | flag-list count (init 0) | ctor |
| `+0x2d8` | `[0x5b]` | flag-list capacity (init 1) | ctor |
| `+0x2dc` | — | `float minTierForSpawn` (init `0x3dcccccd` = 0.1f) — filter compares against `local_1b8` (request tier) | ctor + filter line 328 |
| `+0x2e0` | — | `u64` tier-range pair `{u32 minTier, u32 maxTier}` (init `5`) — filter checks `param_2+0xc` against this `u64` (low=min, high=max) | ctor + filter line 326 |
| `+0x2e8` | `[0x5d]` | secondary entity-asset name (init empty sentinel) | ctor |
| `+0x2f0` | `[0x5e]` | hash for `[0x5d]` | ctor |
| `+0x2f4` | — | `u32` reserved | ctor |
| `+0x2f8` | `[0x5f]` | tertiary asset name | ctor |
| `+0x300` | `[0x60]` | hash | ctor |
| `+0x308` | `[0x61]` | resource-list pointer (init `DAT_141447128`) | ctor |
| `+0x310` | `[0x62]` | `u8 hasTribe` (init 1) — filter line 346 reads `*(char*)(enemy + 0x310)`: if zero, the tribe-membership check at `+0x318` is skipped | ctor + filter |
| `+0x318` | `[0x63]` | `oCDtEnemyTribeDefinition*` (raw pointer to tribe) — filter compares against `local_170` (request tribe list) | ctor + filter line 349 |
| `+0x320` | — | `float weightA` (init `-1.0f` = `0xbf800000`) — filter line 478 reads `*(float*)(enemy + 800)` (=`+0x320`) as default weight | ctor + filter |
| `+0x328` | `[0x65]` | **tier-weight table A** data ptr — `{u32 tier, float weight}` pairs, 16 B per entry; iterated lines 481-487 picking the largest tier `<= request` | ctor + filter |
| `+0x330` | `[0x66]` | tier-weight table A count (u32) at `+0x330` | filter line 481 |
| `+0x338` | — | `float weightB` (init `-1.0f`) — alternate spawn-mode weight | ctor |
| `+0x340` | `[0x68]` | **tier-weight table B** data ptr (16 B/entry, same shape as table A) | filter line 494 |
| `+0x348` | `[0x69]` | tier-weight table B count (u32) | filter line 497 |

Notes:

- `+0x2c0` vs `+0x2b8`: the ctor allocates an `oCCustomFlagList`
  in-place starting at `+0x2c0` (vftable @ `[0x58]` = `+0x2c0`,
  data ptr @ `[0x59]` = `+0x2c8`, count @ `[0x5a]` = `+0x2d0`).
  The Stage-3 filter `FUN_14030b000` instead reads
  `data = *(qword*)(enemy + 0x2b8)` and `count = *(u32*)(enemy + 0x2c0)`.
  The most consistent reading is: **the `oCCustomFlagList` body
  embeds an extra `void*` at `+0x2b8` (one before the vftable) which
  is the tag-list data pointer**, while `+0x2c0` (the location the
  ctor labels as the vftable) shadows as the count. The
  `oCCustomFlagList` is an `oISerializable` subclass and would
  normally have its vftable at offset 0 of itself; here the field at
  `+0x2c0` is documented as the vftable because the ctor expresses
  it that way, but the filter clearly treats `+0x2b8`..`+0x2c0` as
  `{ptr, count}`. # TODO: confirm by inspecting an actual cooked
  enemy record on disk.
- `EnemyDefInternal::oCDtEnemyDefinitionMaxOccurence` (vector at
  `+0x328` / `+0x340`) — each entry is `{u32 tier, float weight, u64 _}`
  initialized as `tier=0, weight=-1.0f` in the deserializer
  (`FUN_14030d010` lines 152-154). The filter loop interprets it as
  `tier@+0x8, weight@+0xc` of each 16-byte slot.
- `+0x340` table is keyed on the same tier value but used when
  `param_2+8 == 2` (a "secondary spawn pass" — likely camp-tier 2
  selection or boss-tier). `+0x328` is used for the default pass.
- "`is_elite`" semantically maps to **tag membership in the
  `oCCustomFlagList`** at `+0x2c0` rather than a dedicated bit. The
  vanilla camp selector at `FUN_1403225a0` filters by exactly that
  list via two `oCCustomFlagFilter` instances. # TODO: confirm the
  exact tag string used for "elite".

## Camp pipeline (data flow)

```
oCDtEnemyDefinition         ──┐
   (one stat block + tags)    │
                              ▼
oCDtEnemyTribeDefinition (one tribe groups N enemies)
   - +0x288 oCCustomFlagList (tribe-wide tag set)
   - +0x2b8 vector<EntryRef>  (the actual enemy-def slot list)
                              │
                              ▼
oCDtEnemyCampTierDefinition (size 0x2a0)
   - +0x290 vector<TribeEntryRef>  (which tribes show up at this tier)
                              │
                              ▼
oCDtEnemyCampDifficultyDefinition (curves multipliers per tier)
                              │
                              ▼
oCDtEnemyCampEntitySelectorToSpawnEntityCpntSettings (UID 0x16b7d175)
   - +0x0f8 oCCustomFlagFilter A  (must-have / must-not-have tags)
   - +0x100 .. +0x118  positive / negative oCCustomFlagList
   - +0x400 oCCustomFlagFilter B  (second pass, elite override?)
   - +0x408 .. +0x420  positive / negative lists
   - several oCResourceRef + float weights (10.0f, 20.0f, 1.0f)
     stored interleaved via FUN_14080d560 / FUN_14080d5d0
```

Two flag-filter slots inside the camp selector (`A` at `+0xf8`, `B`
at `+0x400`) explain how a single camp can express
"normal-enemy filter + elite filter" without a separate class — the
selector evaluates both with different weights. Adding a custom
enemy reduces to "make sure your tag list matches **filter A** of
the camps you want to appear in, and stay clear of **filter B**'s
negative list."

## Stage-3 filter (`FUN_14030b000`)

This is the function invoked during the level-load pipeline at
**stage 3 ("Enemies settings loading")**. It walks the candidate
list `param_1` (vector of `oCDtEnemyDefinition*`) and **removes**
entries that fail any of:

1. `(*(char*)(enemy + 0x2b0)) != 0` when `param_2+8 != 0` — the
   "exclude-from-special-spawn" flag.
2. Tier check: `request_tier ∈ [enemy.+0x2e0_lo, enemy.+0x2e0_hi]`.
3. Minimum tier float: `enemy.+0x2dc <= request_tier_float`.
4. Tag include/exclude against an `EnemyDefInternal::SearchFilter`
   built locally (positive list at `local_1a0`, negative at
   `local_188`). Internally calls `FUN_140652120` (set-intersection
   non-empty?) and `FUN_140652240` (set-intersection empty?).
5. Tribe whitelist: if `enemy.+0x310 == 0` skip; else
   `enemy.+0x318` (the tribe pointer) must be in the request's
   accept list (`local_170`).
6. Weight derivation: pick the largest `(tier, weight)` from
   `enemy.+0x328[+0x330]` (default pass) or `enemy.+0x340[+0x348]`
   (special pass) whose `tier <= request_tier`; if the resulting
   weight is `0.0`, the entry is dropped.

This is the **only** filter standing between a registered enemy
def and its appearance in a camp's roster. There is no separate
opt-in list — registration into `oCTLibrary<oCDtEnemyDefinition>`
plus the right tag set is sufficient. This matches the MOD_HOOKS.md
prediction: "Adding tags to a custom `oCDtEnemyDefinition` is
sufficient to include it."

## Insertion recipe — minimal moving parts

To make a custom enemy `me_orc_pyro` spawn in vanilla "goblin"
camps:

1. **Author an `oCDtEnemyDefinition` cooked record** with
    - `+0x288` name = `"me_orc_pyro"` (path-shaped resource name)
    - `+0x298` entityAsset = path to a visual entity (clone of
      vanilla goblin entity if nothing custom)
    - `+0x2dc` minimum tier float (0.1f matches default)
    - `+0x2e0` tier range (e.g. `{1, 5}`)
    - `+0x2c0` oCCustomFlagList containing the same tags as the
      vanilla goblin (e.g. `"tribe.goblin"`, `"size.small"`)
    - `+0x318` tribe pointer set (or fixup-by-name) to the goblin
      tribe def, with `+0x310 = 1`
    - `+0x328` tier-weight table populated, e.g. `{tier=1, w=1.0}`,
      `{tier=3, w=0.5}`
    - HP / damage live on the **`oCEntitySettings`** referenced by
      `+0x298` (the visual-entity field), **not** on the enemy
      definition itself. Adjusting them requires editing the
      referenced entity, not the enemy def. # TODO: confirm.
2. **Insert it into `oCTLibrary<oCDtEnemyDefinition>` (singleton
   `0x1414118c0`)** by calling vftable slot 3
   (`oIResourceManager::FindOrLoad`) with an `oCResourcePath`
   `{name="me_orc_pyro", hash=fnv1a(name), parent=goblin_tribe_path}`.
3. **Insert a `TribeEntryRef`** into the goblin tribe's vector at
   `+0x2b8/+0x2c0` of `oCDtEnemyTribeDefinition` — this is what
   makes the camp selector consider it during the tribe pass.
4. **Optional: text-bank override** for the visible enemy name —
   namespaced `RSMM_<modid>_<id>_name` in each locale's
   `lang/<locale>.toml`. The asset that references the text key
   lives on the visual entity (`+0x298`), so cloning that entity
   and pointing its `name_key` field at the namespaced override is
   required if a custom name is desired.

Steps 2-4 are what `enemies.py` builds. Patching is done at apply
time by `apply_mods.py` (cooked-record write + library injection
via the loader DLL).

## Still unknown / TODO

- Exact bit positions of HP / damage / move-speed. The enemy def
  doesn't carry them directly; they live on the referenced
  `oCEntitySettings` at `+0x298`. The size-0x350 budget is mostly
  spent on tag lists, tier curves, and resource refs.
- AI profile reference — likely another `oCResourceRef` slot,
  probably at `+0x2e8`/`+0x2f8` ("secondary entity asset"). # TODO:
  confirm by diffing two vanilla enemy defs.
- `oCResourcePath` exact byte layout — the find-by-name path uses
  `{char* name, u32 name_hash, char* parent_path}` but the hash
  algorithm (FNV1a-like? bespoke?) is not 100% confirmed.
- `EnemyDefInternal::oCDtEnemyDefinitionMaxOccurence` field
  semantics beyond `(tier, weight)` — the 16-byte entry might
  hold extra padding or a third u32.
- Tag string vocabulary — vanilla tag names ("tribe.goblin",
  "size.small", "elite", ...) need to be enumerated by string-pool
  scan. # TODO.
