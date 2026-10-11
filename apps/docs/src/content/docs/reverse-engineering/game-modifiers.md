---
title: Game modifiers
description: The run mutators ("negative modes") — where their state lives, which keys drive difficulty and XP, and why the 5-slot selection cap is not in the spawner data.
---

:::note
Status: definition + state layers mapped; `modifier` SDK kind and the read-only
`R.modifier` Lua API ship today. Class `oe::dt::GameModifierDefinition`, asset
glob `*.gamemodifierdef.ot`.
:::

The toggleable run mutators the game calls **GameModifiers** — the New Game Plus
checkboxes (*No boss timer*, *No minimap*, *Day only*, *More experience*, …).

## Three layers

| Layer | What | Status |
|-------|------|--------|
| **Definition asset** | `.gamemodifierdef.ot`, loaded by the typed `oCTLibrary<GameModifierDefinition>` singleton | Additive — same dir-scan + `UsedRscList` path as enemy defs. A new def file registers automatically. |
| **State slot** | a CRC-keyed boolean per modifier in the generic entity-value store (on = active this run) | Mapped (keys below) |
| **Behavior** | what the modifier DOES is hardcoded C++ branching on the state key | Per-modifier. New behavior needs a Lua hook gated on the key, exactly like talents/items. |

## Key functions

- **`GameModifierDef_RegisterAssetLoader`** `FUN_1403257b0` — registers the
  `*.gamemodifierdef.ot` glob → library loader (label "Game modifier definition"),
  via the generic glob-register `FUN_1404a2190`. This is what proves defs are
  file-additive.
- **`EntityValueRegistry_RegisterAll`** `FUN_1401d9b70` — registers every CRC-keyed
  game-state value (difficulty, modifiers, multiplayer, location flags) with its
  label + type. Source of the key table below.
- **`HasGameModifierStateMachine` registrar** `FUN_140197170` — the per-run
  state-machine component (id `0x1b49a36c`) holding which modifiers are on.
- **`Library_GameModifierDefinition_vftable`** `0x141411b50`.

## State keys (CRC32 of the label)

Read these through the entity-value store — see
[Entity values](/reverse-engineering/entity-values/).

### Toggles (bool)

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

### Difficulty / XP scalars

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

`Camp Difficulty Modifier` + `Game Difficulty` are the "harder camps/bosses"
levers; `Global Xp Modifier` / `Difficulty Xp Modifier` are the XP levers.

## Deserialization: no bespoke reader

`GameModifierDefinition` / `oCDtNewGamePlusModifier` are **not** read by a
hand-rolled byte reader. The ctor `FUN_1401ad830` zeroes 0x238 and inits; the def
goes through the engine's generic property-reflective serializer (own property
`Difficulty`, descriptor registrar `FUN_1401fe980`, field flag `0x70001`;
component id `0x18705119`, registrar `FUN_1401926c0`).

Implication: a new modifier def = clone an existing `.gamemodifierdef.ot`, edit
identity + `Difficulty`, register via `UsedRscList`. No versioned-reader wall
(unlike herodefs and skills).

## Lua API (shipped)

`R.modifier` reads modifier/difficulty state by name. The values live in the
**global scene context** (the "New Game Plus" group of the entity-value
registry), not on the hero — read from the hero's store every one of them came
back `0.0` in game. So `R.modifier` goes through `R.game`:

```lua
R.modifier.active("No minimap")        -- true if the toggle is on this run
R.modifier.value("Game Difficulty")    -- numeric value, or nil
R.modifier.why()                       -- why the last read was nil
R.modifier.names()                     -- known modifier/scalar names
```

`SceneContextValue_Find(ctx, key)` returns the map entry's **record**, not a
value union. Read off the engine's own setter (`FUN_1402091a0` →
`FUN_140716470` → `FUN_140706660`) and named by RTTI:

| Offset | Field |
|--------|-------|
| `+0x00` | `oCGlobalEntityValueSettings*` |
| `+0x08` | `EntityCpntValueSignal<oCEntityValueUnion const&>` (change signal) |
| `+0x30` | `oCEntityValueUnion` — `+0x08` storage tag, `+0x10` inline data, `+0x18` type byte |

