# Rewards & banning talents/items (#13)

The level-up / chest offer pool. Heredos wishlist #13 ("ban some talents or items").

Class: `oCDtRewardDefinition`, asset glob `*.rewarddef.ot` (loader
`RewardDef_RegisterAssetLoader` = `FUN_140323b60`, label "Reward definition").
Codec: `cooked_schemas.definitions` `rewarddef.json`.

## How offers are rolled

`Reward_GenerateAndDistribute` (`FUN_1401e9020`) builds each level's reward slots:
`_InitAllRewards` → `Distribute` → "Fill remaining slots with random rewards". The roll is
**seeded** ("Seed : {0} ; Base seed {1}"). The `GENERATE_REWARDS` gameplay event is handled by
`FUN_14005c510` / `FUN_14003b350`.

## Why a ban must be DATA-LEVEL, not a runtime hook

Ravenswatch multiplayer is host-authoritative and **deterministic** ([[multiplayer-netcode]]):
the reward roll is seed-driven so every peer derives the same offers. A per-peer Lua post-filter
that drops a banned card on one client would desync the run (different visible offers / RNG
stream divergence). So a safe ban removes the candidate from the **pool the seeded roll reads**,
identically on all peers — i.e. a data/apply-time change, not a loader detour.

## Def structure (decoded)

`oCDtRewardDefinition` cooks to a plain `u32 count` + `count`×`u32` **reward-type index** list
(e.g. `Camp_Rewards_Dark_Hills` = `4 → [0,1,2,3]`, `Refugees_Dark_Hills` = `5 → [0,1,2,3,4]`) —
the SAME shape as the chapter sequence (game_mode_cook). So **dropping an index bans a whole
reward CATEGORY** for that reward source. The per-index semantics ("Reward type {}" is a runtime
debug formatter, no static enum) are not pinned yet — index→category needs more RE before a
category-ban can name what it removes.

## Two ban levers

- **Category ban (coarse)** — edit a rewarddef's u32 list (mechanically identical to
  `game_mode_cook`). Blocked only on mapping index→category. Removes e.g. "all items" or "all
  talents" from a reward source, not a single item.
- **Per-item/talent ban (precise)** — the real Heredos #13. An item appears because it is in the
  LiveOps `versiondef` magical-object vector (`@off 0x4590`, see [[item-clone-pipeline-verified]]);
  removing its entry de-registers it from the pool → never offered. This is the apply-time,
  MP-safe lever, but edits a shared global def (also hides it from the compendium) so it needs the
  same care as item registration.

## Next steps

1. Map reward-type index → category (RE the type registration) to ship a category ban.
2. Prototype versiondef-entry removal for a precise per-item ban (reuse the item pipeline's
   versiondef writer); gate behind apply so all peers share it.
3. Decide SDK surface: a `[[ban]]` manifest stanza (kind=item/talent id) handled at apply time.
