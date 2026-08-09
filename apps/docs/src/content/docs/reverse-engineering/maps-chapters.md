---
title: Maps & chapters
description: How a run is assembled from a chapter sequence, which layer is editable today, and why a brand-new playable level is out of reach.
---

:::note
Status: chapter re-sequencing **proven in-game** 2026-07-11. A net-new level is
blocked on level-asset authoring, not on RE.
:::

## Three layers

| Layer | Class / asset | Codec |
|-------|---------------|-------|
| **Map** | `oCDtMapDefinition`, `*.mapdef.ot` (loader `MapDef_RegisterAssetLoader` = `FUN_140322a50`) | `cooked_schemas.definitions` `mapdef.json` — `level_ref`, `field_a`, `tribe_ref` + `_tail_hex` |
| **Chapter** | `GameModeDefInternal::Chapter` | inside the game-mode def tail |
| **Sequence** | `GameModeDefaultDefinition`, `*.gamemodedefaultdef.ot` (library `Library_GameModeDefaultDefinition`) | `gamemodedefaultdef.json` — `field_a` + `_tail_hex` |

A run is a `GameModeDefaultDefinition`: an ordered list of chapters, each
referencing the map(s) it can roll. `GAME_END_NEXT_CHAPTER` advances it. The
"One chapter" modifier truncates the sequence to one — see
[Game modifiers](/reverse-engineering/game-modifiers/). "Current chapter" and
"Current map id" are entity-value keys
([Entity values](/reverse-engineering/entity-values/)).

## Sequence layout

The `GameModeDefaultDefinition` tail is a plain `u32 count` followed by `count`
× `u32` chapter index (vanilla `[0,1,2,3]`).

Deserializer-verified: `GameModeDefaultDefinition::Deserialize` reads the list via
`Serializer_ReadPolyPtrVector` into the ordered vector at `def+0x290`, and each
`GameModeDefault` entry is a resource-ref to its chapter content at `entry+0x8`.
So the u32s are sub-object ids into the file's section directory, and **the vector
order IS the run order as stored**.

## SDK kind (shipped)

```python
m.register("game_mode", id="ReverseRun", chapters=[3, 2, 1, 0])  # reorder
# [0,0,0] repeats biome 0; [3] is a one-chapter run.
```

`game_mode` (`src/rsmm/sdk/kinds/game_modes.py`, engine `game_mode_cook.py`),
confidence `experimental`. Indices must reference existing chapters (`0..3`).
Tests: `tests/test_game_mode_cook.py`.

**Proven route is override-in-place**: overriding the retail `All_Chapters` def at
its own cooked path with `chapters=[2, 3]` starts the run directly in the third
chapter — the engine honours the rewritten order, and skipping indices 0/1 hits no
first-run/tutorial coupling (`mods/SeedRunsChapter3`). A net-new *selectable* mode
id is still unproven, as are repeat orders like `[0,0,0]`.

A re-sequenced start is a *fresh* run — no items or talents from the skipped
chapters. Grant a loadout at run start with `R.give` if the mod wants one.

## Blackboard consumers

`FUN_1401da350` is the game-context **blackboard registrar**: it declares every
runtime cvar with a hashed id — `"Current chapter"` (`0x181d17fd`),
`"Current map id"` (`0x193495b8`), `"Random seed"` (`0x17a117c6`),
`"Reroll count"` (`0x1a922cd6`), the four biome map ids, and all
`GameModifier : …` flags.

Run-setup `FUN_1401eca80` (called from `FUN_14028e5f0` at "DayNightCycle
InitCycle") **reads** those modifier hashes via `FUN_1401c9600(ctx, hash)`, making
it the game-modifier consumer as well. The run reads `"Current chapter"` to index
the ordered vector at `def+0x290`.

## What each goal needs

- **Re-sequenced maps** — shipped (above). Determinism caveat: map selection is
  part of the seeded run state, so randomization must be *data-level* (edit the
  pool), never a per-peer runtime choice, or multiplayer desyncs — see
  [Multiplayer](/reverse-engineering/multiplayer/).
- **Brand-new map** — hard. A `mapdef` clone is cheap, but `level_ref` points at a
  cooked LEVEL (geometry, spawn volumes, nav); authoring one is far beyond a def
  edit. The realistic near-term "new map" is a **remix**: a new mapdef reusing an
  existing `level_ref` with a different tribe/reward profile.

## Open

1. Prove or rule out a net-new selectable game-mode id; test repeat orders.
2. Mapdef remix kind (clone + repoint `tribe_ref`).
3. New levels remain out of scope for def cloning.
