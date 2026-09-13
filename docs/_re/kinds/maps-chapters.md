# Maps, chapters & the game-mode sequence (#9 / #10)

## ✅ THE GENERATION RECIPE IS DATA, AND IT IS NOW READ/WRITE — 2026-09-12

Everything below this section was written when a chapter's *layout* was opaque.
It is not any more. `Map_<Biome>_..._TileGeneration.level.ot` is an ordinary
object graph of the shape `level_placements` walks, and it holds the entire map
generation recipe. `src/rsmm/engine/tilegen.py` decodes and re-encodes it; all
**494 tilegen objects across the three shipped chapters round-trip
byte-identically** (`tests/test_tilegen.py`).

The grammar was taken off the engine's WRITE side — each class's `Serialize` at
vftable slot 3 — not inferred from the bytes, which is the same method that
fixed the level object graph earlier the same day.

| Class | Per chapter | What it is |
|---|---|---|
| `oCDtTileSlotSettings` | 143 / 147 | one physical slot: world position, per-kind mask, per-scenario table |
| `oCDtTileKind` | 14 / 16 | one kind: how many to place, min distance, which footprints it fits |
| `oCDtTileSlotSize` | 4 / 6 (+1 inline) | a footprint family and the slot ids in it |
| `oCDtTileSlotScenarioKindCompatibility` | 1 per slot per scenario | one row of the compatibility table |
| `oCDtEntityCpntTileSpawnerSettings` | 1 | the header: kinds, scenarios, groups, mapdef backref, flag quotas |

### The numbers a chapter is made of

Dark Hills, straight out of the decoder:

| Kind | Placed | Min distance | Footprints |
|---|---|---|---|
| Crystal | 50 | 40 m | 3x3, 6x6 |
| Teleporter | 17 | 55 m | 6x6 |
| Fountain | 7 | 90 m | 6x6 |
| Wandering_Camp | 6 | 90 m | 6x6 |
| Camp | 5 | 100 m | 40x40, 64x64 |
| Special | 5 | 90 m | 40x40 |
| Start | 1 | — | 40x40 |
| Map_Boss | 1 | — | 64x64 |

Plus 18 **flag quotas** that cap by tile flag independently of the kind counts
(at most one `Wishing_Well`, two `Boss`, one `Leprechaun_Cauldron`), and four
**scenarios** — `Scenario 01`..`04`, labelled `Enemy Camp Difficulty 01`..`04`.
Avalon ships exactly one scenario, which is why its slots carry one-row tables.

### Three things that were open, and are now closed

**The 4x14 table is per-scenario x per-kind compatibility.** Rows equal the
scenario count and columns equal the kind count, in all three chapters. It is
**tri-state** — Dark Hills reads 2 (7695 times), 0 (29) and 1 (4) — so it is not
a boolean and must not be rewritten as one.

**The kind flag bytes are a footprint mask.** One byte per `oCDtTileSlotSize`
group, in the spawner's own order. It fits every kind on inspection: `Start` is
40x40 only, `Map_Boss` is 64x64 only, `Crystal` is the two small groups,
`Teleporter` is 6x6. That is also *why* the counts are placeable at all.

**The five short slots are the whole-map group.** They carry a position and
nothing else because their kind mask is empty, and the set of empty-mask slots
is *exactly* the inline 128x128 group on the spawner (`+0x190`) in all three
chapters. Not missing data.

Cross-checks that hold on every shipped chapter, and that `tilegen.validate()`
enforces so a game patch breaks loudly: slot mask length == kind count, compat
rows == scenario count, compat width == kind count, kind footprint bytes ==
group count, and every slot listed by exactly one group.

### ★ A chapter can name its map by ASSET PATH, not just by index

This is the finding that matters for #9.

`Chapter` (`Chapter_Serialize`, vftable `0x140ed7968` slot 3) is a discriminated
union:

```
u8  +0x08     one more chapter follows        (1,1,1,0 in the shipped four)
u8  +0x09     DISCRIMINATOR
if +0x09 != 0:  resref +0x10   {lstr type tag, lstr asset path}
else:           u32    +0x0c   built-in biome index (0,1,2,3)
```

**Neither branch is version-gated.** All four shipped chapters take the enum
branch, which binds them to the four built-in biome map ids the blackboard
registrar declares — and that is why "add a fifth chapter" has always read as
blocked.

The resref branch is live code, not a hypothesis. `GameModeDefaultDef_PostLoad`
walks the chapter vector at `+0x290`/`+0x298` and, for every chapter whose
`+0x09` is nonzero, calls `ResourceRef_Resolve` on `+0x10` unless it is already
resolved. So a chapter may name its content by path, the engine resolves it at
load, and nothing on that path checks a version or a flag.

⚠ **What the ref points AT is not proven.** The expected class sits in a
runtime-initialised global and cannot be read statically. A mapdef is the
hypothesis, on the strength of the tile-generation level carrying a mapdef
resref of exactly this shape. That needs a playtest, not more static reading.

`All_Chapters.gamemodedefaultdef` is six sections: an object table of four
`Chapter` entries, four 10-byte payloads and the root. Adding a fifth is the
same three writes already documented for entities and levels — grow the object
table, insert the payload before the root, append the id to the root vector —
in a plain cooked container rather than a level stream, so it needs its own
implementation.

