# Projectiles / line attacks — `oCEntityCpntGpnProjectileAttack`

> Status: hit-volume width RE'd + shipped 2026-08-10 (`R.projectile.scale_width`,
> `mods/big-projectiles`). Static only — **no in-game playtest yet**. The visual
> side is unsolved.

## There is no "projectile" class

Worth stating first, because it is the assumption everyone arrives with.
Searching RTTI for `Projectile` returns exactly two names:

```
oCEntityCpntGpnProjectileAttack
oCEntityCpntGpnProjectileAttackSettings
```

Both are the same component. It is not a flying object — it is a **line
attack**: it sweeps a volume from a start point to an end point and damages
every hittable Gpn inside it. The engine's own profiler markers say so:

```
oCEntityCpntGpnProjectileAttack - Damage all hittable Gpn in line MT
oCEntityCpntGpnProjectileAttack - Damage all hittable Gpn in line ST
CpntGpnProjectileAttack::_DamageAllHittableGpnInLine - Collide Gpn
CpntGpnProjectileAttack::_DamageAllHittableGpnInLineST - Collide Physic Volume
```

So "make projectiles bigger" is not one question. The hit volume and the
artwork are separate systems, and only the first is solved here.

## Component layout (from the begin call + the debug draw)

`ProjectileAttack_BeginAttack` = **vftable slot 28**, `FUN_14083e7d0` in the
2026-08 build. Component lifecycle slot 28 is the "begin" half of the
28/29 pair (29 is teardown) — the same convention documented in
`tools/mine_vtable_interfaces.py`.

```c
// FUN_14083e7d0(cpnt)
puVar5 = (**(code **)(**(longlong **)(cpnt + 8) + 0x48))();  // owner position
*(u32*)(cpnt + 0xd0) = puVar5[0];   // start x
*(u32*)(cpnt + 0xd4) = puVar5[1];   // start y
*(u32*)(cpnt + 0xd8) = puVar5[2];   // start z
*(u32*)(cpnt + 0xdc) = puVar5[0];   // end x   — identical at t=0
*(u32*)(cpnt + 0xe0) = puVar5[1];   // end y
*(u32*)(cpnt + 0xe4) = puVar5[2];   // end z
...
*(u32*)(cpnt + 0xe8) = uVar6;       // WIDTH
*(u8 *)(cpnt + 0xc8) = *(u8*)(settings + 0x180);
```

| Offset | Field |
|---|---|
| `cpnt+0x08` | owner entity back-pointer (every component has this) |
| `cpnt+0x10` | settings pointer |
| `cpnt+0x68` | bound width value (from `settings+0x100`, bound at attach) |
| `cpnt+0x70` | curve/bound form of the same, when non-null |
| `cpnt+0xc8` | bool, copied from `settings+0x180` |
| `cpnt+0xd0..0xd8` | start xyz |
| `cpnt+0xdc..0xe4` | end xyz (swept forward as the attack travels) |
| **`cpnt+0xe8`** | **width — FULL thickness** |

### Where the width comes from

```c
if (*(longlong *)(cpnt + 0x70) == 0) {
    uVar4  = *(u64*)(*(longlong*)(cpnt + 0x68) + 0x68);
    puVar5 = (u32*)(*(longlong*)(cpnt + 0x68) + 0x70);
    if (uVar4 != 4) puVar5 = (u32*)(uVar4 & 0xfffffffffffffffe);
    uVar6 = *puVar5;
} else {
    uVar6 = *(u32*)(*(longlong*)(cpnt + 0x70) + 8);
}
```

The `+0x68` branch is the engine's inline-vs-pointer value variant: tag at
`val+0x68`, inline payload at `val+0x70`, and any tag other than `4` means the
payload is a **pointer** at `tag & ~1`. The `+0x70` branch is the curve/bound
form. Either way the result is one `f32`.

Both are bound at attach — slot 5 (`FUN_14083e4a0`) does
`FUN_140274ba0(cpnt+0x68, entity, settings+0x100)`.

### Why `+0xe8` is known to be the width, not a guess

The component's own debug draw, **slot 20** (`FUN_14083eb30`), renders the
volume:

```c
fVar11 = *(float *)(cpnt + 0xe8);
...
fVar11 = fVar11 * 0.5;              // half-extent
... DrawLine(start ± half, end ± half) ...
```

It halves `+0xe8` and offsets the corners either side of the `+0xd0` → `+0xdc`
line. That is a full width, and scaling it widens the volume symmetrically.
(The `fVar11 <= 0.0` branch degenerates to drawing the bare line — a
non-positive width means nothing can be hit, which is why the SDK clamps.)

## Other slots identified in passing

| Slot | Address | What |
|---|---|---|
| 5 | `FUN_14083e4a0` | attach — binds settings `0x100/0x188/0x2a8/0x3a8` into the component |
| 6 | `FUN_14083e670` | release bound values, null the cached pointers |
| 7 | `FUN_14083e700` | resolve the Gpn scene context, take a handle (`cpnt+0xb0/0xb8`) |
| 8 | `FUN_14083e790` | release that handle |
| 15 | `FUN_14083f130` | cast-by-type-hash (`0xff0dbe9 → this+0x1c0`, `0xff0dbec → this+0x1a0`) |
| 20 | `FUN_14083eb30` | debug draw of the swept volume |
| 28 | `FUN_14083e7d0` | **begin attack** — seeds the volume (above) |
| 29 | `FUN_14083e8d0` | teardown — unsubscribes three event channels, releases bound values |

Slot 15 is the same cast-by-type-hash convention documented for Controller
slot 11; the slot number differs per family, the shape does not.

## The settings class is minable but not mined

`oCEntityCpntGpnProjectileAttackSettings`'s deserializer (`FUN_14083ddb0`) uses
the **same versioned grammar** as every cooked class already handled: a version
record via `FUN_1404fce50(reader, …, 0x12241ff6)` with the version at `+4`, and
each field gated on a minimum version. Field offsets read: `0xf8, 0x100, 0x180,
0x188, 0x2a8, 0x328, 0x368, 0x3a8, 0x4c8, 0x508, 0x548, 0x560`. Most are read
through reader slot `0xa0` (nested object) rather than as scalars.

So a `projectile` content kind is *possible* with existing tooling. Nobody has
mined the field meanings, and this doc does not guess at them.

## What is NOT solved: the visual

Scaling `+0xe8` moves the hitbox. Nothing here touches the mesh, particles or
trail, so a widened attack looks exactly like a vanilla one.

Two dead ends already checked, recorded so they are not re-walked:

* **No size entity-value.** The ~40 registered stat keys (see `stats.md`) have
  no size/area/scale/radius member. Scanning the binary's whole string pool for
  size-ish names turns up render/UI/network terms (`Render scale`, `Border
  Width`, `Game Session Size`, …) and nothing gameplay-dimensional. There is no
  `R.stat` lever for this.
* **No `PointOfInterest`/projectile-size RTTI.** The only size-adjacent
  gameplay classes are particle/trail emitters, which are VFX, not the attack.

The visual would need the projectile entity's transform scale, which means
finding the spawn path for the entity carrying the art — a different problem
from this component.

## Multiplayer

Host-authoritative (see `multiplayer-netcode` memory). A client that widens its
own volumes disagrees with the host about what was hit: shots appear to connect
and then do not register. `mods/big-projectiles` is `local-only` for this
reason.
