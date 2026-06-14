# Enemy damage — the hit pipeline and why there is no cheap primitive

> Status: RE complete, 2026-06-14. Addresses verified live against the shipped
> Ravenswatch.exe via the Ghidra MCP bridge (image base 0x140000000). No runtime
> code shipped — this documents the construction recipe and the recommended mod
> approach so a future implementation is grounded, not speculative.

## TL;DR

`R.combat` heals/damages the **hero** via `Entity_ModifyHealth(hero, delta, tags)`.
That routine is **hero-only** — it dereferences the HUD HP mirror at `hero+0x1d80`
unconditionally, which enemies do not have, so calling it on an enemy
access-violates (see `Entity_ModifyHealth` in `data/symbols.json`).

To damage an **enemy** the engine uses a completely different path: build an
`oCEntityHitData` and hand it to `Entity_DispatchHit(target, hit)`. There is
**no low-arity "damage entity by N" call** and **no standalone `oCEntityHitData`
constructor** — the struct is built inline inside the attack resolver and needs
a real attacker hit-definition. Synthesizing a hit from nothing is impractical;
the viable mod path is to **hook the resolver and amplify/redirect** an attack
the hero already makes.

## The two appliers

| Function | Symbol | Role |
| --- | --- | --- |
| `FUN_1406e2d20` | `Entity_DispatchHit` | LOCAL apply: runs the target's hit handlers (or queues the hit). `(oCEntity* target, oCEntityHitData* hit)`. |
| `FUN_140726610` | `NamedEvent_EmitNetworkDamageFromHit` | Wraps the hit in `oCGameNamedEventNetworkDamage` and sends over the network. Calls `Entity_DispatchHit` for self/non-networked targets. |

Both consume a fully-built `oCEntityHitData`.

## oCEntityHitData layout (~0xb0 bytes)

vftable = `oCEntityHitData_vftable` @ `0x140f0e4b8`.

| Offset | Field |
| --- | --- |
| +0x00 | vftable |
| +0x08 | hit handle/id (from `FUN_140214f30`, released by `NamedEvent_Delete` / `FUN_140126da0`) |
| +0x10 | source/instigator entity\* (accessed through its vtable → must be a live oCEntity; refcounted) |
| +0x18..0x90 | float/vector block: positions, normals, direction. Defaults copied from constants `0x140fc6c10`, `0x140fc6c50`, `0x140fc6e70`, `0x140fc7240` |
| +0x88 | u16 flags |
| +0x90 | ptr |
| +0xa0 | target entity\* (vtable-accessed, refcounted) |

The damage **amount** is not a plain float in this struct — it lives in a
separate "hit-value" object (`*(hitval+0x8)` = damage), and a pointer to that
object is stored into the hit-data during construction.

## The producer: `Entity_ResolveAttackHits` (`FUN_1403dc780`)

`float resolve(void* attacker, uint hitDefIndex, TargetList* targets, float damageMul, float baseDamage)`

- `attacker` — attacker context; hit-def array @ `+0xd8`, entity @ `+0x8`.
- `hitDefIndex` — index into the attacker's hit-def array. `attacker[+0xd8 + i*8]`
  → `vtable[+0x20]()` → the **hit-value object** (`*(+0x8)` = damage).
- `targets` — `{ u32 count @+0x0, oCEntity** @+0x8 }`.
- `damageMul` × (`baseDamage` or the hit-def's own value) → written back to
  `hitval+0x8`.

Per target it: allocs a hit handle, stack-builds the `oCEntityHitData` (vftable,
the 4 constant template vectors, the hit-value pointer, the attacker, the target
position from `target->vtable[+0x48]()`, the source net-id via
`Entity_GetNetComponent`), then calls `Entity_DispatchHit(target, hitData)`.

Construction is **fully inlined here** — confirmed by disassembly, no `CALL` to a
constructor.

## Why synthesis is impractical

A standalone "deal N damage to enemy E from hero H" would have to fabricate:

1. a hit-value object with the right vtable (for `*(+0x8)` damage),
2. a valid hit handle (allocator + release lifecycle),
3. the source net-id (host-authoritative replication; see `Entity_GetNetComponent`),
4. the position/normal block (mostly the constant template, but target-relative
   fields read through the target vtable),
5. correct refcount handling on both entity pointers.

Getting any of these wrong corrupts the hit pipeline or desyncs multiplayer.

## Recommended mod path (future work)

**Ride an existing attack.** Hook `Entity_ResolveAttackHits` (`FUN_1403dc780`)
read/modify and:

- scale the hit-value damage (`*(hitval+0x8)`) for a "+X% damage" / "deal N
  bonus" effect, or
- swap/extend the target list to redirect or widen a hit.

This reuses a real, fully-formed hit the engine already built, so it needs no
fabrication and stays netcode-correct. It is engine-mutating, so it must run on
the game main thread (see `[[loader-thread-model]]`) and ship behind the
hero-capture-style env gate until verified in-game. Not yet implemented.
