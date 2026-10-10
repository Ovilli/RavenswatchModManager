# oCGameNamedEvent gameplay bus — entity-context event dispatch + Lua bridge

> 📖 Prose version on the docs site: **https://docs.rsmm.me/reverse-engineering/event-systems/** (`apps/docs/src/content/docs/reverse-engineering/event-systems.md`).
> This file stays as the raw RE field notes.


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

Emitter `NamedEvent_EmitNetworkDamageFromHit`, **re-found 2026-08-15 at
`FUN_1407276a0`** (the older `FUN_140726610` address went stale; it is the
second caller of `Entity_DispatchHit`). Signature
`(oCEntity* attacker, oCEntity* target, oCEntityHitData* hit)`. It stack-builds
the event then sends it through the TARGET's net component (`FUN_140721630`):

```
+0x40  f32  damage value (= *(attacker+0x30)+0x24 attack stat * DAT_140fcbee8)
+0x48  u64  source net-id  (Entity_GetNetId(attacker) = FUN_1407273c0)
+0x50  oCEntityHitData     embedded — copied field-for-field from *hit:
  +0x50  vft (oCEntityHitData)
  +0x60  refcounted per-hit HANDLE   (hit+0x10; NOT the target)
  +0x68 .. 0xbc  hit floats / vectors (position, direction, knockback ...)
  +0xc0  attacker CONTEXT             (hit+0x70; its entity at +0x8)
  +0xf0  hit-VALUE object             (hit+0xa0; f32 damage at +0x8,
                                       replication gate byte at +0x70)
  +0x100 char flag
```

**LAYOUT CORRECTION (2026-08-15).** The two fields this doc previously called
`target` (+0x60) and `instigator` (+0xf0) are a hit handle and the hit-value
object. Both producers agree: the attack resolver `Entity_ResolveAttackHits`
allocates the +0x10 slot from a handle allocator and releases it through the
generic destroy thunk, and fills +0xa0 with the value object it releases
through `FUN_140407e90` — the same two destructors the emitter uses. **The
target is not in the hit data at all**: it is the applier's first argument.

Loader publishes `{value, source_id}` only. The mislabelled pointers were
removed: they are sender-side heap pointers (the event is only ever built on
the machine that owns the target and then SENT, so every observation is on a
receiver), and a mod comparing `target_entity` to its hero pointer was
comparing a hero against a hit handle — a test that silently never fired. The
victim on the receiving side is the `dispatcher` the event was delivered to.

**Emit gates (why it never fires in solo).** With `authority = *(netcomp+0x130)`
(0 = this machine owns the entity): the hit is applied LOCALLY via
`Entity_DispatchHit` when the target has no net component, or is remotely
owned, or the attack's replication flag is clear; and the event is built and
sent only when this machine owns the target AND the attacker is remote. So a
machine never sees a replicated echo of its own attacks, and single player
never produces one at all.

This is what `R.damage` is built on: local attacks come from the resolver hook,
replicated ones from this event keyed by `source_id`.

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

This recipe is now wrapped in the SDK as **`R.give`** (`src/loader/lib/rsmm.lua`)
so mods don't reimplement the pool walk or hero-capture:

```lua
R.give.random()        -- grant a random loaded item
R.give.by_index(0)     -- grant pool source slot 0
R.give.by_guid(lo, hi) -- grant an explicit identity GUID
R.give.count()         -- number of loaded items
R.give.ready()         -- true once the hero has acted (dispatcher captured)
for i, lo, hi in R.give.each() do ... end
```

The module auto-captures the hero dispatcher from hero-anchored events, so
`R.give.*` just works once the hero acts once in a run (and the bus is armed
with `RSMM_ENABLE_GAMEPLAY_EVENTS=1`). `mods/GiveItemEmitTest` is the
reference consumer. Open follow-up: `R.give.by_name(name)` needs the def's
name/string offset verified live before it can ship.

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

## Who handles each event (static sweep, 2026-10-10)

How the table was made, so it can be redone after a patch: every event name is
interned once per compilation unit (8 static initializers each, found by the
name's image-base RVA — the strings are reached as `lea rax,[rbx+rva]` off
`lea rbx,[image base]`, which is why a `lea [rip+str]` scan finds none). Each
initializer stores the id in its own global; the code that loads one of those
globals is either a sender (writes it to ev+0x30) or a subscriber. Subscribers
come in two shapes, both ending in a thunk `jmp [rip+X]` whose target qword is
the handler:

