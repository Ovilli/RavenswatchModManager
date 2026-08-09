---
title: Items (magical objects)
description: Class layouts behind the magical-object drop chain — reward definitions, drop settings, selectors — and the pickup component the engine spawns.
---

:::note
Status: Tier-1 RE from live Ghidra MCP + headless decompilation. Fields marked
*provisional* are inferred from ordering, not proven by a string in the binary.

The **authoring** path is shipped and verified end-to-end in the SDK — a custom
magical item is a manifest plus `rsmm apply`. See
[Custom items](/guides/custom-items/). This page is the engine-side reference
behind it.
:::

## The chain

```
oCDtRewardDefinition                  data class
    |  referenced-by
    v
oCDtRewardEntitySelectorToSpawnEntityCpntSettings   per-drop selector
    |  owns
    v
oCCustomFlagList                      filter tags
    |
    v
oCDtEntityCpntMagicalObject           runtime component (pickup entity)
    |
    v
oCDtEntityCpntMagicalObjectsDropSettings   drop-table config (0xa50 bytes)
```

The "settings" type is the *authored* container referencing each magical object's
prefab; the runtime component is the instance the engine spawns for one pickup.

## Class registry

The schema addresses are **schema-declarer callbacks**, not deserialization
factories: each calls `MetaClass::SetDisplayName(name)`, writes flags into the
declarer state, then registers the field groups. Ctor/dtor/size live in a separate
registrar that walks `oCMetaClass_FindByKey` then `oCMetaClass_Alloc`.

| Class | UID | Size | Registrar | Schema cb | ctor | dtor |
|---|---|---|---|---|---|---|
| `oCDtRewardDefinition` | `0x176f164e` | `0x298` | `FUN_140237f40` | `FUN_14031a040` | `FUN_1401e3ca0` | `FUN_1401e3d50` |
| `oCDtEntityCpntMagicalObjectsDropSettings` | `0x168afca6` | `0xa50` | `0x140277790` | `FUN_1402d2290` | `FUN_1402d2310` | `FUN_1402d0cc0` |
| `oCDtEntityCpntMagicalObject` (runtime) | — | ≥ `0x2b0` | — (component, not registry-keyed) | — | `FUN_1401e0e10` | `FUN_1401e10f0` |
| `oCDtRewardEntitySelectorToSpawnEntityCpntSettings` | — | — | — | — | `FUN_1401e3e90` | — |
| `oCDtEntityCpntMagicalObjectSettings` (authoring) | — | ≥ `0xc00` | — | — | `FUN_1402ce2b0` | — |

## `oCDtRewardDefinition` (size `0x298`)

| Offset | Field | Notes |
|---|---|---|
| `+0x00` | vftable | |
| `+0x08..+0x20` | `oISerializable` slots | zeroed by ctor |
| `+0x30` low byte | `oIResource` flags | `& 0xe0` at ctor — high 3 bits preserved by caller |
| `+0x34` | refcount | set to `1` |
| `+0x3c` | resource state | `0` |
| `+0x40` | `oCResourcePath::name` | **the logical id lives here** once loaded |
| `+0x48` | `oCResourcePath::hash` | u32 |
| `+0x50` / `+0x58` / `+0x5c` | resource-list prev / next / count | |
| `+0x60..+0x260` | `oCDtDefinition` body | sub-records |
| `+0x270` | `oCDtDefinition` ptr | released in the dtor — likely display name / description |
| `+0x284` | `oCDtDefinition` flags | `0x0101` |
| `+0x288` | **entries** ptr | qword array, freed slot-by-slot in the dtor |
| `+0x290` / `+0x294` | entries length / capacity | |

The named slot at `+0x40`/`+0x48` is what `oIResourceManager::FindOrLoad` keys on.

For the **fully typed** rewarddef grammar (the section directory, per-class version
gating, `oCItem` rows) see [Rewards](/reverse-engineering/rewards/).

## `oCDtEntityCpntMagicalObject` (size ≥ `0x2b0`)