Storage: tag `4` means the data is **inline** at `union+0x10`; any other
non-zero tag is the data's **address** with bit 0 used as a flag (`tag & ~1`).
The type byte, from `EntityValueUnion_InitAsType`'s jump table:

| Type | Value | Size / align | Stored |
|------|-------|--------------|--------|
| `0` | f32 | 4 / 4 | inline |
| `1` | int32 (first dword of the slot) | 16 / 8 | always out of line |
| `2` | bool | 1 / 1 | inline — the modifier **toggles** |
| `10` | unset | — | — |

The decode follows the union's own type byte. Measured in game at a run start:
`Global Xp Modifier` 0.25, `Difficulty Xp Modifier` 1.25, `Current chapter` 0.

### Writing (experimental, local-only)

```lua
R.schedule.next_main(function()          -- engine-mutating: main thread only
  R.modifier.enable_writes()             -- opt-in, shared with R.stat
  R.modifier.set("Global Xp Modifier", 1.5)   -- true when it reads back
  R.modifier.clear("Global Xp Modifier")      -- restores the pre-write value
end)
```

`R.modifier.set` calls the engine's own setter — `SceneContextValue_SetFloat`
(`FUN_14020a580`), `SceneContextValue_SetInt` (`FUN_1402091a0`) or
`SceneContextValue_SetBool` (`FUN_140209010`), picked by the value's type byte —
so the change signal fires like any engine write. **Proven in game:** setting
`No minimap` to 1 mid-run removed the minimap immediately. Both land in `FUN_140706660`, which is the replication
gate: `settings+0xbe` marks a value as **replicated**, a client's write to one is
dropped silently, and a host's is queued for peers. So:

- a **replicated** value is written only when the run is provably solo
  (`Hero Count` reads exactly 1) — refused in co-op and when the count is
  unreadable. ⚠ `Hero Count` read **0** at the start of a solo run, so this gate
  currently refuses replicated values even solo; the two values tested so far
  are not replicated;
- every write is **read back**, because the engine's refusal returns normally;
- a key the context does not hold is refused (the setter never creates one);
- `R.modifier.why()` gives the reason for any `false`.

Modifiers consumed at map generation ("One chapter", "Day only", "Random hero
at map start") change nothing when set mid-run, and the challenge screen does
not show a value set this way.

## SDK kind (shipped)

`modifier` (`src/rsmm/sdk/kinds/modifiers.py`, engine `game_modifier_cook.py`)
clones a vanilla def under a new id with an optional relabel + effect-key swap:

```python
m.register("modifier", id="DoubleTrouble", base="NoBossTimer",
           name="Double Trouble", description="...",
           effect="Game Difficulty")   # reuse another modifier's behaviour key
```

Emits the cooked def + text-bank keys; `apply` registers it additively via
`UsedRscList`. Confidence `guess` — the def cooks and loads, but the UI slot
appearance is unproven. The cook rewrites only whole ASCII identity strings and
the 4-byte behaviour key (every binary marker/count copied verbatim), so it can't
desync the opaque tail. Tests: `tests/test_game_modifier_cook.py`.

## The "5 selected modifiers" cap

Resolved as **not** a spawner-data field. The select screen is the
`Dt Challenge Ui Controller` (registrar `FUN_14035f7f0`), whose settings expose
`m_oGameModifierUiSpawner` (`0x1871e0aa`) and `m_bDisplayEmptySlots`
(`0x1871e0ab`) — which is what first suggested a data-driven slot count. The
actual cap is the controller's pad-to-5 loops plus progressive slot unlocking
keyed off a profile value; lifting it above 5 means patching those loops, which
is high risk and currently parked.

## Open

1. Playtest-verify `R.modifier.*` reads real values, and whether a cloned modifier
   *shows* in the select screen.
2. Type the modifier-def tail in the codec (title/desc keys + behaviour key as
   first-class fields) so relabel/effect stop relying on string surgery.
