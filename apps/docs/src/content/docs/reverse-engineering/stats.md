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
| **Plain HP field** | current/max HP (hot path, mirrored to the HUD) | `Entity_ModifyHealth(hero, delta, tags)` | `R.combat.heal/damage/set_hp` |
| **XP component** | level + xp-within-level (own component, curve table) | `Hero_GainExperience(xpComp, xpGain)` | `R.xp.grant` |
| **Generic value store** | everything else: max-health mult, attack power, crit, move speed, cooldown, life-steal, dream shards, xp multipliers, status stacks | modifier / override write | `R.stat.get/set/modify` |

HP is the exception with a plain `f32` at `hero+0x15c8` (max at `+0x15cc`) — see
[Heroes](/reverse-engineering/heroes/). Everything else is keyed in the store.

:::caution[Units]
Store values are **display × 100**. To set a displayed number, pass
`display / 100`.
:::

## HP

`Entity_ModifyHealth` is the game's own heal(+)/damage(−) routine, resolved by
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

**Not keyed**, so not `R.stat`-settable: raw XP amount (use `R.xp`), armour base
(a hero field, `def+0x6c = 0`), gold (the game has none — only dream shards).

## SDK surface

```lua
R.stat.get("attack_power")          -- read (always safe)
R.stat.names()                      -- known stat names
R.stat.enable_writes()              -- opt in to writes
R.stat.set("move_speed", 1.5)       -- write override cache (TRANSIENT)
R.stat.add("crit_chance", 0.1)      -- current + delta (transient)
R.stat.stick("attack_power", 500)   -- durable by re-assertion
R.stat.unstick("attack_power")      -- stop pinning
R.stat.modify("attack_power", 50)   -- durable engine modifier (composes)
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

## Symbols

Read/write primitives: `EntityValueOverride_Alloc`, `EntityValueEntry_Ctor`,
`EntityValueUnion_DefaultCtor` / `_InitAsType` / `_CopyAssign` / `_Compare` /
`_Destruct`, `Hero_GainExperience`, `XpComponent_SetLevel`, `XpComponent_SetXp`,
`Entity_GetComponentByTester`, `Entity_GetComponentFast`, `XpComponent_vftable`,
`XpComponent_TypeTester`.

Durable-modifier path: `EntityValueStore_Recompute`,
`EntityValueStore_ApplyModifierEvent`, `EntityValueStore_InitBaseValues`,
`ModifierEvent_Ctor`, `oCGameEventNetworkModifier_vftable`.
