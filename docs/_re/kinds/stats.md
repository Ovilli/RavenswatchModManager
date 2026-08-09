# Stats — granting / setting hero stats (health, XP, damage, speed, …)

> 📖 Prose version on the docs site: **https://docs.rsmm.me/reverse-engineering/stats/** (`apps/docs/src/content/docs/reverse-engineering/stats.md`).
> This file stays as the raw RE field notes.


> Status: RE complete 2026-07-13 (three parallel Ghidra passes, decompile-verified
> against the live post-2026-07-09 build, image base `0x140000000`). Read path
> shipped + safe; write / grant paths shipped **experimental, pending in-game
> verification**. SDK: `R.stat`, `R.xp`, `R.combat` in `src/loader/lib/rsmm.lua`.

## The three stat surfaces

Ravenswatch keeps hero stats in three distinct places. "Everything grantable" =
covering all three:

| Surface | What lives there | Grant primitive | SDK |
|---|---|---|---|
| **Plain HP field** | current/max HP (hot path, mirrored to the HUD) | `Entity_ModifyHealth(hero, delta, tags)` | `R.combat.heal/damage/set_hp` (proven) |
| **XP component** | level + xp-within-level (own component, curve table) | `Hero_GainExperience(xpComp, xpGain)` | `R.xp.grant` (experimental) |
| **Generic value store** | everything else: max-health mult, attack power, crit, move speed, cooldown, life-steal, dream shards, xp multipliers, status stacks | value-store override write | `R.stat.get/set/add` (experimental) |

HP is the exception that has a plain `f32` @`hero+0x15c8` (max @`+0x15cc`) — see
`heroes.md`. Everything else is keyed in the value store.

## 1. HP — already shipped

`Entity_ModifyHealth = FUN_140399a10`(stale addr; resolved by pattern) — the
game's own heal(+)/damage(−) routine. Hero-only (derefs the HUD mirror). See
`combat-stat-api` memory + `enemy-damage.md`. `R.combat` is in-game proven.

## 2. XP / level-up

**Grant primitive** `Hero_GainExperience = FUN_1402e2f00(xpComp, xpGain)`
(decompile-verified): the amount added is `*(int*)(xpGain + 0x50)`. It reads the
current level/xp, loops subtracting the per-level threshold and leveling up, then
commits via `XpComponent_SetXp`/`XpComponent_SetLevel`.

- Progress struct: `*(xpComp + 0x108)` → `{[0]=level u32, [4]=xp-in-level u32}`.
- Curve def: `*(xpComp + 0x10)` → `{+0x1d0 has-table, +0x1d8 uint[] thresholds, +0x1e0 count/maxLevel}`.
- `XpComponent_SetLevel = FUN_1402e3190` fires the `_XP_LEVEL_UP` named event and
  writes custom-flag `0x12e831f2` (=level, f32). `XpComponent_SetXp = FUN_1402e3630`
  writes custom-flag `0x12e831f1` (=xp delta).
- Max-level gate: `FUN_1402e2d90`. Analytics (`level_up_reach`/`level_up_book`) are
  downstream telemetry (`FUN_1401f6bf0`/`FUN_1401f7c20`), not the grant.

**Locating `xpComp` from the captured hero** (decompile-verified): the XP component
is a *sibling component* on the hero's `oCEntity`, not a fixed hero offset.

```
entity = *(heroController + 0x2f8)          # (or hero+0x2f8 itself on some paths)
# component array:
arr    = *(entity + 0x190); count = *(uint*)(entity + 0x198)
# scan for the XP component by vtable:
xpComp = arr[i] where *(arr[i]) == XpComponent_vftable (0x140f23200)
invariant: *(xpComp + 8) == entity          # every component's owner back-ptr
# alt: Entity_GetComponentByTester(entity, XpComponent_TypeTester=0x141476e00)
```

The SDK (`R.xp`) scans the component array for `XpComponent_vftable` and verifies
`comp+8 == entity`; both entity-deref forms are tried (page-guarded reads never
fault). Grant builds a zeroed `xpGain` scratch, sets `+0x50 = amount`, calls
`Hero_GainExperience`.

