---
title: Pickable talents
description: Detecting a level-up card pick via POWER_UP_COLLECT_REQUEST, and the additive magical-object route for a card that replaces nothing.
---

:::note
Status: Tier-2 — the detour and Lua API are wired; the picked-card **identity
offset** is pinned empirically (see [Open](#open--confirm-the-identity-offset)).
Backs `R.talent.on_pick` / `R.talent.define{pickable}` in
`src/loader/lib/rsmm.lua` and the `POWER_UP_COLLECT_REQUEST` branch of
`hook_events.cpp`.
:::

## What a "pickable talent" is

A custom-code talent whose effect arms only when the player **chooses its card**
in the level-up book — versus `R.talent.define` without `pickable`, which is an
always-on passive. Choosing a card fires the gameplay-bus event
`POWER_UP_COLLECT_REQUEST` (`oCDtNamedEventPowerUpCollectRequest`), proven live
on the [oCGameNamedEvent bus](/reverse-engineering/event-systems/).

## Pipeline

1. Player picks a card → game dispatches `POWER_UP_COLLECT_REQUEST` at the hero
   dispatcher.
2. `gameplay_dispatch_detour` republishes it to Lua as
   `gameplay:POWER_UP_COLLECT_REQUEST`, attaching the tentative decoded identity
   `ev.card` (`+0x50`/`+0x58` GUID, `"<lo>:<hi>"`) plus a confirm window
   (`ev.p38`..`ev.p58`).
3. `R.talent.on_pick(card, cb)` filters by `card` and runs `cb(ev)` on the main
   thread; `R.talent.define{pickable=true, card=...}` flips a per-talent armed
   flag so its `effect` runs only after the matching pick. Arming resets at
   `GAME_START`.

## Event identity offset

The shared `oCGameNamedEvent` GIVE sibling ctor `NamedEvent_GiveMagicalObject_Ctor`
(`FUN_14030f430`) puts its def GUID at `+0x50`/`+0x58` in a `0x60` object. The
pick event's reward-def GUID is the **prime suspect at the same `+0x50`/`+0x58`**,
so the loader publishes `ev.card` tentatively and string-id matching works today.

Not yet *confirmed*: the pick class registrar (RTTI `oCDtNamedEventPowerUpCollectRequest`
@ `0x140f1d940`, ref'd from undefined code at `0x1402fdb6c`) is unanalysed, and
the pick event may omit the `oCGameNamedEventNetwork` layer GIVE inserts (which
would shift the payload toward `+0x38`).

## Open — confirm the identity offset

Run `mods/TalentPickProbe` (`RSMM_ENABLE_GAMEPLAY_EVENTS=1`), level up, pick
cards. In `mods/_log.txt` the `pickprobe:` lines show `ev.card` + the `p38..p58`
window. The identity is the field that changes with the chosen card and repeats
when the **same** card is picked again. If that field is `p50`/`p58`, `ev.card`
is already correct. The read is bounded to `+0x58`; a smaller no-Network event
reads a few bytes of adjacent mapped heap — benign, never an unmapped fault.

Second thing to confirm: `POWER_UP_COLLECT_REQUEST` fires for **every** power-up
collect (level-up cards *and* world orbs/globes), so per-card targeting needs the
GUID (`ev.card`); `"*"`/no-card arms on ANY power-up.

## Additive pickable — the magical-object route

The cleanest *additive* (replaces-nothing) pickable that works with proven
primitives: a **NEW magical object**. Unlike the hero skill list (fixed 28-row
schema — a 29th [bricks the hero](/reverse-engineering/skills-system/)), the
magical-object / reward pool is **variable-length and additive**:

- Reward definitions are `oCTLibrary<oCDtRewardDefinition>`, file-loaded from
  `*.rewarddef.ot` and registered in `UsedRscList.ot`. Tables are variable-length
  (camp 9 entries, refugee 5) — count is data-driven, not a global constant.
- The custom magical-object pipeline is proven additive end-to-end (a new item
  shows in the compendium and can be granted/picked).

**Binding gap closed.** A custom item's GUID is cook-derived (not recomputable in
Lua), so the loader resolver `resolve_item_guid(id)` (`hook_items.cpp`) +
`R.item.guid(id)` / `R.item.on_guid(id, cb)` resolve it at runtime by scanning
the pool source list for the entry spawned from the item's `EntitySettingsResource*`
(GUID at `def+0x88`/`+0x90`). Demo: `mods/AdditivePickableTalent` — `kind="item"`
emits the card, `init.lua` arms an ownership-gated effect once the GUID resolves.

## See also

- [Event systems](/reverse-engineering/event-systems/) — the gameplay bus this rides.
- [Skills system](/reverse-engineering/skills-system/) — why the herodef route is walled.
- [Custom skills guide](/guides/custom-skills/) — the SDK `skill` kind.
