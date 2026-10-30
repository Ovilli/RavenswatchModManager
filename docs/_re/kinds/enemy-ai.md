# Enemy AI

Static RE, 2026-10-29, build b9c3642884a8. Nothing here is proven in game yet.

## Summary

Enemy AI is **data, not code**. There is no behaviour-tree or brain class: an
enemy is an entity whose cooked components form a hierarchical state machine,
the same component vocabulary heroes use for abilities (State, Tester, Timer,
Selector, Value, ValueSelector, …). The native side supplies only generic
building blocks — spatial queries (GPN), target scoring, path-finding,
look-at — and the data wires them together. `rsmm entity-graph` reads all of
it.

## Inheritance chain

```
Character_Common            shared by heroes + NPCs (controller, hit stun, dying, intangible…)
  └ NPC_Common              THE BRAIN: 438 components, 25 groups
      └ Enemy_Model         enemy-only: death rewards/XP, tainted, NGP scaling, reset-to-wandering
          └ <Family>_Model  e.g. Wolves_Model: the attacks (Bite, Double Slash, Giant Leap, Howl, Summon)
              └ <Variant>   e.g. Standard_Wolf_Timber (10 cpnts), Elite_Wolf_Alpha (53): picks WHICH attacks + tunes values
```

A variant is mostly overrides: it chooses attacks by overriding one selector
(below) and retunes `Value` components.

## Top-level behaviours

`NPC_Common\Bhv Default\Behaviour Default State Machine` holds the mutually
exclusive top-level states: **None / Wandering / Fighting / Following / Goto**
(+ Spawning, Dying, Destroyed, Hit Stunned, Staggered, Cinematic from
Character_Common). `Bhv Last Default` remembers the previous one.

Each behaviour runs a **priority Selector** (`oCEntityCpntSelectorSettings`):
an ordered list of `(State, Tester)` entries; the last entry has its bool set
and no tester (the fallback). Reading: first entry whose condition passes is
the active sub-state (inferred from the data shape; the native selector
update is not decompiled yet).

### Wandering (`Bhv Wandering State Selector`)

1. Retreat (go back to the retreat/spawn location, heal to full; teleport if it takes too long)
2. To Fighting (target seen → wait `Target Delay`, look at it, play the notice sound, enter Fighting)
3. Roam (pick a spread position around spawn, `Roam Distance` = 5, cooldown timer)
4. Idle (fallback)

Detection while wandering = two `GpnDetector`s:

| detector | traverser filter | radius |
|---|---|---|
| Target Detector | `Targetable` | 6 default, 16 when alerted (+ collision radius) |
| Alert Detector | `In Combat`, `Concealed` | 9 |

Delay before switching to Fighting: 0.5 s default, 0.25 s alerted.
"Alerted" comes from nearby allies: `NPC_DEATH_ALERT` (an ally dying) and
anything already in combat inside the alert radius — this is how a whole camp
aggroes together.

### Fighting (`Bhv Fighting State Selector`)

NPC_Common default order:
1. Leashed (too far from home → back to Wandering with the retreat flag; max leash 40)
2. Seek Target Idle
3. Seek Target Move
4. Target Lost (fallback; after `Exit Delay` = 3 s it leaves combat)

A variant inserts its attacks. `Standard_Wolf_Timber`:

```
Leashed → Move UTurn → Attack Bite → Seek Target Move → Seek Target Idle → Target Lost
```

`Elite_Wolf_Alpha`:

```
Leashed → Move UTurn → Attack Howl → Attack Double Slash → Attack Giant Leap → Seek Move → Seek Idle → Target Lost
```

So **attack priority = list order**, and each attack is gated by its own
`Attack X Condition` tester (cooldown timer, range, line of sight…; the tester
expression is an undecoded `test` obj). There is also a shared
`Fighting All Attack Cooldown` (re-armed by `Event On Attack Activated`) and a
`Fighting Start Attack Cooldown` on combat entry.

Fighting target: `Fighting Target Computer` (`GpnTargetComputer`) over a
`Targetable` traverser, radius 30 (shrinks over time after the target is
lost), height window from `Fighting Target Min/Max Height`. A separate
detector watches for heroes at death's door.

### Seek Target (movement in combat)

`Seek Target Pos Computer` (`AttackPosComputer`) keeps the enemy between
`Min`/`Best`/`Max` distance of its target (fighting: 1 / 2 / 3.5; Following
has its own trio), re-pathing every `Path Update Period` = 1 s through
`Move Pathfinding Profile`.

