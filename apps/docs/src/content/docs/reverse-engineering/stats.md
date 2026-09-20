---
title: Stats & XP
description: The three surfaces hero stats live on, the CRC-keyed value store's read and write paths, and why a raw write is transient unless it becomes a modifier.
---

:::note
Status: RE complete; `R.stat` / `R.xp` / `R.combat` ship in
`src/loader/lib/rsmm.lua` and are **in-game proven** (XP grant drives the engine's
own level-up loop; `R.stat.modify` composes and survives recompute).
:::

## The three stat surfaces

Ravenswatch keeps hero stats in three distinct places. "Everything grantable"
means covering all three:

| Surface | What lives there | Grant primitive | SDK |
|---|---|---|---|
| **Plain shard field** | current dream shards (hot path, mirrored to the HUD) | `Hero_ModifyDreamShards(hero, delta, tags)` | `R.shards.get/add/spend/set` |
| **XP component** | level + xp-within-level (own component, curve table) | `Hero_GainExperience(xpComp, xpGain)` | `R.xp.grant` |
| **Generic value store** | everything else: max-health mult, attack power, crit, move speed, cooldown, life-steal, dream shards, xp multipliers, status stacks | modifier / override write | `R.stat.get/set/modify` |

Dream shards are the exception with a plain `f32` at `hero+0x15c8` — see
[Heroes](/reverse-engineering/heroes/). Everything else is keyed in the store.

:::caution[Corrected 2026-09-18]
This field was documented as **HP** for months, and the routine as
`Entity_ModifyHealth`. It is the dream-shard count: the routine fires
`dt_shard_gain` / `dt_shard_loss`, clamps only at 0, and is what the Sandman
spends through. `R.combat.*` and `R.entity.hp/max_hp/hp_frac` still work as
deprecated aliases of `R.shards`.
:::

## Real health

HP lives on the hero's `oCEntityCpntHitPoint`: `component = *(*(hero+0x2f8)+0x78)`,
current HP at `+0xe8`, max at `+0xec`. `*(hero+0x2f8)` is the sibling
`oCDtEntityCpntCharacterController`, not the entity (measured in game); the
component's owner at `+0x8` is the hero's `oCEntity`, `*(hero+0x8)`. The only
writer is `HitPoint_SetHitPoints` (`0x140822db0`). It clamps to `[0, max]`, runs
the death listeners (`+0x108`) when HP crosses 0 and the change listeners
(`+0xf0`) on any change, replicates, and writes `current/max` to the UI bar.
Thirteen gameplay readers walk the same chain; the "Increase damage if
critical health" check and the life-bar listener both divide the pair.

`R.hp.get/max/frac` read it, and `R.hp.set/heal/damage` go through the setter.
Every access re-checks the link: RTTI must name a HitPoint class, and the
component's owner must be the hero's entity. Static RE only (2026-09-18);
the in-game proof is still owed. In co-op HP is host-authoritative, so a
client's write is not expected to stick.

:::caution[Units]
Store values are **display × 100**. To set a displayed number, pass
`display / 100`.
:::

## Dream shards

`Hero_ModifyDreamShards` is the game's own gain(+)/spend(−) routine, resolved by
pattern. Hero-only — it derefs the HUD mirror. See
[Combat & damage](/reverse-engineering/combat-damage/).

## XP / level-up

`Hero_GainExperience(xpComp, xpGain)` adds `*(int*)(xpGain + 0x50)`. It reads the
current level/xp, loops subtracting the per-level threshold and levelling up, then
commits via `XpComponent_SetXp` / `XpComponent_SetLevel`.

- Progress struct: `*(xpComp + 0x108)` → `{[0]=level u32, [4]=xp-in-level u32}`.
- Curve def: `*(xpComp + 0x10)` → `{+0x1d0 has-table, +0x1d8 uint[] thresholds,
  +0x1e0 count/maxLevel}`.