**2026-07-17 — engine-tester fallback.** In-game the exact-vftable scan kept
missing ("XP component not found"): the live component's vftable is (suspected)
a subclass vftable, not `0x140f23200`. `grant()` (main thread only — the walk
calls each component's virtual `IsKindOf`) now falls back to
`Entity_GetComponentByTester(entity, XpComponent_TypeTester)`, logs the actual
vftable of the hit (rebased image VA — use it to correct the symbol map), and
caches the component per hero so the tick-thread readers (`level`/`xp`) stay
pure-memory. If both paths miss, a one-shot diagnostic dumps each candidate
entity's component count and the first 12 component vftables to the log.

## 3. Generic value store — the master "set any stat"

### Store + read (mapped earlier, see `entity-values.md`)

```
ctx   = *(hero + 0x2f8)      # POINTER field — load it, do NOT pass hero+0x2f8 itself
store = *(ctx + 0x4c8)       # EntityValue_Get(ctx, out, key) does this deref
# Engine caller proof: FUN_140399d00 (damage-taken) loads ctx = *(param_1+0x2f8)
# before every EntityValue_Get call. Passing the FIELD ADDRESS hero+0x2f8 makes
# the engine read *(hero+0x7c0) — a float — as the store pointer and fault in
# EntityValue_Lookup's count read (the 2026-07-15 in-run crash, minidump
# c27b0619: store=0xbf800000 = -1.0f, READ @store+0xc8).
EntityValue_Lookup(store, &out, key):
  1. linear-scan OVERRIDE array  store+0xc0 (count +0xc8, 0x38-byte entries, key @+0x00)
  2. fallback base hash map       store+0x80 (Fibonacci mult 0xde5fb9d2630458e9)
  3. miss => union value 0
```

`oCEntityValueUnion` (0x20 bytes, vft `0x140f95008`): `+0x08` inline sentinel
(`==4` ⇒ value inline), `+0x10` inline value (f32/int32), `+0x18` type-tag byte
(`0` = int/float). Inside a 0x38 override **entry** the union sits at `entry+0x08`
(so sentinel `entry+0x10`, value `entry+0x18`, tag `entry+0x20`).

### Write path (RE'd 2026-07-13, no clean setter export — inlined find-or-create)

Canonical copy `FUN_140749a90` @`LAB_14074a810`:

```
scan store+0xc0 for key
  found + changed -> write union value (+ u32@entry+0x28, u16@entry+0x2c)
  miss            -> slot = EntityValueOverride_Alloc(store+0xc0, count, 1)  # FUN_140770290
                     EntityValueEntry_Ctor(slot, src)                        # FUN_140747120
                     (auto-increments count at store+0xc8)
```

Union helpers: `EntityValueUnion_DefaultCtor FUN_14082aa60`, `_CopyAssign
FUN_14082b1d0`, `_Compare FUN_14082ceb0`, `_InitAsType FUN_14082d670`, `_Destruct
FUN_14082dae0` (supersedes the stale `FUN_14082ca50`).

**Durability caveat.** `store+0xc0` is the **computed result cache**; the engine
rebuilds it from base+modifiers on the next stat recompute (item pickup, level up,
…), so a raw override write is **transient**. The permanent grant (the game's own
mechanism) adds an `oCEntityValueModifier` to the entry's holder (`entry+0x30`, via
holder vtable vcall `+0x18`; pattern in `FUN_140747f20`) so recompute keeps it.
That durable path is documented but not yet wired — `R.stat.set` currently writes
the override cache (re-assert on demand). Base values live in the hash map
`store+0x80`.