* **Hero controller** — `NamedEvent_HeroSubscribeAll` inlines each subscription:
  id → `[rbp+..]`, `Netcode_Channel_LookupById`, then `lea rax,[rip+thunk]`.
  Validated: this resolves GAIN_REROLL to 0x1403aa9e0 (the proven handler),
  GIVE_MAGICAL_OBJECT to 0x1403a88f0 and CHOOSE_MELODY to 0x140399090.
* **Ability controller** — `AbilityController_Ctor` calls a per-handler
  template (0x1402f1bb0 / 0x1402f1cb0 / …) on owner+0x4d8; the template holds
  the thunk. A jump-table tail shares one template call across slots (all
  `REDUCE_<SLOT>_CD` reach 0x1402cd140 through 0x1402ca1ce), so read the call
  that the id-load FLOWS into, not the next call in address order.

Ability family (payload = `oCNamedEventNetworkWithData`, one typed value; see
the `oCNamedEventNetworkWithData_vftable` symbol): CLEAR_CD / CLEAR_<SLOT>_CD →
0x1402cce40 (bool true), REDUCE_CD / REDUCE_<SLOT>_CD → 0x1402cd140 (f32 or
int seconds), ADD_<SLOT>_CHARGE → 0x1402ccf30 (int, default 1),
REMOVE_<SLOT>_CHARGE → 0x1402cd040 (no payload). Slots: BASIC PRIMARY
SECONDARY DEFENSIVE TRAIT ULTIMATE DASH. Backs `R.ability` (CLEAR_CD proven in game 2026-10-10).

Hero-controller handlers (handler payloads unread unless noted — read each
handler before building on it):

| event | handler |
|---|---|
| ABILITY_EXIT | 0x1402cca20, 0x1403cf910 |
| ADD_ALL_SKILLS | 0x1402eef80 |
| ADD_RANDOM_ULTI_SKILL | 0x1403a75d0 |
| ALTAR_HERO_REVIVE_STAT | 0x1401f9350 |
| BABAYAGA_HOUSE_DEFEATED | 0x140293d00 |
| BOSS_FIGHTING_START | 0x1401f90c0, 0x1402888b0, 0x140293cb0 |
| BOSS_FIGHTING_STOP | 0x1401f9150, 0x140288a50 |
| CHARGE_LINK | 0x1403cf8c0 |
| CHOOSE_MELODY | 0x140399090 |
| CINE_ASK_SKIP | 0x140288680 |
| CINE_START | 0x1402885a0 |
| CINE_STOP | 0x140288610 |
| CLEAR_CHILLED | 0x1403cbc40 |
| CLEAR_ROSE_SEED | 0x1403cbc60 |
| CLEAR_STAGGER | 0x1403cc1d0 |
| CLEAR_STATUS | 0x1403bfb00 |
| COMBO_LINK | 0x1403cf900 |
| DEATHDOOR_TIMER_END | 0x1403a8040 |
| DUPLICATE_RANDOM_COMMON_OBJECT | 0x1403a8260 |
| DUPLICATE_RANDOM_EPIC_OBJECT | 0x1403a8560 |
| DUPLICATE_RANDOM_MAGICAL_OBJECT | 0x1403a80c0 |
| DUPLICATE_RANDOM_RARE_OBJECT | 0x1403a83e0 |
| FIRING_EXPLODE | 0x1403dc610, 0x1403dd120 |
| FORCE_DEATH | 0x1403cbc80 |
| GAIN_DREAM_SHARDS | 0x1403a72b0 |
| GAIN_INGREDIENT | 0x14039acc0 |
| GAIN_REROLL | 0x1403aa9e0 |
| GAME_CHRONO_START | 0x140287eb0 |
| GAME_END_CHANGE_STATE | 0x1402890b0 |
| GAME_END_FAILED | 0x140289020 |
| GAME_END_NEXT_CHAPTER | 0x140293d20 |
| GAME_END_SUCCESS | 0x140289000 |
| GAME_END_SUCCESS_SKIP_NEXT | 0x140289010 |
| GIVE_MAGICAL_OBJECT | 0x1403a88f0 |
| HERO_REVIVE | 0x1403a2700 |
| HOURGLASS_STATS | 0x1401f8cd0 |
| INTERACTION_CANCELED | 0x1402e5d20 |
| INTERACTION_FAILED | 0x1403a21f0, 0x1403a2270 |
| INTERACTION_REJECT | 0x1403a2170 |
| INTERACTION_REQUEST | 0x1402e5740 |
| INTERACTION_VALIDATE | 0x1403a2110 |
| LOCAL_INTERACTION_SUCCESS | 0x140305910 |
| OPEN_CHEST | 0x1401f8f30 |
| POWER_UP_COLLECT_REQUEST | 0x1402e8330 |
| REMOVE_ALL_COMMON_OBJECT | 0x1403a8c80 |
| REMOVE_ALL_CURSED_OBJECT | 0x1403a8cc0 |
| REMOVE_ALL_EPIC_OBJECT | 0x1403a8ca0 |
| REMOVE_ALL_LEGENDARY_OBJECT | 0x1403a8cb0 |
| REMOVE_ALL_MAGICAL_OBJECT | 0x1403a8c70 |
| REMOVE_ALL_RARE_OBJECT | 0x1403a8c90 |
| REMOVE_MAGICAL_OBJECT_FROM_ID | 0x1403a8b70 |
| REMOVE_MELODY | 0x140399150 |
| REMOVE_NEWLY_UNLOCK | 0x140359bf0 |
| REMOVE_RANDOM_COMMON_OBJECT | 0x1403a8a80 |
| REMOVE_RANDOM_CURSED_OBJECT | 0x1403a8b40 |
| REMOVE_RANDOM_EPIC_OBJECT | 0x1403a8ae0 |
| REMOVE_RANDOM_LEGENDARY_OBJECT | 0x1403a8b10 |
| REMOVE_RANDOM_MAGICAL_OBJECT | 0x1403a8a50 |
| REMOVE_RANDOM_RARE_OBJECT | 0x1403a8ab0 |
| RESET_SKILLS | 0x1403a7f60 |
| RESET_STAGGER_RESILIENCE | 0x1403cc1c0 |
| REVIVE_RELEASE_TOKEN | 0x140288590 |
| REVIVE_REQUEST | 0x140287ef0 |
| REVIVE_VALIDATE | 0x1403a26b0 |
| STARTUP_LINK | 0x1403cf880 |
| START_DAYMARE | 0x1401ee4e0 |
| START_NIGHTMARE | 0x1401ee590 |
| TELEPORT_SUBMAP_ENTER | 0x140288b50 |
| TELEPORT_SUBMAP_EXIT | 0x140288c10 |
| TUMOR_FIGHTING_START | 0x1402886b0 |
| TUMOR_FIGHTING_STOP | 0x1402887a0 |
| UPDATE_OBJECT_UI | 0x1403a86e0 |
| UPGRADE_LOWER_SKILL | 0x1403a7ba0 |
| UPGRADE_LOWER_SKILL_TO_LEGENDARY | 0x1403a7d80 |
| UPGRADE_RANDOM_SKILL | 0x1403a77e0 |
| UPGRADE_SPECIFIC_SKILL | 0x1403a79e0 |
| USE_BLOOD_FOUNTAIN | 0x1401f9070 |
| USE_HEAL_FOUNTAIN | 0x1401f9020 |

