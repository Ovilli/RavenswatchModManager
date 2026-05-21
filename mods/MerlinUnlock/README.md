# MerlinUnlock

Bypasses the unlock-condition check on the Merlin hero so he is selectable
on the pick screen without satisfying the in-game progression requirement.

## How it works

The game's hero progression system gates each hero behind a chain of
`oIGameUnlockConditionSettings` instances embedded in the hero's
`herodef.ot.DtHeroDefinition.gen` resource. For Merlin (per
`Definitions/Heroes/Merlin.herodef.ot.DtHeroDefinition.gen`) the chain is:

  * `oCGameLockSettings[311086676]`
  * `AdditionalContentGameUnlockConditionSettings[459350033]`
  * `HeroProgressionUnlockConditionSettings[458483264]`
  * `HeroRankGameLockConditionSettings[435766022]`
  * `NamedEventGameLockConditionSettings[457179039]`

At runtime each subclass exposes a virtual `IsUnlocked(this, GameContext*) -> bool`.
The hero picker calls this on Merlin and refuses selection when it returns
false. We hook the virtual, look at the receiver's parent pointer, and
short-circuit to `true` if and only if the parent is the Merlin herodef
instance — every other hero keeps its native rule.

## Build prerequisites

1. Run the full Ghidra decompile pass once:
   ```bash
   python3 scripts/ghidra_export.py
   ```
   Produces `data/decompiled.jsonl` (~22 MB binary → 30–90 min CPU).

2. Mine the Merlin-unlock pointer set:
   ```bash
   python3 scripts/mine_merlin_unlock.py
   ```
   Writes `data/merlin_unlock_pointers.json`:
   ```json
   {
     "IsUnlocked_va":       1099511627776,
     "Merlin_HeroDef_va":   1099511628112,
     "parent_offset":       24
   }
   ```

3. Apply the mod:
   ```bash
   ./rsmm apply
   ./rsmm run
   ```

Without the pointer file, the mod loads but logs a warning and does
nothing. Safe to ship in that state — the rest of the load chain is
unaffected.

## Save-data note

Modifying `_Save/Profile_1.ob` was considered and rejected: the file is
checksummed and roundtrips through Steam Cloud. The Lua-hook path leaves
the save untouched, so disabling the mod restores the locked state with
no cleanup.