**Reactive events fire for free.** The store's observer lists (`store+0x108/
+0x120/+0x138/+0x150/+0x158`, per-key notify `FUN_1406f6510`) dispatch on any store
write — so a value change already emits the reactive gameplay-bus events; there is
no separate "set signal" call. The standalone `EntityCpntValueSignal::setValue`
was not isolated (RTTI/vftable not indexed by the MCP bridge) and isn't needed.

### Stat key catalog

Keys are **structured base+index ids, NOT CRC32 of the label** (adjacent stats
differ by 2; slot families are `base + 2·slotIndex`). Source of truth =
`EntityValueRegistry_RegisterAll` + siblings `FUN_1401d66a0` (combat/build stats),
`FUN_1401da350` (session: shards/xp/difficulty), `FUN_1401d9070` (status effects);
each stores its key at `def+0x6c` via `FUN_1406de840(list, KEY, name, …)`.

| stat | key | kind |
|---|---|---|
| max health (base "Vitality") | `0x188671a6` | f32 |
| max health % | `0x15c9296d` (dflt 1.0) | f32 |
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
Status-effect family (`FUN_1401d9070`): `0x16ede056 + 2·i` →
Strength/Regen/Haste/Concealed/Resistant/Rooted/Vulnerable/Ignite/Chilled/Poison;
Shield `0x173fcd75`, Bleed `0x173fcdac`, Cursed `0x1a5d3d69`, Marked `0x1a40367d`.
Full modifier/difficulty key table: `game-modifiers.md`.

**Not keyed** (so not `R.stat`-settable): raw XP amount (use `R.xp`), armour base
(a hero field, `def+0x6c = 0`), gold (Ravenswatch has no gold — only dream shards).

## SDK surface (`rsmm.lua`)

```lua
R.stat.get("attack_power")          -- read (always safe)
R.stat.names()                      -- known stat names
R.stat.enable_writes()              -- opt in to experimental writes
R.stat.set("move_speed", 1.5)       -- write override cache (TRANSIENT — see below)
R.stat.add("crit_chance", 0.1)      -- current + delta (transient)
R.stat.stick("attack_power", 500)   -- DURABLE: set + re-assert after recompute
R.stat.unstick("attack_power")      -- stop pinning (engine restores its value)
R.stat.sticky()                     -- {name = value} currently pinned
R.xp.level(); R.xp.xp()             -- read
R.xp.grant(100)                     -- add XP (levels up), experimental — already durable
```

**Transient vs durable.** `R.stat.set` writes the override *cache*
(`store+0xc0`), which `EntityValueStore_Recompute` rebuilds from base + engine
modifiers on the next dirty event (item pickup, level-up, …) — so a bare `set`
is discarded. **`R.stat.stick`** makes a value durable by re-asserting it on the
main-thread gameplay pump: it re-applies the value whenever the live value has
drifted off target (drift-gated, so steady-state = one guarded read per pinned
stat per gameplay event, zero writes until the engine actually clobbers it).
This *pins the final value* — it does not compose with the game's own modifier
math. `R.xp.grant` goes through the engine's real gain-experience routine, so XP
is already durable without pinning.

Writes are engine-mutating: **main thread only** (gameplay-event handler /
`R.schedule.next_main`, see the `loader-thread-model` memory), opt-in via
`enable_writes()`, and fail closed (log + no-op) on any implausible pointer.
Memory reads/writes in the loader are page-guarded, so a wrong deref no-ops
rather than crashing; the residual crash surface is the engine calls
(`EntityValueOverride_Alloc`, `Hero_GainExperience`), which are gated behind
plausibility checks. **In-game verification pending.**

## Durable modifier path (RE 2026-07-14 — why `R.stat.set` is transient, and the fix)

`R.stat.set` pokes the **override cache** at `store+0xc0` (the folded per-key
result). That cache is not authoritative — it is *rebuilt* by
**`EntityValueStore_Recompute`** (`FUN_140749a90`) whenever a key goes dirty
(`store+0x64 & 8`). Recompute reseeds each key from its base value then folds in
every entry of the **per-key modifier registry** (a SwissTable at `store+0x88`),
applying each modifier via a vcall `(*(modifier+0x18))(modifier, valueUnion)`.
So a raw cache poke is discarded on the next gameplay event that touches the key
— exactly the observed "re-asserts on recompute".

**Durable = register a modifier the recompute folds in.** The engine's own entry
point is **`EntityValueStore_ApplyModifierEvent`** (`FUN_14074b2f0`): it takes a
built modifier request, constructs an `oCEntityValueModifier`, inserts it into the
`store+0x88` registry, and re-folds the cache. Combine mode (`op`, from the
value-def `+0x68`):

| op | fold | meaning |
|----|------|---------|
| 1  | `val += amount * scale` | **additive** (+X attack) |
| 2  | `val = amount`, base `= base` | **set / override** |
| 3  | replace modifier with matching source/id | **match-replace** |
| 4  | keep smallest-delta | **min / priority cap** |

The modifier request is an **`oCGameEventNetworkModifier`** named event
(vftable `0x140f322d0`), built by **`ModifierEvent_Ctor`** (`FUN_140389fb0`):
event id `@+0x30`, value union `@+0x60`, scale `1.0 @+0x84/+0x88`, then a virtual
fill `(*(valueDef+0x20))(valueDef, event)` populates op/key/amount. Crucially this
rides the **same named-event bus as `R.give`** — so a durable modifier can be
dispatched with `NamedEvent_Dispatch(entity+0x4d8, event)` rather than
hand-editing the SwissTable.

**Two durable strategies.**

1. **Re-assertion — SHIPPED (`R.stat.stick`).** Rather than register a real
   engine modifier, keep re-applying the override-cache poke after each recompute
   (drift-gated, main-thread). This *pins the final value*; it does not compose
   with the game's modifier math, but it is safe — reuses only the existing
   page-guarded, gated `R.stat.set`, no forged game objects, no SwissTable surgery,
   no new native code. Default durable path today. In-game verification still
   pending, but its crash surface is identical to the already-shipped transient write.

2. **Native modifier event — WIRED 2026-07-16 (`R.stat.modify`, experimental,
   playtest pending).** The payload was fully decoded during the 2026-07-15 crash
   triage: `FUN_1403c7560` (give-handler) constructs a complete
   `oCGameEventNetworkModifier` inline, giving every field offset, and the
   `ApplyModifierEvent` decompile shows exactly which fields it consumes.

   Event layout (0x98 bytes; `ModifierEvent_Ctor` `FUN_140389fb0` = the canonical
   init): `+0x00` vftable, `+0x08` state u32 (2 while building, **0 = ready**),
   `+0x20` name `oCString {ptr, cap|0x80000000, len}`, `+0x30` name hash (bus
   routing only), `+0x38` modifier id (`-1` = fresh; op 3 match-replaces on it),
   `+0x50` serial u32, **`+0x54` stat CRC key**, `+0x58` counter,
   **`+0x60` embedded `oCEntityValueUnion` carrying the amount**, `+0x80`
   **duration f32** (`<0` = permanent — a negative duration also lands the
   modifier in the store's persistent list; the give-handler uses `5.0` for its
   5 s buff; `DAT_140fcbd90 = 5.0`), `+0x84/+0x88` multipliers (1.0), `+0x8c`
   flag u8 (1), `+0x90` source entity (0 = no lifetime binding; non-zero
   registers an entity-death watch at `entity+0x570`).

   Consumption (`FUN_14074b2f0(store, ev, 0, 0)`): key = `ev+0x54`; the **op and
   modifier type come from the value DEF** looked up in the base hashmap
   `*(store+0x80)` — `def+0x70` = merge op (1..4 per the table above; anything
   else = plain append), `def+0x74` = typed-modifier factory switch (0..6),
   `def+0x68` = max modifier count (0 → unlimited). `mod+0x3c` = remaining
   duration, `mod+0x40` = apply timestamp (game time `*(*(entity+0x30)+0x24)`).
   In co-op non-authority the function *relays* the event to the host over the
   named-event bus instead of applying locally (its own code, free for us).

   `R.stat.modify(name, amount[, duration])` forges the event in scratch memory
   (union built via the engine's own `EntityValueUnion_DefaultCtor` →
   `_Destruct` → `_InitAsType(u,0)` sequence, exactly like the engine's locals)
   and calls `ApplyModifierEvent` directly — no bus, no name hash needed.
   Fail-closed: `enable_writes` + `_va_ok` + `_ev_ctx`-validated store +
   vftable slot-0 plausibility probe. Composes with item/talent modifiers and
   survives recompute, unlike `set`/`stick`. Don't combine with `stick` on the
   same stat.

## Symbols added (all `status: ok` / `va`, pattern-resolved)

Read/write primitives: `EntityValueOverride_Alloc`, `EntityValueEntry_Ctor`,
`EntityValueUnion_DefaultCtor`, `_InitAsType`, `_CopyAssign`, `_Compare`,
`_Destruct`, `Hero_GainExperience`, `XpComponent_SetLevel`, `XpComponent_SetXp`,
`Entity_GetComponentByTester`, `Entity_GetComponentFast`, `XpComponent_vftable`,
`XpComponent_TypeTester`.

Durable-modifier path (2026-07-14): `EntityValueStore_Recompute`,
`EntityValueStore_ApplyModifierEvent`, `EntityValueStore_InitBaseValues`,
`ModifierEvent_Ctor`, `oCGameEventNetworkModifier_vftable`.