Item family (read 2026-10-10; back `R.give.remove_random` / `remove_all` /
`duplicate_random`, all three proven in game the same day): none of these handlers reads the event payload.
REMOVE_RANDOM_<R>_OBJECT (0x1403a8a50..0x1403a8b40) calls the picker
0x14039bb60(hero, &guid, rarity, 0) — it walks the owned items at hero+0xd80
(count +0xd88), filters by the item's quality (clamped 0..5), and returns a
random one's def GUID (entry+0x280 -> +0x10 def, +0x88/+0x90) — then the
remover 0x1403985a0(hero, &guid). REMOVE_ALL_<R>_OBJECT (0x1403a8c70..0x1403a8cc0)
passes the rarity to 0x1403a8bf0. DUPLICATE_RANDOM_<R>_OBJECT collects through
0x14039be20 and re-grants through Hero_GrantMagicalObject tagged "Duplicate";
the MAGICAL variant collects rarities 0, 1 and 2 only. Rarity codes: 0 common,
1 rare, 2 epic, 3 legendary, 4 cursed, 6 any (MAGICAL). Not wrapped:
REMOVE_MAGICAL_OBJECT_FROM_ID — it reads a type-1 value but copies only its
first u32 into the GUID it removes, so it cannot name an arbitrary item.

