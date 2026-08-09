---
title: Event systems
description: The two distinct event systems — the analytics firehose and the oCGameNamedEvent gameplay bus — and how the loader bridges both to Lua.
---

:::note
Status: Tier-1 RE backing `hook_events.cpp`. The gameplay bus is **proven live**
under Proton (4200+ events, 82 distinct names captured); the analytics firehose
is string-verified. Image base `0x140000000`.
:::

## Two event systems

Ravenswatch has **two** independent event systems. Do not conflate them.

| | Analytics firehose | oCGameNamedEvent bus |
|---|---|---|
| Sink / hook | `Analytics_SubmitNamedEvent` `FUN_1401fa470` | `NamedEvent_Dispatch` `FUN_14066a700` |
| Payload | analytics key/value JSON | live entity handles + typed fields |
| Timing | **after** the action | **at** the action (subscribers run inline) |
| Lua event | `R.on("<name>")` | `R.on("gameplay:<NAME>")` |
| Use | "when X happens, do Y" triggers | mutate the actor, read damage, give items |
| Env gate | on by default (`RSMM_DISABLE_GAME_EVENTS=1` to turn off) | on by default (`RSMM_DISABLE_GAMEPLAY_EVENTS=1` to turn off) |

## Analytics firehose

All lowercase snake_case analytics events funnel through one central sink,
`Analytics_SubmitNamedEvent` (`FUN_1401fa470`) — ~37 callers build a KV payload
and submit it as JSON to Passtech's backend. The event name is `arg3`, a
`StringDesc { const char* ptr @+0; u32 len|0x80000000 @+8 }`.

`install_analytics_firehose()` detours that single sink, reads the name, and
emits it to Lua — so **one hook exposes every named event**, and any name a patch
adds shows up automatically. Confirmed names: `game_start` `run_start` `run_end`
`chapter_end` `level_up_reach` `enemy_killed` `unlock_skill` `unlock_hero` …

**Observation-grade, not a gameplay bus** — fires after the action and carries
analytics KV, not a live entity handle. Perfect for triggers, useless for
mutating the actor.

## oCGameNamedEvent gameplay bus

Each entity that wants events owns a **NamedEventDispatcher** sub-object — for a
hero it lives at `entity + 0x4d8`; the world has one at `world + 0x340`.

```text
dispatcher + 0x00..0x18   pending-dispatch queue (intrusive)
dispatcher + 0x28         channel map (SwissTable: id -> channel node)
```

A **channel node** (one per interned event id, 0x20 bytes): `+0x00` id,
`+0x08` subscriber array, `+0x10` count, `+0x14` cap. A **subscription**:
`+0x00` owner entity, `+0x10` handler functor (invoked `(*handler)(ev, sub)`).

### Event object header (every subclass)

```text
ev + 0x00   vftable     (oCGameNamedEvent -> ...Network -> concrete subclass)
ev + 0x08   u32 = 2     (type tag)
ev + 0x20   const char* PLAINTEXT name, e.g. "GIVE_MAGICAL_OBJECT"
ev + 0x30   u32         interned event id (THE channel key)
ev + 0x38   u64         owning-peer/session id (network leg stamps this)
```

Because the plaintext name sits at `ev+0x20`, the loader needs **no per-event
table** and survives the game adding event names. Interned ids are
`crc32_reflected(name)` via `NamedEvent_Id_FromCrc` (`FUN_14051e0e0`).

### The hook point — `NamedEvent_Dispatch` (`FUN_14066a700`)

```c
void NamedEvent_Dispatch(void* dispatcher, oCGameNamedEvent* ev)
```

Clones the event, enqueues it, drains the queue — per event, finds the channel
node by `ev->id`, iterates subscribers invoking `(*(sub+0x10))(ev, sub)`, then
deletes the clone. **One detour here exposes every entity-context gameplay event.**
The loader forwards the original first, reads name@`+0x20` and id@`+0x30`, decodes
verified payloads, and publishes `gameplay:<NAME>`.

## Verified payloads

### GIVE_MAGICAL_OBJECT (size 0x60) — ctor `FUN_14030f430`

```text
+0x20  name "GIVE_MAGICAL_OBJECT"   +0x30 interned id   +0x38 peer = -1
+0x50  u64 MO definition GUID lo    (from MagicalObjectDefinition+0x88)
+0x58  u64 MO definition GUID hi
```

### NETWORK_DAMAGE (size 0x110) — emitter `FUN_140726610`

```text
+0x40  f32 damage value      +0x48 u64 source net-id
+0x50  oCEntityHitData embedded (+0x60 target, +0x100 instigator)
```

## Give-item recipe (proven in-game 2026-06-12)

Any currently-loaded item's identity GUID is just `def+0x88`/`+0x90` of a
`g_MagicalObjectPool` source-array entry — read it live, no file parsing:

```lua
-- g_MagicalObjectPool @ 0x1414365d0; *ptr = {src[] @+0, u32 srcN @+8}
local pool = I.module_base() + (0x1414365d0 - 0x140000000)
local def  = I.read_u64(I.read_u64(I.read_u64(pool)))   -- source slot 0
local lo, hi = I.read_u64(def + 0x88), I.read_u64(def + 0x90)
local ev = R.engine.call("NamedEvent_GiveMagicalObject_Ctor", I.scratch(0x60))
I.poke(ev + 0x50, lo, 8); I.poke(ev + 0x58, hi, 8)
R.engine.call("NamedEvent_Dispatch", hero_dispatcher, ev)
```

The item is granted **directly to inventory** (no world orb). This is wrapped in
the SDK as **`R.give`** (`R.give.random()` / `.by_index(0)` / `.by_guid(lo,hi)`),
which auto-captures the hero dispatcher from any hero-anchored event.

:::note[Solo vs network]
`GIVE_MAGICAL_OBJECT` and `NETWORK_DAMAGE` never fire in solo play (item-grant and
damage are direct calls there) — they only fire on the network-replication path
or our own emit. The hero's handlers are still subscribed, so *emitting* them from
Lua is the give-item lever regardless.
:::

## See also

- [Pickable talents](/reverse-engineering/pickable-talents/) — rides `POWER_UP_COLLECT_REQUEST`.
- [Combat & damage](/reverse-engineering/combat-damage/) — the `NETWORK_DAMAGE` hit-data.
- [Mod hooks](/reverse-engineering/mod-hooks/) — loader detour + thread model.
