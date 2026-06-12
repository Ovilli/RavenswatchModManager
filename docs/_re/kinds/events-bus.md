# oCGameNamedEvent gameplay bus — entity-context event dispatch + Lua bridge

> Status: Tier-1 RE backing `src/loader/src/hook_events.cpp::install_gameplay_bus`.
> All addresses verified live against the shipped Ravenswatch.exe via the
> Ghidra MCP bridge, 2026-06-11 (image base 0x140000000). This is the SECOND,
> distinct event system — do not conflate with the analytics firehose
> (`Analytics_SubmitNamedEvent` / `FUN_1401fa470`, see `events.md`).

## Two event systems

| | Analytics firehose | oCGameNamedEvent bus (this doc) |
|---|---|---|
| Sink/hook | `Analytics_SubmitNamedEvent` `FUN_1401fa470` | `NamedEvent_Dispatch` `FUN_14066a700` |
| Payload | analytics key/value JSON | live entity handles + typed fields |
| Timing | after the action | at the action (subscribers run inline) |
| Lua event | `R.on("<name>")` | `R.on("gameplay:<NAME>")` |
| Use | "when X happens do Y" triggers | mutate the actor, read damage, give items |
| Env gate | `RSMM_ENABLE_GAME_EVENTS=1` | `RSMM_ENABLE_GAMEPLAY_EVENTS=1` |

## Architecture

Each entity that wants events owns a **NamedEventDispatcher** sub-object. For a
hero/entity it lives at `entity + 0x4d8`; the world has one too (`world + 0x340`).
The dispatcher holds:

```
dispatcher + 0x00 .. 0x18   pending-dispatch queue (head/tail/freelist, intrusive)
dispatcher + 0x10           queue count
dispatcher + 0x18           "currently dispatching" flag (re-entrancy guard)
dispatcher + 0x28           channel map (SwissTable: id -> channel node)
```

A **channel node** (one per distinct interned event id), malloc'd 0x20 bytes by
`Netcode_Channel_LookupById` on first subscribe:

```
node + 0x00   u32  interned event id
node + 0x08   sub** subscriber array
node + 0x10   u32   subscriber count
node + 0x14   u32   subscriber capacity
node + 0x18   sub*  in-dispatch cursor (the sub currently being invoked)
```

A **subscription (sub)** object (alloc'd by `FUN_140219dc0`, functor stored by
`FUN_14051b580`):

```
sub + 0x00   holder/owner entity*
sub + 0x08   functor free-thunk (or 0)
sub + 0x10   handler functor — invoked as (*handler)(ev, sub)
sub + 0x18   self index inside node's array (for O(1) swap-remove)
```

### Event object header (every oCGameNamedEvent subclass)

```
ev + 0x00   vftable      (oCGameNamedEvent -> ...Network -> concrete subclass)
ev + 0x08   u32 = 2      (type tag)
ev + 0x20   const char*  PLAINTEXT name, e.g. "GIVE_MAGICAL_OBJECT"
ev + 0x28   u32 cap | 0x80000000   (non-owned string flag)
ev + 0x2c   u32 len
ev + 0x30   u32          interned event id (THE channel key)
ev + 0x38   u64          owning-peer/session id (network leg stamps this)
```

Because the plaintext name sits at `ev+0x20`, the loader needs **no per-event
table** and survives the game adding event names — exactly like the analytics
firehose, but with live payloads.

## Interned event ids

Names are interned at static-init. Each name has a one-shot init thunk (e.g.
`FUN_140038360` for `NETWORK_DAMAGE`) that runs:

```
id = NamedEvent_Id_FromCrc(0, crc32_reflected(name))   // FUN_14051e0e0
```

storing the result in a per-name global (e.g. `_DAT_1412e96b0`). The id is
crc32 (standard reflected table `DAT_141436710`) over the 8 interleaved bytes
of `(ns=0, name_crc)`. `GIVE_MAGICAL_OBJECT` interns at `DAT_1412ec880`; its
name string is at `0x140f12808`. The loader can derive the id for any name at
runtime via `NamedEvent_Id_FromCrc` + a crc32 of the name.

## THE hook point: NamedEvent_Dispatch (FUN_14066a700)

`void NamedEvent_Dispatch(void* dispatcher, oCGameNamedEvent* ev)`

