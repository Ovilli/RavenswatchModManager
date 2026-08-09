---
title: Bosses
description: A boss is a flag-tagged enemy plus a BossTimer controller component — the settings layout, the named-event encounter gates, and the reward hookup.
---

:::note
Status: Tier-1 RE backing `src/rsmm/sdk/kinds/bosses.py`, from live Ghidra MCP +
headless decompilation. Items marked *unconfirmed* are inferred, not read from the
binary.
:::

Per-kind companion to [Mod hooks](/reverse-engineering/mod-hooks/) ("Enemies &
bosses", "level-load pipeline"). Scope: one custom boss encounter — a tagged enemy
with an `oCDtBossTimerUiControllerEntityCpnt` component, wired into the existing
named-event spawn fabric, guaranteed to drop a reward.

## Summary — bosses are tagged enemies with a controller component

1. `oCDtBossTimerUiControllerEntityCpnt` is the runtime component driving the
   boss-fight UI / HP bar. It is **not** in `class_registry.json` — it's a
   component, not a UID-keyed serializable record (same shape as
   `oCDtEntityCpntMagicalObject`).
2. `oCDtBossTimerUiControllerEntityCpntSettings` is the *authored* settings
   container — what asset bytes describe. Its four embedded `oCEntityCpntPicker`
   slots are the fields a level designer fills in.
3. The encounter is gated by `oCGameNamedEvent`s named `BOSS_FIGHTING_START` /
   `BOSS_ACTIVATED` / `BOSS_FIGHTING_STOP` / `BOSS_DEFEATED`. Each string is
   CRC32-keyed at static init into a `_DAT_*` slot; `FUN_14027fde0` is the master
   listener-binder wiring those keys to per-listener thunks.
4. Bosses are otherwise vanilla `oCDtEnemyDefinition` records (UID `0x176debb7`,
   size `0x350`, library `0x1414118c0`) — "is a boss" is a **bit in the enemy's
   `oCCustomFlagList`**, not a separate class. Flag bits are unnamed in the binary
   (`"Flag 0"`.."Flag 63"` are the only labels).

## The chain

```
oCDtEnemyDefinition                       data class (UID 0x176debb7)
    +-- oCCustomFlagList                  tag list — one bit = "is_boss"
    |
    +-- oCDtBossTimerUiControllerEntityCpntSettings   per-encounter cfg
            +-- picker @ +0xf8   target enemy / arena anchor
            +-- picker @ +0x138  intro / cinematic ref
            +-- picker @ +0x250  music cue / FMOD event
            +-- picker @ +0x310  post-kill reward (oCDtRewardDefinition)
            |
            v (resolved at level-load)
        oCDtBossTimerUiControllerEntityCpnt   runtime component (UI + HP bar + timer)
            +-- oCEntitySpawner    embedded at +0x68
            +-- bool signals       at +0x18 (is_active) / +0x38 (ever_activated)
```

Named-event keys: `BOSS_FIGHTING_START` → `_DAT_1412c0430`, `BOSS_ACTIVATED` →
`_DAT_1412bfcb8`, `BOSS_DEFEATED` (string `0x140ef1788`), `BOSS_FIGHTING_STOP`
(string `0x140ef1798`).

:::caution[Rebase note]
The `0x140368xxx` / `0x14147ff74` addresses below are from the pre-rebase corpus
and are stale in the current binary. The core claim was re-verified: the settings
vftable is now `0x140f2da98`, deserialize is slot 3 = `FUN_140374250`, and it reads
exactly `+0xf8`, `+0x138`, `+0x178`, `+0x250` unconditionally plus `+0x290` and
`+0x310` gated on class-version tag `0x17e9a0ae >= 1`. **The offset tables stand;
re-derive the addresses before using them.**
:::

## Runtime component layout

From the ctor + dtor. Mirrors `oCDtEntityCpntHeroSpawner` (same spawner-shaped
pattern).

| Offset | Field |
|---|---|
| `+0x00` | vftable (`oIEntityCpnt` first, then specialized) |
| `+0x08..+0x10` | parent / scene-graph backrefs (0 at ctor) |
| `+0x18` | `EntityCpntValueSignal<bool>` — **is_active** (boss enters fight) |
| `+0x20..+0x30` | signal body (listener list head/tail) |
| `+0x38` | `EntityCpntValueSignal<bool>` — **ever_activated** (first encounter) |
| `+0x40..+0x50` | signal body |
| `+0x64` | low-nibble-masked status byte (`& 0xf0` cleared by ctor) |
| `+0x68` | embedded `oCEntitySpawner` — **what actually creates the boss entity** |
| `+0x70..+0x88` | spawner body; `0xffffffffffffffff` is the unresolved-prefab sentinel |
| `+0x90..+0xb8` | spawner state (parent entity backref, prefab cache) |
| `+0xc0..+0xe8` | controller state — boss-fight HUD / HP bar context *(unconfirmed)* |
| `+0xd8`, `+0xe8` | heap signal-listener pointers; released by the dtor when non-null |
| `+0xe4`, `+0xf4` | ints — phase index / phase count *(unconfirmed; inferred from the dtor's matched pair of refcounted listeners)* |

## Settings layout

The settings struct is the **authoring** record. Each picker is an
`oCEntityCpntPicker` — the same "pick one named resource" primitive items use.

| Offset | Field | Notes |
|---|---|---|
| `+0x00` / `+0x08` | primary / secondary vftable | multiple-inheritance ABI |
| `+0xf8` | **picker 1** | target entity — anchor to attach the boss prefab to |
| `+0x100` / `+0x108` | picker 1 name ptr / hash | `0x80000000` = unresolved |
| `+0x118` | picker 1 resolved `oCMetaClass*` | fixed up by the resolve pass |
| `+0x138` | **picker 2** | intro cinematic / intro entity *(unconfirmed)* |
| `+0x158` | picker 2 resolved meta | |
| `+0x178` | scalar/array slot (no picker vftable) | likely per-phase settings or HP cutoffs *(unconfirmed)* |
| `+0x1b0` | array-tail pointer | resolves to `+0x278` |
| `+0x250` | **picker 3** | music cue, likely over the FMOD event library *(unconfirmed)* |
| `+0x290` | scalar/array slot | possibly the `oCCustomFlagList` of fight tags |
| `+0x2c8` | picker target ptr | resolved-meta sentinel |
| `+0x310` | **picker 4** | reward — the guaranteed-drop `oCDtRewardDefinition` |
| `+0x330` | picker 4 resolved meta | |

Deserialize calls the sub-object reader six times, one per field. The sixth
(`+0x310`) is **gated** on the cooked-asset version-tag test for `0x17e9a0ae`, so
the reward picker is a newer schema addition and may be absent on older records.
**A mod must emit version tag `0x17e9a0ae` for the reward picker to deserialize.**

## How the boss actually appears

There is **no direct factory call** for bosses in the level-load resource loader.
Instead:

1. Stage 3 (*Enemies settings loading*) walks
   `oCTLibrary<oCDtEnemyDefinition>` and filters via
   `EnemyDefInternal::SearchFilter` + `oCCustomFlagFilter`. Survivors join the
   camp pool.
2. Stage 12 (*Generate enemy camps*) fires a named event; camp-spawner components
   instantiate enemies. A boss enemy lands in the pool with the right tag, and the
   camp's `oCDtEnemyFlagListEntitySelectorToSpawnEntityCpntSettings` picks it
   because its `oCCustomFlagList` matches.
3. When the player approaches the arena, the attached controller wakes — its
   `is_active` signal flips, the engine raises `BOSS_FIGHTING_START`, and the
   listener-binder's `MapSceneContext` closure runs.
4. On death `BOSS_DEFEATED` fires and the reward picker at `+0x310` dispatches
   through the reward-selector chain
   ([Rewards](/reverse-engineering/rewards/)).

So the "spawn the boss" hook is not a call — it's the combination of a tagged
enemy definition clearing the stage-3 filter, a controller component attached to
that enemy or its arena anchor, and the existing camp machinery doing the creation
at stage 12. **Modders don't fire any new event**: with the boss tag and the
component, the engine handles the rest.

## What the "boss flag" is, concretely

The engine walks every enemy in the library and tests each against
`oCCustomFlagFilter`; the camp's selector carries its own `oCCustomFlagList`. A
boss is an enemy whose bitfield has the bit the boss-arena camp filter demands.
The exact bit index isn't string-labelled, so in practice: read a vanilla boss's
asset `oCCustomFlagList` bitfield, and copy it onto the custom enemy.

## Insertion recipe

1. **Enemy definition** — clone a vanilla boss `oCDtEnemyDefinition`; set the
   resource path/name, HP/damage scalars, and the `oCCustomFlagList` bits to
   include the boss flag the stage-3 camp filter looks for.
2. **BossTimer settings** — picker `+0xf8` → arena anchor entity name, `+0x138` →
   intro entity, `+0x250` → FMOD music cue, `+0x310` → reward definition, with
   version tag `0x17e9a0ae` in the cooked stream.
3. **Component attach** — at level load a controller must sit on either the boss
   enemy or its arena anchor; it reads its settings through the normal
   entity-component plumbing.
4. **Arena** — the map's camp must include a spawn tag matching the new enemy's
   flag list, or route through a per-map selector patch.

Unknown fields fall back to **clone-from-base**: copy a vanilla boss's bytes
verbatim and patch only the offsets above, carrying a `synthesized: {offset: value}`
map and a `cloned_from` field so the apply layer can audit which bytes are real
schema and which are inherited.

## Harder bosses vs "all moves at once"

- **Harder bosses (HP / damage scaling)** — reachable today. A boss is an enemy
  entity: scale it via the difficulty levers (`Game Difficulty` `0x18700873`,
  `Camp Difficulty Modifier` `0x187aaecf`; see
  [Game modifiers](/reverse-engineering/game-modifiers/)) or per-entity stat
  overrides. A "slider to 1000%" is thin UI over a value multiplier — no RE wall.
- **"All moves at once"** — hard and unmapped. Ability sequencing lives in the
  boss **behaviour tree** plus per-ability controllers (cooldown / windup / phase
  gates), not a scalar. True simultaneity needs BHV-asset surgery or a per-tick
  ability-force-trigger hook, which is engine-AI and MP-determinism sensitive. The
  closest tractable approximation is driving ability **cooldowns** toward zero, if
  they surface as entity-value keys.
