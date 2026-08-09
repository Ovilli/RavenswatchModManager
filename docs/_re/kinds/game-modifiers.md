# Game Modifiers (mutators / "negative modes")

> 📖 Prose version on the docs site: **https://docs.rsmm.me/reverse-engineering/game-modifiers/** (`apps/docs/src/content/docs/reverse-engineering/game-modifiers.md`).
> This file stays as the raw RE field notes.


The toggleable run mutators Ravenswatch calls **GameModifiers** (the New Game Plus
checkboxes: *No boss timer*, *No minimap*, *Day only*, *More experience*, …). Heredos'
wishlist items #1 (less item scaling), #2 (less XP), #11 (harder bosses), #16 (>5 negative
modes), #17 (new negative modifiers) all live here.

Class: `oe::dt::GameModifierDefinition`. Asset glob: `*.gamemodifierdef.ot`.

## Three layers (same shape as items/talents)

| Layer | What | RE status |
|-------|------|-----------|
| **Definition asset** | `.gamemodifierdef.ot` file, loaded by the typed `oCTLibrary<GameModifierDefinition>` singleton | additive — same dir-scan + UsedRscList path as enemy defs. A new def file registers automatically. |
| **State slot** | each modifier has a CRC-keyed boolean in the generic entity-value store (on = active this run) | mapped (keys below) |
| **Behavior** | what the modifier DOES is hardcoded C++ branching on the state key | per-modifier; new behavior needs a Lua hook gated on the state key (like talents/items) |

## Key functions

- **`GameModifierDef_RegisterAssetLoader`** = `FUN_1403257b0` — registers the
  `*.gamemodifierdef.ot` glob → library loader (label "Game modifier definition"). Calls the
  generic glob-register `FUN_1404a2190`. Proves defs are file-additive, no machinery needed.
- **`EntityValueRegistry_RegisterAll`** = `FUN_1401d9b70` — registers every CRC-keyed
  game-state value (difficulty, modifiers, multiplayer, location flags) with its label + type.
  Source of the key table below.
- **`HasGameModifierStateMachine` component registrar** = `FUN_140197170` — registers the
  per-run state-machine component (component id `0x1b49a36c`) that holds which modifiers are on.
- **`Library_GameModifierDefinition_vftable`** @ `0x141411b50` — the library singleton vftable.

## Entity-value state keys (CRC32 of the label)

Read/gate these via the entity-value store (`EntityValue_Lookup`, see entity-values.md). A Lua
mod can branch on whether a modifier is active, or (for the scalar difficulty/xp ones) author a
plain value override.

### Modifier toggles (bool)
| Modifier | Key |
|----------|-----|
| No boss timer | `0x1a7945fc` |
| Less day/night half cycle | `0x1a77d42d` |
| More experience (any source) | `0x1a77e2e4` |
| No revive token | `0x1a793d1a` |
| No minimap | `0x99f27eac` |
| One chapter | `0x1a8a3688` |
| Day only | `0x1a8b53b4` |
| Night only | `0x1a8b53bc` |
| Random hero at map start | `0x1ab183ab` |
| All same heroes | `0x1ab58780` |

### Difficulty / XP scalars (directly serve Heredos #1, #2, #11)
| Value | Key |
|-------|-----|
| Game Difficulty | `0x18700873` |
| Difficulty Xp Modifier | `0x19bddb2e` |
| Global Xp Modifier | `0x187afd1d` |
| Rare Skill Chance Modifier | `0x1871c2fa` |
| Dream Shard Costs Modifier | `0x187310ec` |
| Half Cycle Count Before Boss Awakens Modifier | `0x187443de` |
| Camp Difficulty Modifier | `0x187aaecf` |
| Camp Difficulty Modifier Chance To Apply | `0x187ab36e` |