1. Clones the event (vcall `ev+0x18`), enqueues the clone on the dispatcher
   queue, bumps the count.
2. If already dispatching (re-entrancy guard `dispatcher+0x60`... actually the
   loop guard at `+0x18`), returns — the outer drain handles it.
3. Otherwise drains the queue. Per queued event:
   - `NamedEvent_ChannelMap_Find(dispatcher+0x28, &it, &ev->id)` (`FUN_14066cc50`,
     find-only sibling of `Netcode_Channel_LookupById`).
   - Iterate `node` subscriber array, set `node+0x18` cursor to the current
     sub, invoke `(*(sub+0x10))(ev, sub)`.
   - If a handler unsubscribes itself mid-call the cursor is set to `-1` and the
     loop swap-removes it; empty channels are erased.
   - `NamedEvent_Delete(ev_clone)` (`FUN_140126da0`, vdelete with free flag).

**One detour here exposes every entity-context gameplay event.** The loader
forwards the original first (subscribers run, effect applies, the caller-owned
event is still alive), reads name@+0x20 and id@+0x30, decodes verified payloads,
and publishes `gameplay:<NAME>`.

Verified callers reaching this dispatch (xref of the dispatcher path):
`NETWORK_DAMAGE` emitter `FUN_140726610` -> `NamedEvent_NetSend` -> receive ->
dispatch; the give-MO path `FUN_140397190` -> ctor + dispatch.

## Hero subscription catalog

`NamedEvent_HeroSubscribeAll` (`FUN_140391d30`, the events corpus's
"give-handler") and its teardown twin `NamedEvent_HeroUnsubscribeAll`
(`FUN_140394a40`) register/clear ~26 handler slots on the hero. Each entry is
`(interned-id global -> hero handler slot)`. Slots are qword indices into the
hero object; map (from `FUN_140394a40`, the clean unsubscribe walk):

| id global      | hero slot (qword idx) | event name |
|----------------|-----------------------|------------|
| DAT_1412eca10  | hero+0x2fa            | CINE_START |
| DAT_1412ec5e8  | hero+0x2fb            | CINE_STOP |
| DAT_1412eca10  | hero+0x2fc            | CINE_START (world map) |
| DAT_1412ec5e8  | hero+0x2fd            | CINE_STOP (world map) |
| DAT_1412ec9a8  | hero+0x2ff            | GAIN_DREAM_SHARDS |
| DAT_1412ec698  | hero+0x300            | UPDATE_OBJECT_UI |
| DAT_1412ec960  | hero+0x301            | GAIN_REROLL |
| DAT_1412ebe30  | hero+0x305            | DUPLICATE_RANDOM_MAGICAL_OBJECT |
| DAT_1412ec880  | hero+0x306            | **GIVE_MAGICAL_OBJECT** |
| DAT_1412ebce0  | hero+0x2fe            | DUPLICATE_RANDOM_COMMON_OBJECT |
| DAT_1412ec3e0  | hero+0x302            | DUPLICATE_RANDOM_RARE_OBJECT |
| DAT_1412ebe00  | hero+0x303            | DUPLICATE_RANDOM_EPIC_OBJECT |
| DAT_1412ec488  | hero+0x304            | REMOVE_MAGICAL_OBJECT_FROM_ID |
| DAT_1412ec3f8  | hero+0x307            | REMOVE_RANDOM_MAGICAL_OBJECT |
| DAT_1412ec410  | hero+0x308            | REMOVE_RANDOM_COMMON_OBJECT |
| DAT_1412ec8c8  | hero+0x309            | REMOVE_RANDOM_RARE_OBJECT |
| DAT_1412ec350  | hero+0x30a            | REMOVE_RANDOM_EPIC_OBJECT |
| DAT_1412ec2a0  | hero+0x30b            | REMOVE_RANDOM_LEGENDARY_OBJECT |
| DAT_1412ebd28  | hero+0x30c            | REMOVE_RANDOM_CURSED_OBJECT |
| DAT_1412ec028  | hero+0x30d            | REMOVE_ALL_MAGICAL_OBJECT |
| DAT_1412ec8e0  | hero+0x30e            | REMOVE_ALL_COMMON_OBJECT |
| DAT_1412ecc00  | hero+0x30f            | REMOVE_ALL_RARE_OBJECT |
| DAT_1412ec7f0  | hero+0x310            | REMOVE_ALL_EPIC_OBJECT |
| DAT_1412ebd10  | hero+0x311            | REMOVE_ALL_LEGENDARY_OBJECT |
| DAT_1412ec2e8  | hero+0x312            | REMOVE_ALL_CURSED_OBJECT |
| DAT_1412ec6c8  | hero+0x313            | ADD_RANDOM_ULTI_SKILL |
| DAT_1412ec748  | hero+0x314            | GAIN_INGREDIENT (world map) |
| DAT_1412ebf68  | hero+0x315            | CHOOSE_MELODY (world map) |
| DAT_1412ec650  | hero+0x316 / +0x318   | LOCK_CONTROL |
| DAT_1412eca28  | hero+0x317 / +0x319   | UNLOCK_CONTROL |
| DAT_1412ec208  | hero+0x31a            | GAIN_REROLL (DEATHDOOR_TIMER_END cluster) |
| DAT_1412ebc68  | hero+0x321            | REMOVE_MELODY |

