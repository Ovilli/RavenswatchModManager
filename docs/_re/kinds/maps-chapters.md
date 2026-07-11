# Maps, chapters & the game-mode sequence (#9 / #10)

Heredos wishlist #9 (new map) and #10 (random / re-sequenced maps). Three layers:

| Layer | Class / asset | Codec |
|-------|---------------|-------|
| **Map** | `oCDtMapDefinition`, `*.mapdef.ot` (loader `MapDef_RegisterAssetLoader` = `FUN_140322a50`) | `cooked_schemas.definitions` `mapdef.json` — `level_ref`, `field_a`, `tribe_ref` + `_tail_hex` |
| **Chapter** | `GameModeDefInternal::Chapter` | inside the game-mode def tail |
| **Sequence** | `GameModeDefaultDefinition`, `*.gamemodedefaultdef.ot` (library `Library_GameModeDefaultDefinition`) | `gamemodedefaultdef.json` — `field_a` + `_tail_hex` |

A run is a `GameModeDefaultDefinition` = an ordered list of chapters; each chapter references the
map(s) it can roll. `GAME_END_NEXT_CHAPTER` advances; the "One chapter" GameModifier truncates the
sequence to one (see [[game-modifiers-re]] / game-modifiers.md). "Current chapter" /
"Current map id" are entity-value keys (entity-values.md).

## What each wishlist item needs

- **#10 random / re-sequenced maps** — MOST TRACTABLE. The chapter→map ordering lives in the
  `GameModeDefaultDefinition` `_tail_hex` (a chapter list, each with map refs). Typing that tail in
  the codec exposes the sequence to edit: reorder chapters, add a chapter, or widen a chapter's map
  pool so the existing maps roll in a new order. No new engine code — it's an additive/edited
  `.gamemodedefaultdef.ot`, same apply path as other defs. **Determinism caveat:** map selection is
  part of the seeded run state, so any randomization must be data-level (edit the pool), not a
  per-peer runtime choice, or multiplayer desyncs ([[multiplayer-netcode]]).
- **#9 brand-new map** — HARD. A `mapdef` clone is cheap, but `level_ref` points at a cooked LEVEL
  (geometry, spawn volumes, nav) — authoring a new playable level is far beyond a def edit. A
  *remix* (new mapdef reusing an existing `level_ref` with a different tribe/reward profile) is the
  realistic near-term "new map".

## SDK kind (shipped — #10 fixed re-sequence)

The `GameModeDefaultDefinition` tail is a plain `u32 count` + `count`×`u32` chapter index
(vanilla `[0,1,2,3]`). The `game_mode` kind (`src/rsmm/sdk/kinds/game_modes.py`, engine
`game_mode_cook.py`) rewrites it:

```python
m.register("game_mode", id="ReverseRun", chapters=[3, 2, 1, 0])  # reorder
# [0,0,0] repeats biome 0; [3] is a one-chapter run.
```

Confidence `experimental` (upgraded from `guess` 2026-07-05): the layout is now
deserializer-verified — `GameModeDefaultDefinition::Deserialize` (FUN_140324de0, vftable
0x140eff358 slot 3) reads the list via `Serializer_ReadPolyPtrVector` into the ordered vector
@def+0x290, and each `GameModeDefault` entry (deser FUN_1403256c0) is a resource-ref to its
chapter content @entry+0x8. So the rewritten u32s are sub-object ids into the file's section
directory (numerically `[0,1,2,3]` in the vanilla def) and the vector order IS the run order as
stored. **In-game proven 2026-07-11** (`mods/SeedRunsChapter3`): overriding the retail
`All_Chapters` def at its own cooked path with `chapters=[2, 3]` starts the run directly in the
third chapter — the engine honours the rewritten order, and skipping indices 0/1 hit no
first-run/tutorial coupling. The proven route is *override-in-place* (same def id, retail path);
a net-new selectable mode id is still unproven, as are repeat orders (`[0,0,0]`).
Indices must reference existing chapters (`0..3`). Tests: `tests/test_game_mode_cook.py`.
True per-run *random* order stays out of scope (engine RNG + MP-determinism); a fixed custom
order is data-safe. Note: a re-sequenced start is a *fresh* run — no items/talents from the
skipped chapters; grant a standard loadout at run start via `R.give` if a mod wants one.

## Next steps

1. ~~Playtest a re-sequenced run~~ — DONE 2026-07-11, engine honours the new order (see above).
2. Prove (or rule out) a net-new selectable game-mode id; test repeat orders like `[0,0,0]`.
3. Mapdef remix kind (clone + repoint `tribe_ref`) for "same level, new enemy/biome profile".
4. New levels (#9 proper) remain blocked on level-asset authoring (out of scope for def cloning).