`Camp Difficulty Modifier` + `Game Difficulty` are the levers for "harder bosses / camps"
(#11). `Global Xp Modifier` / `Difficulty Xp Modifier` cover "less XP" (#2).

## What ships today vs. what's open

- **New modifier asset (relabel/reuse existing behavior)** — works now via the additive
  `.gamemodifierdef.ot` + UsedRscList path. Reuses a known modifier's hooked C++ behavior.
- **New modifier with NEW behavior** — needs a loader Lua hook gated on a state key, identical
  to the pickable-talent / ownership-gated-item pattern. No new RE wall.
- **Lift the "5 negative modes" selection cap (#16)** — PARTLY MAPPED. The select screen is the
  **`Dt Challenge Ui Controller`** (registrar `FUN_14035f7f0`), whose settings expose
  `m_oGameModifierUiSpawner` (field `0x1871e0aa`) + `m_bDisplayEmptySlots` (`0x1871e0ab`). The
  `DisplayEmptySlots` flag implies the slot count is **pre-sized by the spawner data asset**, i.e.
  the cap is DATA-DRIVEN (the challenge-UI spawner def) rather than a code constant — so #16 is
  likely an asset edit, not a loader detour. NEXT: dump the challenge-UI spawner asset, find the
  slot-count field. Per-modifier def class = `oCDtNewGamePlusModifier` (component id `0x18705119`,
  registrar `FUN_1401926c0`, has a `Difficulty` property).
- **`GameModifierDefinition` / `oCDtNewGamePlusModifier` deserialize** — NOT a bespoke byte
  reader. Ctor `FUN_1401ad830` just zeroes 0x238 + inits; the def is read through the engine's
  **generic property-reflective serializer**, props = inherited base + own `Difficulty` (descriptor
  registrar `FUN_1401fe980`, field flag `0x70001`). Implication: a new modifier def = clone an
  existing `.gamemodifierdef.ot` + edit `Difficulty`/identity + register via UsedRscList — the same
  generic `.ot` cook path the item/enemy SDK cookers already use. NO versioned-reader wall here
  (unlike herodef/skills). Truly-new *behavior* still maps to a hardcoded entity-value key, so new
  behavior needs a Lua hook on the state key; a new tier/variant of an existing modifier is
  data-only.

## Lua API (shipped)

`R.modifier` in `src/loader/lib/rsmm.lua` reads modifier/difficulty state by name through the
entity-value store (`R.entity.value(key)` → `EntityValue_Get(hero+0x2f8, out, key)`, inline f32):

```lua
R.modifier.active("No minimap")        -- true if the toggle is on this run
R.modifier.value("Game Difficulty")    -- numeric value (or nil)
R.modifier.names()                     -- known modifier/scalar names
```

Read-only; lets a mod gate custom logic on modifier state (Heredos #5/#6, and #17 custom
behavior). Pending in-game verification that the state lives on the hero store (wrong store just
returns 0/nil, never faults).

## SDK kind (shipped)

`modifier` kind (`src/rsmm/sdk/kinds/modifiers.py`, engine `game_modifier_cook.py`) clones a
vanilla `.gamemodifierdef.ot` under a new id, optional display relabel + effect-key swap:

```python
m.register("modifier", id="DoubleTrouble", base="NoBossTimer",
           name="Double Trouble", description="...",
           effect="Game Difficulty")   # reuse another modifier's behaviour key
```

Emits the cooked def + text-bank keys; `apply_mods` registers it additively via UsedRscList.
Confidence `guess` — the def cooks/loads but UI-slot *appearance* is unproven (cap, below). The
cook only rewrites whole ASCII identity strings + the 4-byte behaviour key (every binary
marker/count copied verbatim), so it never desyncs the opaque tail. Tests:
`tests/test_game_modifier_cook.py`.

## Next steps

1. Playtest-verify `R.modifier.*` reads real values, and whether a cloned modifier *shows* in
   the select screen (tests the #16 slot-cap theory directly).
2. Locate/lift the UI selection-count cap (asset dump of the challenge-UI spawner) for #16.
3. Type the modifier-def tail in the codec (title/desc keys + behaviour key as first-class
   fields) so relabel/effect don't rely on string surgery.