- `XpComponent_SetLevel` fires the `_XP_LEVEL_UP` named event and writes
  custom-flag `0x12e831f2` (= level, f32). `XpComponent_SetXp` writes custom-flag
  `0x12e831f1` (= xp delta). The `level_up_*` analytics are downstream telemetry,
  not the grant.

### Locating `xpComp`

The XP component is a *sibling component* on the hero's `oCEntity`, not a fixed
hero offset:

```
entity = *(heroController + 0x2f8)          # (or hero+0x2f8 itself on some paths)
arr    = *(entity + 0x190); count = *(uint*)(entity + 0x198)
xpComp = arr[i] where *(arr[i]) == XpComponent_vftable (0x140f23200)
invariant: *(xpComp + 8) == entity          # every component's owner back-ptr
# alt: Entity_GetComponentByTester(entity, XpComponent_TypeTester = 0x141476e00)
```

In-game the exact-vftable scan kept missing — the live component's vftable is a
subclass vftable. `grant()` (main thread only; the walk calls each component's
virtual `IsKindOf`) falls back to `Entity_GetComponentByTester`, logs the actual
vftable of the hit, and caches the component per hero so the tick-thread readers
stay pure-memory.

## The generic value store

### Read path

```
ctx   = *(hero + 0x2f8)      # POINTER field — load it, do NOT pass hero+0x2f8 itself
store = *(ctx + 0x4c8)       # EntityValue_Get(ctx, out, key) does this deref

EntityValue_Lookup(store, &out, key):
  1. linear-scan OVERRIDE array  store+0xc0 (count +0xc8, 0x38-byte entries, key @+0x00)
  2. fallback base hash map       store+0x80 (Fibonacci mult 0xde5fb9d2630458e9)
  3. miss => union value 0
```

:::danger
Passing the **field address** `hero+0x2f8` instead of loading the pointer makes
the engine read `*(hero+0x7c0)` — a float — as the store pointer and fault. That
was a real in-run crash (store = `0xbf800000` = `-1.0f`, read at `store+0xc8`).
The engine's own damage-taken caller loads `ctx = *(param_1+0x2f8)` before every
`EntityValue_Get`.
:::

`oCEntityValueUnion` (0x20 bytes, vftable `0x140f95008`): `+0x08` inline sentinel
(`== 4` ⇒ value inline), `+0x10` inline value (f32/int32), `+0x18` type-tag byte
(`0` = int/float). Inside a 0x38 override **entry** the union sits at `entry+0x08`,
so sentinel `entry+0x10`, value `entry+0x18`, tag `entry+0x20`.

### Write path

There is no clean setter export — it's an inlined find-or-create:

```
scan store+0xc0 for key
  found + changed -> write union value (+ u32@entry+0x28, u16@entry+0x2c)
  miss            -> slot = EntityValueOverride_Alloc(store+0xc0, count, 1)
                     EntityValueEntry_Ctor(slot, src)     # auto-increments count at store+0xc8
```

**`store+0xc0` is the computed result cache**, so a raw override write is
**transient**: `EntityValueStore_Recompute` rebuilds it from base + modifiers on
the next dirty event (item pickup, level-up, …). Base values live in the hash map
at `store+0x80`.

Reactive events fire for free — the store's observer lists (`store+0x108`,
`+0x120`, `+0x138`, `+0x150`, `+0x158`) dispatch on any write, so a value change
already emits the reactive gameplay-bus events. There is no separate "set signal"
call.

## Stat key catalog

Keys are **structured base+index ids, not CRC32 of the label** — adjacent stats
differ by 2, and slot families are `base + 2·slotIndex`. Source of truth is
`EntityValueRegistry_RegisterAll` plus siblings `FUN_1401d66a0` (combat/build),
`FUN_1401da350` (session: shards/xp/difficulty), `FUN_1401d9070` (status effects);
each stores its key at `def+0x6c`.