| Offset | Field |
|---|---|
| `+0x00` | vftable |
| `+0x18` | `EntityCpntValueSignal<bool>` — "is_active" |
| `+0x38` | `EntityCpntValueSignal<bool>` — "ever_spawned" |
| `+0x58..+0x68` | small int / flag block (low nibble of `+0x64` masked) |
| `+0x90..+0xf8` | three closure slots (signal binder header, ctx + del) |
| `+0x1f8` | `EntityCpntValueSignal<int>` — **rarity** *(provisional)* |
| `+0x218` | `EntityCpntValueSignal<int>` — **count** *(provisional)* |
| `+0x238` | `EntityCpntValueSignal<int>` — **level** *(provisional)* |
| `+0x290` | `oCCustomFlagList::vftable` — tag list |
| `+0x298..+0x2a8` | flag-list body |
| `+0x2ac` | `0xffffffff` sentinel |

The rarity / count / level labels come from ordering alone — no schema string in
the binary proves the mapping. Treat them as provisional until a save-game diff
confirms which signal carries which int.

## `oCDtEntityCpntMagicalObjectsDropSettings` (size `0xa50`)

High level only — the body is a 0x80-byte stride array built by
`_eh_vector_constructor_iterator_`.

| Offset | Field |
|---|---|
| `+0x00` | vftable |
| `+0x1f8` | array of 12 × 0x80-byte entries (drop-table rows) |
| `+0x3f8`, `+0x478`, … | further rows, pattern repeating |
| `+0x9d0` | `oCEntityCpntPicker` 1 |
| `+0xa10` | `oCEntityCpntPicker` 2 |
| `+0xa48` | tail |

The SDK does not synthesize new drop-table rows — it threads a new reward through
an existing one.

## `oCDtRewardEntitySelectorToSpawnEntityCpntSettings`

| Offset | Field |
|---|---|
| `+0x00` / `+0x08` | vftable (`oIEntitySelectorToSpawnEntityCpntSettings` first, then specialized) / secondary vftable |
| `+0xf8` / `+0x100` / `+0x104` | target name ptr (empty sentinel) / hash `0x80000000` / resolved flag |
| `+0x108` / `+0x110` / `+0x114` | parent path ptr / hash / resolved flag |
| `+0x118` | resolved `oCMetaClass*` = `DAT_141447bd0` (`oCDtRewardDefinition` meta) |
| `+0x120` low byte | enable flag (`1`) |
| `+0x130` | `oCCustomFlagList::vftable` |
| `+0x138..+0x148` | flag-list body |

So a selector pins to one named reward definition, its parent resource group, and
a tag filter.

## Engine-side insertion

Following the `oIResourceManager` slot-3 by-name lookup ABI:

1. **Register UID** — the `oCMetaClass` for `oCDtRewardDefinition` is
   `DAT_141447bd0`; its registrar static-inits before `main()`, so nothing is
   needed for the existing class. A *new* UID would require running the same
   `oCMetaClass_FindByKey → oCMetaClass_Alloc → set sizeof+align → SetDisplayName
   → register factory` sequence at boot.
2. **Construct** an `oCDtRewardDefinition` (or clone a vanilla one) and fill
   `+0x40` = `"rwd_<mod>_<id>"`, `+0x48` = name hash, the `oCDtDefinition` fields.
3. **Insert** into `oCTLibrary<oCDtRewardDefinition>` (singleton `0x141412e00`) via
   vftable slot 3 (`+0x18`, `FindOrLoad`) with an `oCResourcePath`. The library
   allocates an entry, links it into the `+0x150` head / `+0x148` tail list under
   the `+0x118` critical section, and returns a refcounted pointer.
4. **Selector** — for every drop site, the selector's target name must match the
   new reward's name, and its tag list must contain at least one tag matching the
   dropper's `oCCustomFlagFilter`.
5. **Magical object** — the pickup entity's own flag list at `+0x290` must overlap
   the drop-settings row's filter.

:::tip
In practice none of this is done at runtime. The shipped pipeline is asset-level:
a cooked def plus a `versiondef` magical-object vector entry plus a `UsedRscList`
registration, all emitted by the `item` kind. Runtime library injection stays a
fallback for cases assets can't reach.
:::