### Symbols added

`TileKind_Serialize`, `TileSlotSettings_Serialize`, `TileSlotSize_Serialize`,
`TileSlotScenarioKindCompat_Serialize`, `TileSpawnerSettings_Serialize`,
`Chapter_Serialize`, `MapDef_Serialize`, `GameModeDefaultDef_Serialize`,
`Serializer_ReadVectorU8`, `Serializer_ReadVectorU32`,
`Serializer_ReadVectorObjIds`, `Serializer_ReadEnum` — all `ok`, patterns
unique, `verify_symbol_resolve.py` green.

Two long-standing `unverified` entries were **relocated** in the process, both
carrying the 2026-07-10 note "resolves mid-instruction, no unique anchor, needs
manual RE": `ResourceRef_Serialize` -> `0x1401c8e60` and
`Serializer_GetClassVersion` -> `0x1404fce50`. Both were found from the call
side rather than by anchor.

### The painted terrain beside the recipe (read-only, `engine/terrain.py`)

Each chapter's `Map_<Name>_Terrain.level` holds one `oCTerrainGo` and named
`oCTerrainPaintedFloatInputLayer` / `...ColorInputLayer` objects (`Base Height`
1024², `LD Path` / `LD Block` 512², `Base Water Height` 256², a vertex-colour
layer, four `Enemy Camp Difficulty 0N` masks, grass/pebble density, fog). Each
is `u32 w, u32 h, u32 byteCount` + cells (float32 or RGBA8, `byteCount = w*h*4`),
ending exactly at the payload end — the header before it varies per layer, so it
is found by those relations. `oCTerrainGo` holds the world box
`-256,-50,-256 .. 256,50,256` (unaligned in the payload) in all three chapters.
Row = world Z, column = world X from the box minimum, `y = min.y + cell * 100`.
**Proven, not assumed**: sampling that under every recipe slot reproduces the
slot's own Y to < 1 mm mean in all three chapters, and every flip/swap misses by
metres (`tests/test_terrain.py`). Tiles blend their own heights on at run time
(`Tiles Heights`), so this is the base land, not a finished run. `rsmm
map-editor` draws it.

### What is still unmined here

* `TileKind.rule` (`+0x10`): 0 on ten of Dark Hills' fourteen kinds, 2 on both
  `Key` and `Key_Keeper`, 3 on `Ruin`, 1 on `Corpse_Master`. Looks like a
  placement phase or a pairing group; unproven.
* `Slot.tail` (`+0x1c`) and the spawner's eight tail scalars (`+0x130`..`+0x14c`,
  two of them the floats 40.0 and 0.3).
* What the 0 and 1 values mean in the tri-state compatibility table — **read
  from data, not from the engine**: 2 is by far the default and reads as
  "defer to the slot's own kind mask"; 1 appears only where the mask is 0
  (Dark Hills `Start`: every 40x40 slot's mask is 0, and slots 40/30/32/35 carry
  a 1 in scenarios 1..4 respectively, one each), so it reads as "allowed in this
  scenario regardless of the mask"; 0 reads as "forbidden here". Avalon's one
  scenario is all 2s. `rsmm map-editor` colours eligibility this way; the branch
  in `TileSpawn_PlaceTiles` that consumes the byte is not yet read.
* `r13` in `TileSpawn_PlaceTiles` — still unpinned, but much less interesting
  now that the per-kind slot vocabulary is readable from the data.

---

> 📖 Prose version on the docs site: **https://docs.rsmm.me/reverse-engineering/maps-chapters/** (`apps/docs/src/content/docs/reverse-engineering/maps-chapters.md`).
> This file stays as the raw RE field notes.


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

## Current-build consumer re-trace (2026-07-12)

Re-anchored on the current binary via stable strings (the `GameModeDefaultDefinition::Deserialize`
vftable `0x140eff358` / `FUN_140324de0` addresses drifted with the 2026-07-09 patch — the latter is
now a 3-line copy stub). Model confirmed:

- `FUN_1401da350` is the game-context **blackboard registrar** — it declares every runtime cvar
  with a hashed id: `"Current chapter"` (hash `0x181d17fd`), `"Current map id"` (`0x193495b8`),
  `"Random seed"` (`0x17a117c6`), `"Reroll count"` (`0x1a922cd6`), the four biome map ids
  (Dark Hills…), and all `GameModifier : …` flags (No boss timer `0x1a7945fc`, One chapter
  `0x1a8a3688`, Day only `0x1a8b53b4`, Night only `0x1a8b53bc`, …).
- The run-setup `FUN_1401eca80` (called from `FUN_14028e5f0` at "DayNightCycle InitCycle") **reads**
  those GameModifier hashes via `FUN_1401c9600(ctx, hash)` — so it is also the **game-modifier
  consumer** (relevant to the `modifier` kind).
- Chapter order = the `GameModeDefaultDefinition` (`All_Chapters`) ordered vector @def+0x290; the
  run reads the `"Current chapter"` int to index it, and `GAME_END_NEXT_CHAPTER` advances it.

**Surgical playtest watch-point:** for a re-sequenced `game_mode`, watch which biome the run *starts*
in and the order it advances through (the "Current chapter" index stepping the rewritten vector).
Fixed reorder already proven 2026-07-11 (above); repeat orders `[0,0,0]` + net-new mode id still open.