| Stat | Key | Kind |
|---|---|---|
| max health (base "Vitality") | `0x188671a6` | f32 |
| max health % | `0x15c9296d` (default 1.0) | f32 |
| attack power (base) | `0x15a486c4` | f32 |
| attack power per slot | `0x15a5cf40 + 2·slot` (basic `0x15a5cf51`, dash `0x183a609a`) | f32 |
| crit chance (base) | `0x15c7d482` | f32 |
| crit chance per slot | `0x15c7d482 + 2·slot` (dash `0x183a60b6`) | f32 |
| crit damage | `0x15c82d13` | f32 |
| move speed ("Move Speed Ratio") | `0x044dadde` | f32 |
| cooldown reduction (base) | `0x15b45d80` | f32 |
| cooldown reduction per slot | `0x15b45d80 + 2·slot` (dash `0x183a5fc9`) | f32 |
| life steal | `0x15c028c2` | f32 |
| life on hit (base) | `0x1894f1a2` | f32 |
| dream shards (currency count) | `0x171c27b5` | int |
| Global Xp Modifier | `0x187afd1d` | f32 |
| Difficulty Xp Modifier | `0x19bddb2e` | f32 |

Slot index: `primary=0, secondary=1, defensive=2, trait=3, ultimate=4`.
Status-effect family: `0x16ede056 + 2·i` →
Strength/Regen/Haste/Concealed/Resistant/Rooted/Vulnerable/Ignite/Chilled/Poison;
Shield `0x173fcd75`, Bleed `0x173fcdac`, Cursed `0x1a5d3d69`, Marked `0x1a40367d`.
The full modifier/difficulty key table is in
[Game modifiers](/reverse-engineering/game-modifiers/).

**Attack power is a percentage, not a flat bonus.** Every hit is built by the
hit-value constructor (`0x1401ce0b0`) with a damage multiplier of `1.0` at
`hit+0xcc`. The hit resolver then adds the base value (clamped at 0, `0x1403c6e8e`)
and the ability slot's value (`0x1403d6632`), and multiplies the damage by the
sum:

```
damage = base × (1.0 + max(0, attack_power) + attack_power[slot]) × hit+0xd0
```

So `0.5` in the store is **+50% damage**, which the stat screen shows as
`+50`: it is the same ×100 as crit, where `0.15` shows as 15%. `50` in the
store is +5000%, a 100× overdose.

**Not keyed**, so not `R.stat`-settable: raw XP amount (use `R.xp`), armour base
(a hero field, `def+0x6c = 0`), gold (the game has none — only dream shards).

## SDK surface

```lua
R.stat.get("attack_power")          -- read (always safe)
R.stat.names()                      -- known stat names
R.stat.enable_writes()              -- opt in to writes
R.stat.set("move_speed", 1.5)       -- write override cache (TRANSIENT)
R.stat.add("crit_chance", 0.1)      -- current + delta (transient)
R.stat.stick("attack_power", 0.5)   -- durable by re-assertion (+50%)
R.stat.unstick("attack_power")      -- stop pinning
R.stat.modify("attack_power", 0.5)  -- durable engine modifier (+50%, composes)
R.xp.level(); R.xp.xp()             -- read
R.xp.grant(100)                     -- add XP (levels up) — already durable
```

Writes are engine-mutating: **main thread only** (gameplay-event handler or
`R.schedule.next_main`), opt-in via `enable_writes()`, and fail closed on any
implausible pointer. Loader reads/writes are page-guarded, so a wrong deref
no-ops; the residual crash surface is the engine calls, which are gated behind
plausibility checks. Stat modifiers persist in the **run** save, not the profile.

## Making a write durable

`EntityValueStore_Recompute` (`FUN_140749a90`) reseeds each key from its base
value whenever it goes dirty (`store+0x64 & 8`), then folds in every entry of the
**per-key modifier registry** (a SwissTable at `store+0x88`), applying each via a
vcall `(*(modifier+0x18))(modifier, valueUnion)`. So a raw cache poke is discarded.

