---
title: Rewards
description: What the reward system actually decides (spawned chests, not offered cards), the fully decoded rewarddef grammar, and why a type-count ban is unreliable in-game.
---

:::note
Status: cooked grammar fully decoded and deserializer-verified; `reward` SDK kind
ships at confidence `experimental`. Its **ban lever is known-unreliable** — see the
roll-handler section. Class `oCDtRewardDefinition`, glob `*.rewarddef.ot`.
:::

Loader `RewardDef_RegisterAssetLoader` = `FUN_140323b60` (label "Reward
definition"). Codec `cooked_schemas.definitions.RewardDefinitionHandler`
(`rewarddef.json`) — byte-stable round-trip over all 9 retail files
(`test_rewarddef_roundtrip`). Rows fully editable: items, entity refs, tier bands,
flag filters, min/max counts.

## What this system is — and isn't

`Reward_GenerateAndDistribute` runs at level load ("Level load - Generate
rewards") and decides **which reward ENTITY spawns at each reward spawn point** —
chests, astrolabs, dream crystals (`Objects_*\*.entity.ot`).

It does **not** pick the talent/item cards offered when a chest opens or the
player levels up. That draw comes from the magical-object pool (the LiveOps
`versiondef` MO vector — see [Custom items](/guides/custom-items/)). So a
per-item/talent **card** ban lives in the MO pool; this system is the lever for
reward-object **placement**.

## How the roll works

`_InitAllRewards` → `Distribute` → "Fill remaining rewards on random slot".
Seeded ("Seed : {0} ; Base seed {1}") and host-authoritative deterministic
([Multiplayer](/reverse-engineering/multiplayer/)) — a per-peer runtime filter
desyncs MP, so edits must be data-level. After the roll, level load posts a
`GENERATE_REWARDS` `oCGameNamedEvent` via `NamedEvent_Dispatch` and drains the
context queue (`EventQueue_Drain`, ctx+0x1c0).

Candidates are level entities carrying
`oCDtRewardEntitySelectorToSpawnEntityCpnt` ("reward spawners"). Per spawner a
**value** f32 is lazily rolled and cached at spawner+0x68. A spawner matches an
`oCItem` row iff:

1. `oCItem.min <= value <= oCItem.max` (runtime `oCItem+0xb0` / `+0xb4`)
2. `CustomFlagList_ContainsAll(settings+0x100, oCItem+0xc0)` — required flags
3. `!CustomFlagList_ContainsAny(settings+0x100, oCItem+0xd8)` — excluded flags

Flag lists are string sets: `{char* name, u32 len}` entries, 0x18 stride, data at
`+0x8`, count at `+0x10`; compared by length + memcmp. **Every shipping rewarddef
has all flag lists empty** — the mechanism exists but retail data doesn't use it,
so a mod can claim flag names freely.

## Cooked grammar

Recovered from the actual deserializers and byte-verified against the
`Camp_Rewards_Avalon` and Refugees files. Three structural facts apply to **all**
cooked defs:

1. **`AABB1111`/`AABB2222` are section separators** that `cooked.parse` already
   strips — not node open/close inside a payload. Nested sub-objects each get
   their own section; references between them are u32 sub-object ids (order of
   sub-object sections).
2. **Section 0 is a sub-object class directory**: `{u32 count, count × u32
   class-table-index}`, one entry per sub-object section, naming its class.
3. **Field presence is version-gated** per class via the header class table
   (`Serializer_GetClassVersion` by class hash — the codec parses these as
   `classes[].version_*`). A typed codec must gate optional fields the same way.

```
oCDtRewardDefinition (hash 0x176f164e, LAST section):
    u32 res? + u8 base_a + u8 base_b      # oCDtDefinition base (v1+ bools @+0x285/+0x284)
    u32 count, count × u32 sub-object id  # -> the oCType rows (runtime vector @def+0x288)
    v1+: u8                                # unpinned bool

RewardDefInternal::oCType (0x176f4fdc):
    u32 count, count × u32 sub-object id  # -> oCItem rows ({ptrs @+0x8, count @+0x10})
    v1+: u8 use_float; if 0: u32 n (min=max=n) else f32 legacy_weight (1.0)
    v2+: u32 min_count (+0x18), u32 max_count (+0x1c)

RewardDefInternal::oCItem (0x176f5023):
    resource-ref { lstr "EntitySettings", lstr entity path }      # @+0x8
    f32 value_min (+0xb0), f32 value_max (+0xb4)                  # tier band over 0..1 roll
    v1+: inline oCCustomFlagFilter (+0xb8)                        # required @+0xc0, excluded @+0xd8
    v2+: resource-ref (+0x40)   # JSON _ref_b — LOCKED-variant entity on chest rows
    v4+: resource-ref (+0x78)   # JSON _ref_c — empty in retail
    v5+: u32 enum <7            # JSON _kind — 1=chest, 3=astrolab, 4=dream crystal

oCCustomFlagFilter (0x15a9d9bf): inline oCCustomFlagList required (+0x8), excluded (+0x20)
oCCustomFlagList  (0x15a9d9be): u32 count, count × lstr

candidate side — oCDtRewardEntitySelectorToSpawnEntityCpntSettings (0x1740e3e9),
cooked in the reward object's *.entity.ot settings:
    v<3: legacy discarded resource-ref
    v1+: inline oCCustomFlagList @+0x100   # spawner flags, matched vs the oCItem filter
    v2+: u32 enum <4 @+0xf8, v3+: u32 enum <2 @+0xfc   # unpinned (likely value-source mode)
```

The "Reward type {}" debug index is the position in the `oCType` row list; a
"category" is an `oCType` row's `oCItem` set.

## Ban levers (data-level, MP-safe)

- **Ban a reward object** — remove its index from every `oCType` row that lists
  it, or set `value_min > value_max`.
- **Ban a category** — remove/empty an `oCType` row, or zero its min/max counts.
- **Flag-based suppression** — add a flag string to an `oCItem` excluded list;
  only spawners whose settings carry that flag are suppressed. The spawner side
  must be authored too, so this is for mod content, not for banning retail objects.
- **Per-item/talent card ban** — not this system: remove the entry from the
  LiveOps `versiondef` MO vector. That de-registers it from the offer pool but
  also hides it from the compendium.

## SDK kind

`reward` (`sdk/kinds/rewards.py`) takes `base` + `ban` (entity substring → drop
from categories; a locked-variant `_ref_b` match clears the ref, so chests spawn
unlocked only) + `counts` (`{category: [min, max]}`; `[0,0]` bans the category).
It emits an **override at the retail decoded path**, not an additive def.

## Why the type-count ban did NOT work in-game

A playtest shipped a `reward` mod emptying the basic-chest reward type
(min=max=0, items=[]) across all 6 `Camp_Rewards` defs. The output was
byte-correct and installed — **chests still spawned.** Decompiling the roll
handler explains it: there are two independent placement blocks with two def
sources.

- **Block 1 — reward_types-driven, count-gated.** Walks a def's reward_types
  vector at `def+0x288`/`+0x290`. Per type: `min_count @type+0x18`,
  `max_count @type+0x1c`; candidate items from `type+0x08`/`+0x10`; each item has
  an **exclude byte at `item+0x30`** (nonzero ⇒ skipped) and a tag match at
  `item+0xc0`/`+0xd8` vs `spawner+0x100`. Emptying a type does yield 0 spawns
  *here*. But the def list it walks is built from globals — a runtime reward
  registry, not the `Camp_Rewards` file pointer directly.
- **Block 2 — guaranteed/forced, count-BYPASSING.** Uses a different def
  (scene-context `param_1[0x15]` = game-context `+0xa8`) with its own collections
  at `+0xe0`/`+0xf0`/`+0x110` and count loops at `+0x70`/`+0x7c`. It never reads
  reward_types min/max, so a "guaranteed" chest ignores the type-count edit.

:::caution
A count/type edit is **not a reliable ban.** The levers that do bind — item
exclude byte, removing the entity from the pool, the tag filter — bind Block 1
only. Banning a Block-2 guaranteed reward needs the context `+0xa8` def.
:::

## Open

1. Runtime loader dump to close this: hook the roll handler, log the Block-1 def
   list and the context `+0xa8` def, dump each one's `+0x288` reward_types and
   whether the basic-chest type is present or guaranteed. That pins whether the
   failure is a def-identity miss (Block 1) or a Block-2 placement.
2. Prototype versiondef MO-vector entry removal for the card-level ban, and check
   whether the compendium side effect is acceptable.