### Attack anatomy (Wolves_Model `Attack Bite`)

```
State Attack Bite            while active: keeps NPC_Common "State Fighting Attack" on,
  │                          runs a sub-state machine (In → Success Loop), arms Attack Bite Cooldown
  ├ Attack Bite Gpn Target Best One Computer  (GpnTargetComputer, its own traverser)
  ├ Event Attack Bite Active  → Gpn Attack Bite Target (GpnTargetAttack) → Attack Bite Damage
  │                           → NPC_Common "Event On Attack Activated" (shared cooldown)
  └ Event Attack Bite Active Impact → FX, sound, Success Loop, Rooted debuff on the target
```

The hit itself is a `GpnTargetAttack` (single target) / `ZoneAttack` /
`ProjectileAttack`, each carrying an `oCDtEntityCpntDamage`.

## Native: GPN (Global Positioning Node)

Every gameplay entity has an `oCEntityCpntGpn` ("Position update") that
registers it in a spatial index. Queries are composed from:

- **Traversers** — Around Position, Closest, In Box, In Cone, In Line; carry
  flag filters (`Targetable`, `In Combat`, `Concealed`, `Prop`, …) and height.
- **Filters / testers** — LOS, physics LOS, HitPoint, Height, Flag/FlagMask,
  Custom Flag, Network, Path Find, Self, Combiner, Preset.
- **Score computers** — Distance, Best Facing, HitPoint, Entity Get Value,
  Entity Collector.

### `oCEntityCpntGpnTargetComputer` ("Targets update")

Registered by `FUN_1407ba740` (job priority 5000), per-frame job
`FUN_1407bc390` → per component `FUN_1407bc410(cpnt, retarget)`.

- `retarget` = NOT the bool value at cpnt+0x3c0/+0x3c8 (a "lock current
  target" switch). Locked: only drop dead targets (`FUN_1407bd8f0`, gated by
  the bool at +0x3d0). Otherwise full re-target, `FUN_1407bd2c0`:
  1. Get candidates from the traverser (cpnt+0x88, `FUN_1407b7780`).
  2. Each candidate starts at score 0 — or at the value at +0x3b0 if it was
     selected last time (**stickiness bonus**, so targets don't flicker).
  3. For each score computer in the list at +0x380 (count +0x388) whose
     enable value is true: `score += computer->Score(entity) [vtbl+0x28] ×
     weight [+0x38]`.
  4. Sort descending; the top N (value at +0x3a0, 0 = all) are marked
     selected (+0xc of the entry). Subscribes to each target's destruction.
- Then `FUN_1407bdb20` resolves the "main" target by mode (settings
  +0xd90): **0 = best-scored, 1 = centroid of all selected, 2 = index from a
  value (u32 % count)**, and publishes position (+0xe0), direction
  (+0x100/+0x120), id (+0x140), horizontal distance (+0x160) and angle
  (+0x180) as entity values the data reads (Seek Target selectors, look-at).
- Per-slot outputs for the first N targets go to arrays at +0x258..+0x298;
  "has target" states at +0x368 / +0x370 are switched on/off — this is how
  `State Fighting Target Computer Has Target` / `State Fighting Attack` light
  up.

There is no threat/aggro table. "Aggro" is the score sum; taunt
(`Debuff Taunted`, `ON_TAUNTED` event) is a state on the enemy, which
presumably feeds a score computer or locks the target (not traced).

## What this means for modding

- Retuning AI (detection/leash/attack distances, delays, cooldowns) = editing
  `Value` components on an enemy family or variant — the existing `entity`
  kind path, no new RE needed.
- New attack order / which attacks a variant uses = override `Bhv Fighting
  State Selector` on the variant (reorder entries, add a family attack).
- A brand-new attack = copy an attack group (state + sub-machine + target
  computer + attack + damage + cooldown) — the same clone pattern as hero
  abilities, with the same activation caveats (spawned-entity-activation).
- Live control (force a target, freeze AI) would need `R.*` work on the
  target computer's lock flag (+0x3c0) — unbuilt, unproven.

## Open

- Native `oCEntityCpntSelector` update — confirm first-true-wins and how
  often it re-evaluates.
- Tester `test` obj encoding (the actual attack conditions).
- `oCDtEntityCpntEnemyController` (refs character controller, fighting
  target computer, GPN detection, in-combat tester, boss/elite flags) — likely
  publishes combat state for music / `EnemyAround_*` counts; unread.
- Which score computers the stock `Fighting Target Computer` uses, and their
  weights.