The engine's own entry point is **`EntityValueStore_ApplyModifierEvent`**
(`FUN_14074b2f0`): it takes a built modifier request, constructs an
`oCEntityValueModifier`, inserts it into the registry, and re-folds the cache.
Combine mode comes from the value def:

| op | fold | meaning |
|----|------|---------|
| 1  | `val += amount * scale` | additive |
| 2  | `val = amount`, base `= base` | set / override |
| 3  | replace modifier with matching source/id | match-replace |
| 4  | keep smallest-delta | min / priority cap |

### Two durable strategies

**1. Re-assertion — `R.stat.stick`.** Keep re-applying the override poke after
each recompute, drift-gated on the main thread. This *pins the final value*; it
does not compose with the game's modifier math, but it is safe — no forged game
objects, no SwissTable surgery, no new native code.

**2. Native modifier event — `R.stat.modify`.** The request is an
`oCGameEventNetworkModifier` named event (vftable `0x140f322d0`), built by
`ModifierEvent_Ctor`. It rides the same named-event bus as `R.give`.

Event layout (0x98 bytes): `+0x00` vftable, `+0x08` state u32 (2 while building,
**0 = ready**), `+0x20` name `oCString {ptr, cap|0x80000000, len}`, `+0x30` name
hash (bus routing only), `+0x38` modifier id (`-1` = fresh; op 3 match-replaces on
it), `+0x50` serial u32, **`+0x54` stat key**, `+0x58` counter, **`+0x60` embedded
`oCEntityValueUnion` carrying the amount**, `+0x80` **duration f32** (`< 0` =
permanent, and also lands the modifier in the store's persistent list; the give
handler uses `5.0`), `+0x84`/`+0x88` multipliers (1.0), `+0x8c` flag u8 (1),
`+0x90` source entity (0 = no lifetime binding; non-zero registers an entity-death
watch at `entity+0x570`).

Consumption: key = `ev+0x54`; the **op and modifier type come from the value DEF**
looked up in the base hashmap `*(store+0x80)` — `def+0x70` = merge op,
`def+0x74` = typed-modifier factory switch (0..6), `def+0x68` = max modifier count
(0 = unlimited). `mod+0x3c` = remaining duration, `mod+0x40` = apply timestamp. In
co-op non-authority the function *relays* the event to the host over the
named-event bus instead of applying locally — free correctness for us.

