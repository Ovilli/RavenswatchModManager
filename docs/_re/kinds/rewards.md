# Rewards & banning talents/items (#13)

The level-up / chest offer pool. Heredos wishlist #13 ("ban some talents or items").

Class: `oCDtRewardDefinition`, asset glob `*.rewarddef.ot` (loader
`RewardDef_RegisterAssetLoader` = `FUN_140323b60`, label "Reward definition").
Codec: `cooked_schemas.definitions.RewardDefinitionHandler` (`rewarddef.json`) — TYPED
2026-07-05, byte-stable round-trip over all 9 retail files (`test_rewarddef_roundtrip`).
Rows fully editable: items, entity refs, tier bands, flag filters, min/max counts.

## What this system actually is (corrected 2026-07-05)

`Reward_GenerateAndDistribute` (`FUN_1401e9020`) runs at **level load** ("Level load -
Generate rewards") and decides **which reward ENTITY spawns at each reward spawn point** —
chests, astrolabs, dream crystals (`Objects_*\*.entity.ot`). It does **not** pick the
talent/item cards offered when a chest opens or the player levels up; that draw comes from the
magical-object pool (LiveOps `versiondef` MO vector, see [[item-clone-pipeline-verified]]).
So for a **per-item/talent ban** (the real #13) the lever remains the MO pool. This system is
the lever for **reward-object placement** (e.g. ban locked chests, force tier-3 astrolabs).

## How the roll works

`_InitAllRewards` → `Distribute` → "Fill remaining rewards on random slot". Seeded
("Seed : {0} ; Base seed {1}"), host-authoritative deterministic ([[multiplayer-netcode]]) —
any per-peer runtime filter desyncs MP; edits must be data-level. After the roll, level load
posts a `GENERATE_REWARDS` `oCGameNamedEvent` via `NamedEvent_Dispatch` and drains the context
queue (`EventQueue_Drain`, ctx+0x1c0). (`FUN_14005c510` / `FUN_14003b350` are NOT handlers —
they are per-TU static initializers interning the "GENERATE_REWARDS" name into the CRC32 event
registry; the old note was wrong.)

Candidates = level entities carrying `oCDtRewardEntitySelectorToSpawnEntityCpnt`
("reward spawners"). Per spawner a **value** f32 is lazily rolled/evaluated (cached at
spawner+0x68; from a GUID'd curve/property via vtable+0x48, else a property read). A spawner
matches an `oCItem` row iff:

1. `oCItem.min <= value <= oCItem.max` (runtime oCItem+0xb0 / +0xb4)
2. `CustomFlagList_ContainsAll(settings+0x100, oCItem+0xc0)` — required flags (`FUN_140669cc0`)
3. `!CustomFlagList_ContainsAny(settings+0x100, oCItem+0xd8)` — **excluded flags = the
   suppress field** (`FUN_140669de0`)

Flag lists are string sets: `{char* name, u32 len}` entries, 0x18 stride, data @+0x8,
count @+0x10; compared by length+memcmp.

**Suppress-field question RESOLVED:** the per-candidate suppress mechanism is the
`oCCustomFlagFilter` (required + excluded `oCCustomFlagList`) on each `oCItem` row, matched
against the spawner settings' own flag list @+0x100. **Every shipping rewarddef has all flag
lists empty** — the mechanism exists but retail data doesn't use it, so a mod can claim flag
names freely without colliding with the base game.

## Cooked `*.rewarddef.ot` grammar (FULLY decoded 2026-07-05, deserializer-verified)

Recovered from the actual deserializers (`RewardDef_Deserialize` FUN_140323bc0 slot 3 of the
class vftable, plus per-class `*_Serialize`), byte-verified against Camp_Rewards_Avalon and
Refugees files. Three structural discoveries that apply to ALL cooked defs:

1. **The `AABB1111`/`AABB2222` markers are section separators** the codec's `cooked.parse`
   already strips — NOT node open/close inside a payload. Nested sub-objects each get their own
   section; references between objects are **u32 sub-object ids** (order of sub-object
   sections).
2. **Section 0 is a sub-object class directory**: `{u32 count, count × u32 class-table-index}`
   — one entry per sub-object section, naming its class. Camp: 13 = `[4×4, 5×9]` = 4 `oCType`
   + 9 `oCItem` (class-table indices 4/5). The old "leading 4/5 vector mystery" and the older
   "tail = count+indices" decode were both misreadings of this directory.
3. **Field presence is version-gated** per class via the header class table
   (`Serializer_GetClassVersion` by class hash — the codec already parses these as
   `classes[].version_*`). A typed codec must gate optional fields the same way.

Per-class body grammar (each sub-object section starts with `u32 class-table-index`):

```
oCDtRewardDefinition (hash 0x176f164e, LAST section):
    u32 res? + u8 base_a + u8 base_b      # oCDtDefinition base (v1+: the two bools @+0x285/+0x284)
    u32 count, count × u32 sub-object id  # -> the oCType rows (runtime vector @def+0x288)
    v1+: u8                                # unpinned bool

RewardDefInternal::oCType (0x176f4fdc):
    u32 count, count × u32 sub-object id  # -> oCItem rows (runtime {ptrs @+0x8, count @+0x10})
    v1+: u8 use_float; if 0: u32 n (min=max=n) else f32 legacy_weight (1.0)
    v2+: u32 min_count (+0x18), u32 max_count (+0x1c)

RewardDefInternal::oCItem (0x176f5023):
    resource-ref { lstr "EntitySettings", lstr entity path }      # @+0x8
    f32 value_min (+0xb0), f32 value_max (+0xb4)                  # tier band over 0..1 roll
    v1+: inline oCCustomFlagFilter (+0xb8)                        # required @+0xc0, excluded @+0xd8
    v2+: resource-ref (+0x40)   # JSON _ref_b — LOCKED-variant entity on chest rows
                                #   (e.g. Basic_Chest_T1 -> Basic_Chest_Locked_T1); empty elsewhere
    v4+: resource-ref (+0x78)   # JSON _ref_c — empty in retail
    v5+: u32 enum <7            # JSON _kind — observed 1=chest, 3=astrolab, 4=dream crystal

oCCustomFlagFilter (0x15a9d9bf): inline oCCustomFlagList required (+0x8), excluded (+0x20)
oCCustomFlagList  (0x15a9d9be): u32 count, count × lstr

candidate side — oCDtRewardEntitySelectorToSpawnEntityCpntSettings (0x1740e3e9),
cooked in the reward object's *.entity.ot settings:
    v<3: legacy discarded resource-ref
    v1+: inline oCCustomFlagList @+0x100   # the spawner's flags, matched vs oCItem filter
    v2+: u32 enum <4 @+0xf8, v3+: u32 enum <2 @+0xfc   # unpinned (likely value-source mode)
```

"Reward type {}" debug index = position in the oCType row list; a "category" = an oCType row's
oCItem set (e.g. Camp_Avalon: [11,12], [8,9,10], [5,6,7], [4]). index→category fully derivable
per def.

## Ban levers (all data-level, MP-safe)

- **Ban a reward object** — remove its index from every `oCType` row that lists it (or set
  `value_min > value_max`). E.g. drop `Avalon_Basic_Chest_Locked_T2` from camp rewards.
- **Ban a category** — remove/empty an `oCType` row (or zero its min/max counts).
- **Flag-based suppression** — add a flag string to an `oCItem` excluded list; only spawners
  whose settings carry that flag are suppressed. Needs the spawner-settings side authored too
  (settings flag list @+0x100, in the entity's `RewardEntitySelectorToSpawnEntityCpntSettings`)
  — retail lists are empty, so this is for mod-authored content, not banning retail objects.
- **Per-item/talent card ban (real #13)** — NOT this system: remove the entry from the LiveOps
  `versiondef` MO vector @off 0x4590 ([[item-clone-pipeline-verified]]). De-registers it from
  the offer pool but also hides it from the compendium; needs the same care as item
  registration.

## Next steps

1. ~~Type the rewarddef body~~ DONE 2026-07-05: `RewardDefinitionHandler`, 9/9 byte-stable.
   ~~`reward` SDK kind~~ DONE same day: `sdk/kinds/rewards.py` — `kind="reward"`,
   fields `base` + `ban` (entity substring → drop from categories; locked-variant
   `_ref_b` match → clear ref = chest spawns unlocked only) + `counts`
   ({category: [min,max]}, `[0,0]` bans category). Emits an OVERRIDE at the retail
   decoded path (not additive). Confidence `experimental` — needs in-game playtest.
2. For the card-level ban, prototype versiondef MO-vector entry removal (reuse the item
   pipeline's versiondef writer) and check whether the compendium side-effect is acceptable or
   needs a separate compendium-list re-add.
3. ~~Pin the leading u32-vector semantics~~ SOLVED: it is the sub-object class directory
   (section 0), maintained automatically when adding/removing rows. Remaining unpinned trivia:
   rewarddef v1 bool, selector-settings enums — pass through verbatim. oCItem `_kind` enum
   now empirically pinned (1=chest, 3=astrolab, 4=crystal); `_ref_b` = locked chest variant.