(Slots whose source map is `lVar16 = world+0x368` vs `lVar1 = entity+0x500` are
noted "world map"; the rest subscribe on the entity's own channel map.)

## Payload layouts

### GIVE_MAGICAL_OBJECT — oe::dt::NamedEventGiveMagicalObject (size 0x60)

Ctor `NamedEvent_GiveMagicalObject_Ctor` `FUN_14030f430`:

```
+0x00  vft chain (..NamedEventGiveMagicalObject)
+0x08  u32 = 2
+0x20  name "GIVE_MAGICAL_OBJECT" (literal, +0x28 flag 0x80000000)
+0x30  u32 interned id
+0x38  u64 peer = -1
+0x50  u64 MO definition GUID lo   <-- from MagicalObjectDefinition+0x88
+0x58  u64 MO definition GUID hi
```

Loader publishes `{mo_guid_lo, mo_guid_hi}` (hex strings).

### NETWORK_DAMAGE / NETWORK_DAMAGE_RESPONSE — oCGameNamedEventNetworkDamage (size 0x110)

Reference emitter `NamedEvent_EmitNetworkDamageFromHit` `FUN_140726610`
stack-builds it then `NamedEvent_NetSend`s it:

```
+0x40  f32  damage value (= source+0x30 attack stat * DAT_140fc6a68)
+0x48  u64  source net-id  (FUN_140726330(source))
+0x50  oCEntityHitData     embedded:
  +0x50  vft (oCEntityHitData)
  +0x60  oCEntity* target            (refcounted; copied from hit+0x10)
  +0x68 .. 0xbc  hit floats / vectors (position, direction, knockback ...)
  +0xc0/+0xc8/+0xd0  u64 flags/ids
  +0xd8  u16
  +0xe0  ptr
  +0xf0  oCEntity* instigator        (refcounted)
  +0x100 char flag
```

Loader publishes `{value, source_id, target_entity, instigator_entity}`
(entities as hex strings; raw pointers, undecoded further).

Class name strings: `NETWORK_DAMAGE` @0x140f027f8, `NETWORK_DAMAGE_RESPONSE`
@0x140f02808, vftable `oCGameNamedEventNetworkDamage::vftable` @0x140f0c4a8.

## Network leg (replication)

`NamedEvent_NetSend` `FUN_1407205a0` -> `NamedEvent_NetSendToPeer` `FUN_140720630`
wraps the event in an `oCNamedEventNetworkMessage` (vft `0x140f96b28`, msg class
id `0x157f6854`) and unicasts via the session vcall `+0xc0`. Receive side:
`FUN_14085dec0` (the message Serialize) re-allocates the event from the class
registry `DAT_14146b2d8` by serialized class index, restores `ev+0x30`, then
dispatches into the target entity. So `NamedEvent_Dispatch` fires on the
receiving side for replicated events — the hook sees both local and remote.

## Emit path (fire an event from the loader / a mod)

Local give-item, mirroring `FUN_140397190`:

1. `buf = malloc(0x60)` (or a stack buffer; if you let dispatch delete it, it
   must be game-heap — but dispatch deletes a *clone*, not your object, so a
   stack/loader buffer is fine).
2. `ev = NamedEvent_GiveMagicalObject_Ctor(buf)`.
3. Write the MO definition GUID into `ev+0x50/+0x58` (from
   `MagicalObjectDefinition+0x88`).
4. `NamedEvent_Dispatch(hero + 0x4d8, ev)`.

All four primitives carry a `cabi` in `data/symbols.json`, so a Lua mod can do
this through the existing engine bridge with no new native surface:

```lua
local buf = -- a 0x60 scratch region (e.g. from a small alloc helper)
local ev  = R.engine.fn.NamedEvent_GiveMagicalObject_Ctor(buf)
rsmm._internal.poke(ev + 0x50, guid_lo, 8)
rsmm._internal.poke(ev + 0x58, guid_hi, 8)
R.engine.fn.NamedEvent_Dispatch(dispatcher, ev)
```

`R.engine.fn.NamedEvent_Id_FromCrc(0, crc)` derives an interned id for any
event name. For replicated effects, route through `NamedEvent_NetSend` instead
of calling dispatch directly.

## In-game verification (2026-06-12)

The `NamedEvent_Dispatch` detour is **proven live** under Proton: a wildcard
Lua probe (`mods/GameplayBusProbe`) captured 600+ events in one session with
monotonic `seq`, ids matching the crc table, and sane dispatcher/entity
pointers. Observed names include ENEMY_KILLED, ENEMY_DEAD(_AROUND),
SPAWNED_ENEMY_DEATH, NPC_DEATH_ALERT, HERO_XP_LEVEL_UP, GAIN_HEALTH,
GAIN_DREAM_SHARDS, ADD_MODIFIER / REMOVE_MODIFIER / CLEAR_STATUS,
INTERACTION_REQUEST / _VALIDATE / _SUCCESS / LOCAL_INTERACTION_SUCCESS,
POWER_UP_COLLECT_REQUEST, CROWS_MAP_REVEAL, PROJECTILE_DESTROYED,
SHOW/HIDE_LIFE_BAR, OPTIMIZE_ON/OFF, BHV_FLYING_TELEPORTER,
BEHAVIOUR_TELEPORTER_ACTIVATION, FORTISSIMO_ZONE_END, PERFECT_KILL_INC,
COMBAT_COUNTER_INC and assorted *_COUNTER_INC achievement feeders — i.e. the
bus carries AI/behaviour, UI, economy, and combat traffic, not just the hero
subscription catalog.

A second solo session (4200+ events, 82 distinct names) added per-hero ability
traffic (ENCHANTED_BLADES_LIGHT/HEAVY_IMPACT, COMBO_LINK, ENERGY_COUNTER_INC/
DEC), run lifecycle (GAME_START, GAME_CHRONO_START, MAP_GENERATION_DONE,
ACTIVITY_START, GAME_END_NEXT_CHAPTER), loot flow (OPEN_CHEST,
GENERATE_REWARDS, HEALTH_GLOBE_PICKED_UP, UPGRADE_RANDOM_SKILL) and
NETWORK_PLAY_BARK. Notably **GIVE_MAGICAL_OBJECT and NETWORK_DAMAGE never
fired in solo play** even while chests were opened and damage was taken
(OPEN_CHEST / GENERATE_REWARDS / STAGGERED_SUFFERED_COUNTER_INC did fire):
solo item-grant and damage are direct calls; those two events are emitted only
on the network-replication path (and the debug give-item route). The hero's
handlers for them are still subscribed, so *emitting* GIVE_MAGICAL_OBJECT from
Lua remains the expected give-item lever — observation of them just requires
multiplayer or our own emit.

Dispatcher semantics (verified live): events fire at the *subject* entity's
dispatcher, which is not always the hero — GAIN_HEALTH fires at the heal
source (health globe etc., new entity each time), while ABILITY_EXIT,
COMBO_LINK, ENERGY_COUNTER_INC/DEC, INTERACTION_VALIDATE and
GAIN_DREAM_SHARDS are reliably hero-anchored (one stable dispatcher all
session). Use those to locate the hero at runtime from Lua.

**Emit path proven live (2026-06-12)**: a Lua mod (`mods/GiveItemEmitTest`)
built a GIVE_MAGICAL_OBJECT event via `rsmm._internal.scratch(0x60)` +
`NamedEvent_GiveMagicalObject_Ctor`, poked the GUID (zeroed for stage 1) and
called `NamedEvent_Dispatch(hero_dispatcher, ev)` — the hook echoed
`gameplay:GIVE_MAGICAL_OBJECT id=3469130550 mo_guid_lo=0x0` back, the game's
handler took the GUID-lookup miss gracefully (no crash, session continued),
and the recursive script mutex carried the same-thread re-entry
(Lua → dispatch → detour → Lua). Remaining for an actual item grant: the real
MagicalObjectDefinition GUID (def+0x88) for a chosen item — needs the def
registry / GUID-lookup function traced in Ghidra. Also verified: dispatching
an event nobody fully handles is safe (the unknown-id open question is now
half-answered — known id with missing payload target is a no-op).

Trigger gotchas for test mods: SHOW_TAB / HIDE_TAB / BOOK_MENU_OPEN are UI
lifecycle events (fire on creation/teardown only, not per keypress) — use
gameplay actions (ABILITY_EXIT counting) as deliberate triggers instead.

### Give-item recipe (real item grant) — PROVEN in-game 2026-06-12

Stage 2 traced the GIVE_MAGICAL_OBJECT handler and granted an actual item
from Lua:

- The subscribed handler `FUN_1403a7ba0` (found via the hero channel functor
  thunk at `0x1403bc5b0` → vftable slot `0x140f2c8a8`) reads the GUID at
  `ev+0x50/+0x58` and calls `MagicalObjectPool_SourceLookup`
  (`FUN_1402590c0`) against `g_MagicalObjectPool`. SourceLookup linearly
  matches `def+0x88 == guid_lo && def+0x90 == guid_hi` over the pool's source
  array. On a hit it calls the give routine `FUN_140397190` with the resolved
  definition; a zero/unknown GUID is a clean no-op (this is why stage 1's
  zeroed GUID was safe).
- So **any currently-loaded item's identity GUID is just `def+0x88/+0x90` of
  a `g_MagicalObjectPool` source-array entry**. No file parsing, no cooked
  GUID extraction — read it live from the pool.

Recipe (proven):

```lua
-- g_MagicalObjectPool: pointer global; *ptr = {src[] @+0, u32 srcN @+8, ...}
local pool = I.module_base() + (0x1414365d0 - 0x140000000)
local vec  = I.read_u64(pool)
local def  = I.read_u64(I.read_u64(vec))        -- source array slot 0
local lo, hi = I.read_u64(def + 0x88), I.read_u64(def + 0x90)

local ev = R.engine.call("NamedEvent_GiveMagicalObject_Ctor", I.scratch(0x60))
I.poke(ev + 0x50, lo, 8)
I.poke(ev + 0x58, hi, 8)
R.engine.call("NamedEvent_Dispatch", hero_dispatcher, ev)
```

Result: the item is granted **directly to inventory** (no world orb), the
hook echoes `gameplay:GIVE_MAGICAL_OBJECT` with the matching GUID, and the
engine fires `gameplay:SPAWN_MO` at the same hero dispatcher ~5 events later
(the grant cascade). Pool held 99 source defs in the test run. Locating the
hero dispatcher: capture it from any hero-anchored event (see above).
`mods/GiveItemEmitTest` is the working reference.

## Open questions

- The dispatcher base offset (`entity + 0x4d8`) is hard-coded in the loader's
  published `entity` field; it is correct for hero/entity events but the world
  dispatcher (`world + 0x340`) gives a meaningless `entity` value — consumers
  should treat `entity` as advisory and prefer `dispatcher`.
- `NamedEvent_GiveMagicalObject_Ctor` pattern is non-unique (match_index 11/13,
  a tiny ctor template). `fn_verify` guards misresolution but a game update can
  shuffle the rank; the ctor may need a longer/anchored pattern later.
- Full oCEntityHitData field semantics past +0x60 (the float block) are not
  decoded — only target/instigator/value are surfaced.
- Subscriber functor ABI: `(*(sub+0x10))(ev, sub)` confirmed from the dispatch
  loop, but the functor's own closure layout (captured `this` etc.) is not
  reversed — fine for observation, needed only to *register* a native handler.
- Whether a brand-new event id (one no entity subscribes to) is safe to dispatch
  is untested; unknown ids just miss the channel map (no-op), which should be
  safe but is unverified in-game.