`R.stat.modify(name, amount[, duration])` forges the event in scratch memory (the
union built through the engine's own ctor → destruct → `_InitAsType` sequence) and
calls `ApplyModifierEvent` directly — no bus, no name hash needed. It composes with
item/talent modifiers and survives recompute. Don't combine it with `stick` on the
same stat.

**Delivery: the modifier travels on the hero's event bus, as `ADD_MODIFIER`.** None of
the 13 vanilla places that build a modifier event call `ApplyModifierEvent`; all of them
dispatch the event on the entity's bus (`NamedEvent_Dispatch`), which routes by the
channel id at `ev+0x30` = `NamedEvent_Id_FromCrc(0, crc32("ADD_MODIFIER"))` = `816961080`,
the same id a vanilla upgrade carries on the same dispatcher `R.give` captures. That is
`R.stat.modify`'s default route, proven in game (2026-09-19): `+1` counts exactly once,
the in-run stat strip follows, and a permanent (`-1`) modifier survives a chapter change
like the game's own upgrades. It needs the hero's dispatcher (the hero must have acted
once) and returns `false` until then. The dispatch reaches `R.on("*")` handlers
**synchronously**, so a mod that calls `modify` from an event handler must latch before
calling; the SDK refuses a nested call (steamroller once recursed 99 deep without it).

`route = "direct"` calls `ApplyModifierEvent` itself (works from the value context alone).
Its defects are why it is not the default: a permanent `-1` is counted **twice** (the
`-1`-only branch at `0x14074ba3c` also records it in the run's persistent store), so on this
route "permanent" is sent as a `1e6` s duration instead, which counts once but is **dropped
at the next chapter**.

**The in-run stat strip reads a cache, not the store.** It shows
`100 × f32[obj+0x308]` for attack (`+0x304` vitality, `+0x30c` armor) with
`obj = *(*g_StatReportRoot + 0x20)`, and the engine refreshes that only when it folds a
modifier itself. So `R.stat.set` / `stick` change damage but leave the strip at its old
value (a pinned 40 showed `0`), while `R.stat.modify` moves both. `R.stat.cached(name)`
reads that cache for diagnostics.

## The registry catalog (mined 2026-09-20)

`tools/mine_stat_keys.py` reads the engine's own registration calls and writes
`data/stat_keys.json`: **221 keyed values**, name and key, which `rsmm symbols
gen` turns into `src/loader/lib/stats_gen.lua` and `R.stat.keys` merges in (the
hand-RE'd names win, and a key already spoken for gains no second name).

Five registration shapes feed one catalog. `Register_A(list, key, &name, desc)`
takes the key in `edx`; three `Register_B` helpers take it in `ecx`; and an
allocator form assigns the name into `def+0x08` and stores the key at
`def+0x6c`, sometimes as an immediate and sometimes through a register. Two
registrations are still unparsed on purpose: their keys are computed in a loop
(`base + 2*i`), which is the status family the SDK already derives by hand.

⚠ **Pair on structure, never on "the nearest string".** A block stages its name
several instructions before the call, and the description and editor-icon path
sit between two registrations, so the naive pairing is off by one *whole*
registration and looks plausible: it put `attack_power` on "Attack power basic"
and armour on a neighbour's key. The miner ties each name to the stack slot the
call actually passes, and checks the staged `0x80000000 | len` against the
string's real length.

What it settled:

* **Armour is registered with key `0`** — a definition, a display name and an
  editor icon, but no id. It is genuinely unaddressable through the store, so no
  `R.stat` call can read or write it; its live value is a plain field at
  `hero+0x31c` (written by `0x1403aab60`, beside the attack cache at `+0x318`).
  Five armour *effects* are keyed and usable: "Armour per missing health"
  (`0x16917db7`), "Armour increase crit damage" (`0x16917ec8`), "Armour into AP"
  (`0x174a0363`), "Armour per ability under cooldown" (`0x170329b8`) and
  "Transform over healing to armour" (`0x170435c4`).
* **Ten of twelve hand-RE'd keys confirmed** by the engine's own labels
  (`0x188671a6` is "Vitality", `0x15c9296d` is "Max health", `0x15b45d80` is
  "CD reduce"). The two that are absent, `xp_multiplier` and
  `difficulty_xp_mult`, are scene-context values and live in `R.game`'s table.
* **Two corrections.** `status_poison` pointed at `0x16ede068`, which the engine
  calls **"Weak"**; real Poison is `0x173fcdaa`, in the shield/bleed family. And
  `status_cursed` is the engine's **"Disease"** — the name stays for the mods
  that use it, with the label recorded.

## Symbols

Read/write primitives: `EntityValueOverride_Alloc`, `EntityValueEntry_Ctor`,
`EntityValueUnion_DefaultCtor` / `_InitAsType` / `_CopyAssign` / `_Compare` /
`_Destruct`, `Hero_GainExperience`, `XpComponent_SetLevel`, `XpComponent_SetXp`,
`Entity_GetComponentByTester`, `Entity_GetComponentFast`, `XpComponent_vftable`,
`XpComponent_TypeTester`.

Durable-modifier path: `EntityValueStore_Recompute`,
`EntityValueStore_ApplyModifierEvent`, `EntityValueStore_InitBaseValues`,
`ModifierEvent_Ctor`, `oCGameEventNetworkModifier_vftable`.
