---
title: Combat & damage
description: The hit pipeline — why healing the hero is easy, damaging an enemy is not, and the ride-an-existing-attack mod path.
---

:::note
Status: RE complete, 2026-06-14. Addresses verified live against the shipped
`Ravenswatch.exe` via Ghidra MCP (image base `0x140000000`). No runtime code
shipped — this documents the recipe so a future implementation is grounded.
:::

## TL;DR

`R.combat` heals/damages the **hero** via `Entity_ModifyHealth(hero, delta, tags)`.
That routine is **hero-only** — it dereferences the HUD HP mirror at `hero+0x1d80`
unconditionally, which enemies do not have, so calling it on an enemy
access-violates.

To damage an **enemy** the engine builds an `oCEntityHitData` and hands it to
`Entity_DispatchHit(target, hit)`. There is **no low-arity "damage entity by N"
call** and **no standalone `oCEntityHitData` constructor** — the struct is built
inline inside the attack resolver. The viable mod path is to **hook the resolver
and amplify/redirect** an attack the hero already makes.

## The two appliers

| Function | Symbol | Role |
|---|---|---|
| `FUN_1406e2d20` | `Entity_DispatchHit` | LOCAL apply: runs the target's hit handlers. `(oCEntity* target, oCEntityHitData* hit)`. |
| `FUN_140726610` | `NamedEvent_EmitNetworkDamageFromHit` | wraps the hit in `oCGameNamedEventNetworkDamage`, sends over the network; calls `Entity_DispatchHit` for self/non-networked targets. |

Both consume a fully-built `oCEntityHitData`.

## oCEntityHitData layout (~0xb0 bytes)

vftable `0x140f0e4b8`.

| Offset | Field |
|---|---|
| `+0x00` | vftable |
| `+0x08` | hit handle/id (from `FUN_140214f30`) |
| `+0x10` | source/instigator entity\* (refcounted) |
| `+0x18..0x90` | float/vector block: positions, normals, direction (defaults from constants `0x140fc6c10`, `0x140fc6c50`, `0x140fc6e70`, `0x140fc7240`) |
| `+0x88` | u16 flags |
| `+0xa0` | target entity\* (refcounted) |

The damage **amount** is not a plain float here — it lives in a separate
"hit-value" object (`*(hitval+0x8)` = damage), pointed to from the hit-data.

## The producer: `Entity_ResolveAttackHits` (`FUN_1403dc780`)

```c
float resolve(void* attacker, uint hitDefIndex, TargetList* targets,
              float damageMul, float baseDamage)
```

- `attacker` — hit-def array @ `+0xd8`, entity @ `+0x8`.
- `hitDefIndex` — index into the attacker's hit-def array;
  `attacker[+0xd8 + i*8]` → `vtable[+0x20]()` → the hit-value object.
- `targets` — `{ u32 count @+0x0, oCEntity** @+0x8 }`.
- `damageMul × (baseDamage or the hit-def's value)` → written to `hitval+0x8`.

Per target it allocs a hit handle, stack-builds the `oCEntityHitData` (fully
inlined — no constructor `CALL`), then calls `Entity_DispatchHit(target, hitData)`.

## Why synthesis is impractical

A standalone "deal N damage to enemy E from hero H" would have to fabricate: a
hit-value object with the right vtable, a valid hit handle (alloc + release
lifecycle), the source net-id (host-authoritative replication), the
position/normal block, and correct refcounts on both entity pointers. Any error
corrupts the hit pipeline or desyncs multiplayer.

## Recommended mod path

**Ride an existing attack.** Hook `Entity_ResolveAttackHits` (`FUN_1403dc780`)
read/modify and either scale the hit-value damage (`*(hitval+0x8)`) for a "+X%"
effect, or swap/extend the target list to redirect/widen a hit. This reuses a
real, fully-formed hit the engine already built — no fabrication, netcode-correct.
Engine-mutating, so it runs on the game main thread (see
[loader thread model](/reverse-engineering/mod-hooks/)) behind an env gate until
verified. Not yet implemented.

## See also

- [Entity values](/reverse-engineering/entity-values/) — where combat modifiers live.
- [Event systems](/reverse-engineering/event-systems/) — `NETWORK_DAMAGE` payload decode.
- [Multiplayer](/reverse-engineering/multiplayer/) — why the net-id matters.