Talent family (read 2026-10-10; backs `R.talent.reset` / `upgrade_random` /
`upgrade_lowest` / `upgrade` / `add_random_ultimate`, rsmm/talent_events.lua;
all five proven in game the same day — the added ultimate is not in the 10
slots, and reset leaves the hero's starting talent):
hero-bound; 10 talent slots at hero+0xff0 (stride 0x20), tier = *(*(slot+0x68)),
0..3, changed through SkillController_SetTier. RESET_SKILLS 0x1403a7f60 (no
payload; HeroController_RemoveSkill on each slot, count into hero+0x1374).
UPGRADE_RANDOM_SKILL 0x1403a77e0 — subscribed with its thunk 0x4f bytes past
the id load, which is why the first sweep missed it — upgrades `count`
(with-data int, default 1) distinct talents below tier 3. UPGRADE_LOWER_SKILL
0x1403a7ba0 / _TO_LEGENDARY 0x1403a7d80: no payload, a random lowest-tier
talent +1 / set to 3. UPGRADE_SPECIFIC_SKILL 0x1403a79e0: with-data int index
into the owned talents (default the last) — **crashes with no talent owned**
(index -1 of a null list). ADD_RANDOM_ULTI_SKILL 0x1403a75d0: draws from
hero+0xfb8 (count +0xfc0), re-rolling `div count` with no zero check — **divides
by zero when no candidate qualifies** (the Sandman-shop rand); qualifying =
*(cand+0x70)+0x10 object's +0xc0 byte == 0 and the +0x70 object's +0x40 byte
!= 0, and a null +0x10 makes the engine read address 0xc8. The SDK checks both
before sending.

Status family (backs `R.status`, rsmm/status.lua): subscribed by the hero's
character controller on the hero dispatcher's channel map (entity+0x500 =
0x4d8+0x28). CLEAR_STATUS 0x1403bfb00 → 0x1403c8d40 clears the listed status
keys from the value store at this+0x4c8 and checks that store for null;
CLEAR_STAGGER 0x1403cc1d0 zeroes this+0x33c; RESET_STAGGER_RESILIENCE 0x1403cc1c0
zeroes this+0x344. Not wrapped: CLEAR_CHILLED / CLEAR_ROSE_SEED (0x1403cbc40 /
0x1403cbc60) hand the same this+0x4c8 to 0x140749720 WITHOUT the null check;
FORCE_DEATH 0x1403cbc80 activates this+0x588.

Revive (not wrapped, parked): REVIVE_VALIDATE 0x1403a26b0 activates hero+0x13f0
and increments the u16 at HUD-mirror (hero+0x1d80) +0x14, beside the reroll
count at +0x16 — most likely the revive-token count, unconfirmed. HERO_REVIVE
0x1403a2700 (hero) / 0x1403cbbb0 (character) is a long scene-context routine in
the multiplayer revive flow; read it in full before sending it.

Melody, control, run flow (read 2026-10-10):
* CHOOSE_MELODY 0x140399090 / REMOVE_MELODY 0x140399150 (hero) name the melody
  by the oCString at +0x50, compared with *(*(def+0x48)+0x18) of each live
  MelodyDefinition — NOT a GUID (the first R.melody.choose guessed +0x38/+0x48
  and could never match). Backs `R.melody.choose/remove/names` (rsmm/melody.lua).
* LOCK_CONTROL 0x1403a7580 / UNLOCK_CONTROL 0x1403a75a0 (hero, no payload): a
  counter at hero+0xc50; the apply/release branches test byte hero+0xc54 in
  opposite senses, meaning unestablished. Backs `R.control` (counts its own locks).
* GAME_END_SUCCESS / _SUCCESS_SKIP_NEXT / _FAILED (0x140289000 / 0x140289010 /
  0x140289020, no payload) are WORLD events: subscribed by the game-mode
  controller (0x140284db0) on oCEntitySceneContext+0x340's channel map. Guarded
  by an already-ended byte (this+0x213) and a context vtable slot +0xd8 (likely
  authority). Backs `R.run.next_chapter/win/lose` (rsmm/run_flow.lua), which
  learns the world dispatcher from the bus by RTTI — only inside a live chapter,
  since the same dispatcher survives the chapter switch (an end sent during the
  transition would hit the next chapter); one end per chapter. Not wrapped:
  GAME_END_NEXT_CHAPTER (level load's follow-up step), TELEPORT_SUBMAP_ENTER/EXIT
  (they only set the player-location flags after a move), START_DAYMARE /
  START_NIGHTMARE (0x1401ee4e0 / 0x1401ee590: on the day/night component they
  restart the CURRENT phase's timer, only when the phase matches, then schedule
  something through 0x140205120 — unread).

Read so far: GAIN_DREAM_SHARDS 0x1403a72b0 and GAIN_INGREDIENT 0x14039acc0
(layouts in their vftable symbols; back `R.shards.gain` / `R.ingredient`).
Not in this table: the skill/item events that subscribe through another path
(UPGRADE_RANDOM_SKILL), and events with no subscriber found by either shape.
