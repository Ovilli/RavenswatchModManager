# Pickable talents — `POWER_UP_COLLECT_REQUEST` pick detection

> 📖 Prose version on the docs site: **https://docs.rsmm.me/reverse-engineering/pickable-talents/** (`apps/docs/src/content/docs/reverse-engineering/pickable-talents.md`).
> This file stays as the raw RE field notes.


> Status: Tier-2 (Phase 1 of the pickable-custom-talent feature). The detour and
> Lua API are wired; the picked-card **identity offset** is pinned empirically
> in-game (see "Open" below). Backs `R.talent.on_pick` / `R.talent.define{pickable}`
> in `src/loader/lib/rsmm.lua` and the `POWER_UP_COLLECT_REQUEST` branch of
> `src/loader/src/hook_events.cpp::gameplay_dispatch_detour`.

## What a "pickable talent" is

A custom-code talent whose effect arms only when the player **chooses its card**
in the level-up book — as opposed to `R.talent.define` without `pickable`, which
is an always-on passive. Choosing a card fires the gameplay-bus event
`POWER_UP_COLLECT_REQUEST` (`oCDtNamedEventPowerUpCollectRequest`), already
proven live on the `NamedEvent_Dispatch` bus (`events-bus.md`).

## Pipeline

1. Player picks a level-up / reward card → game dispatches
   `POWER_UP_COLLECT_REQUEST` at the hero dispatcher.
2. `gameplay_dispatch_detour` republishes it to Lua as
   `gameplay:POWER_UP_COLLECT_REQUEST`, attaching the tentative decoded
   identity `ev.card` (the `+0x50/+0x58` GUID, `"<lo>:<hi>"`) plus a confirm
   **window** (`ev.p38`..`ev.p58` = qwords at event `+0x38`..`+0x58`).
3. `R.talent.on_pick(card, cb)` filters by `card` and runs `cb(ev)` on the main
   thread; `R.talent.define{pickable=true, card=...}` flips a per-talent armed
   flag so its `effect` only runs after the matching pick. Arming resets at
   `GAME_START`.

## Event object layout (base, from `events-bus.md`)

| Offset | Field |
|--------|-------|
| `+0x20` | plaintext name (`char*`) |
| `+0x30` | interned name id (u32) |
| `+0x40`+ | subclass payload (`oCDtNamedEventPowerUpCollectRequest`) |

The shared `oCGameNamedEvent` template is fixed by the GIVE sibling ctor
`NamedEvent_GiveMagicalObject_Ctor` (`FUN_14030f430`), decompiled:

```text
+0x00 vftable   +0x08 u32=2   +0x20 name StringDesc   +0x28 flag 0x80000000
+0x30 interned id   +0x38 peer=-1   +0x40 0   +0x48 -1
+0x50/+0x58 def GUID (payload, 16 bytes)   → object size 0x60
```

So GIVE is exactly `0x60` with its def GUID at `+0x50/+0x58`. The pick event's
reward-def GUID is the **prime suspect at the same `+0x50/+0x58`**, so the loader
publishes `ev.card = "<+0x50>:<+0x58>"` tentatively and string-id matching works
today. It is not yet *confirmed* because the pick class registrar (RTTI string
`oCDtNamedEventPowerUpCollectRequest` @ `0x140f1d940`, ref'd from undefined code
at `0x1402fdb6c`) is unanalysed in the corpus, and the pick event may omit the
`oCGameNamedEventNetwork` layer GIVE inserts (which would shift the payload
earlier, toward `+0x38`).

## Open — confirm the identity offset (one in-game session)

Run `mods/TalentPickProbe` (enable it, `RSMM_ENABLE_GAMEPLAY_EVENTS=1`), level
up and pick cards. In `mods/_log.txt` the `pickprobe:` lines show `ev.card`
plus the `p38..p58` window per pick. The identity is the field that:

- changes with the chosen card, and
- repeats when the **same** card is picked again.

If that field is `p50`/`p58`, `ev.card` is already correct — done. Otherwise
note the real offset here and repoint the `card` field in `hook_events.cpp`
(and trim the window). The read is bounded to `+0x58` (the GIVE template's last
field); if the pick event is the smaller no-Network shape the high fields read a
few bytes of adjacent mapped heap — benign, never an unmapped fault.

Second thing to confirm in the same session: **`POWER_UP_COLLECT_REQUEST` fires
for every power-up collect, not just card picks.** `Item_Quality_Power_Up` /
`oCDtEntityCpntPowerUpSettings` model both level-up cards and world orbs/globes,
and this is the only `POWER_UP_*` event string. So check that it DOES fire on a
card pick, and note whether orb/globe pickups also fire it (expected). The
consequence is already designed for: bind a specific `card` GUID to target one
talent; `"*"`/no-card arms on ANY power-up.

So: predicate (`on_pick(function(ev) ... end)`) and any-pick (`"*"`) matching are
unconditionally correct *as "any power-up collect"*; per-card targeting needs the
GUID (`ev.card`), correct iff the prime-suspect offset holds.

## Next (Phase 2) — the visible card

Phase 1 detects a pick; it does not yet add a *new* card. Route A (ship first):
reskin a low-value vanilla power-up via Text/Ui overrides + zero its magnitude
so it reads as the custom talent and only the Lua effect remains. Route B
(research): author a custom `oCDtRewardDefinition` and inject it into the reward
roll (`GENERATE_REWARDS`). See the feature plan.

## ADDITIVE pickable — the magical-object route (2026-06-16)

The cleanest *additive* (replaces-nothing) pickable that works with proven
primitives: a **NEW magical object**. Unlike the hero skill list (a fixed schema
— exactly 28 rows on all 12 heroes, a 29th bricks the hero; see
`skills-system.md`), the magical-object / reward pool is **variable-length and
additive**:

- The reward definitions are `oCTLibrary<oCDtRewardDefinition>`, file-loaded from
  `*.rewarddef.ot` and **registered in `UsedRscList.ot`** (9 reward tables today:
  `Camp_Rewards_*`, `Refugees_*`). The tables themselves are variable-length —
  camp tables hold 9 reward entries, refugee tables 5 — i.e. the entry count is
  data-driven per table, not a global fixed constant.
- The custom magical-object pipeline is already proven additive end-to-end
  (`item-clone-pipeline-verified`): a new item shows in the compendium and can be
  granted/picked.

**Binding gap CLOSED.** A custom item's identity GUID is cook-derived (not
recomputable in Lua) and `register_item` only returned a bool — so a mod couldn't
bind its OWN effect to its OWN item. Added a loader resolver
`resolve_item_guid(id)` (`hook_items.cpp`) + Lua native `_internal.item_guid`,
surfaced as **`R.item.guid(id)` / `R.item.on_guid(id, cb)`** (`rsmm.lua`). It
finds the item's `EntitySettingsResource*` by path, scans the pool SOURCE list for
the entry spawned from it, and reads the GUID at `def+0x88/+0x90` (the same fields
`dump_pool` logs). Returns nil until the def has loaded, so callers poll.

Demo: `mods/AdditivePickableTalent` — `[[content]] kind="item"` emits the new
pickable card; `init.lua` resolves its GUID via `R.item.on_guid` and arms an
ownership-gated effect (heal on each ability use). Loader builds+links and both
Lua files parse; **in-game proof still pending a play session** (enable it +
`RSMM_ENABLE_GAMEPLAY_EVENTS=1`, confirm the card drops and the effect fires while
owned). This is the engine-supported "new talent that replaces nothing".
