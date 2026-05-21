# Decompile + Merlin Unlock Workflow

End-to-end recipe for getting a full Ghidra decompile of `Ravenswatch.exe`
into the repo, then deriving the pointer set the `MerlinUnlock` mod needs.

## 1. Decompile every function

```bash
python3 scripts/ghidra_export.py \
    --ghidra  /home/ovilli/Documents/Programming/ghidra_11.3_PUBLIC \
    --exe     /home/ovilli/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/Ravenswatch/Ravenswatch.exe \
    --project ghidra_project \
    --out     data/decompiled.jsonl
```

* First pass imports the PE and runs Ghidra's full auto-analysis; subsequent
  passes reuse `ghidra_project/Ravenswatch.gpr` so only the export step
  repeats.
* Output is JSON-Lines, one function per line:
  `{"addr":"0x140abc...","name":"...","sig":"...","size":N,"code":"<C source>"}`.
* Wall time on the 22 MB PE: **30–90 min** depending on CPU + Java heap
  (`_JAVA_OPTIONS=-Xmx8G` set by the driver).

## 2. Mine the Merlin unlock pointer set

```bash
python3 scripts/mine_merlin_unlock.py
```

Writes `mods/MerlinUnlock/pointers.json` (alongside `init.lua` so
`rsmm apply` mirrors it into the game's mods folder):

```json
{
  "IsUnlocked_va":            "<filled in>",
  "Merlin_HeroDef_xref_va":   "<filled in>",
  "parent_offset":            24
}
```

If the mining regex misses, inspect manually:

```bash
jq -r 'select(.name | test("Unlock"))   | "\(.addr)  \(.name)"' data/decompiled.jsonl
jq -r 'select(.code | test("Merlin\\.herodef")) | "\(.addr)  \(.name)"' data/decompiled.jsonl
```

…and either update `ISUNLOCKED_RE` in `scripts/mine_merlin_unlock.py` or
write the JSON by hand.

## 3. Apply the mod

```bash
./rsmm apply
./rsmm run
```

Pick screen now shows Merlin as selectable for every save slot. Disable
the mod (`enabled = false` in `mods/MerlinUnlock/manifest.toml`, then
`./rsmm apply`) to revert — the save file is never touched.

## 4. How the in-game hook works

`oCDtHeroDefinition::Merlin` carries five
`oIGameUnlockConditionSettings`-derived children:

```text
oCGameLockSettings                              (Class7, lock 'orchestrator')
└── AdditionalContentGameUnlockConditionSettings (Class15, DLC/ownership gate)
└── HeroProgressionUnlockConditionSettings       (Class16, gameplay progression)
└── HeroRankGameLockConditionSettings            (Class17, rank threshold)
└── NamedEventGameLockConditionSettings          (Class15-alt, story event)
```

All four subclasses inherit `oIGameUnlockConditionSettings::IsUnlocked`,
a virtual called by `oCDtHeroPickerEntityCpnt` when the player hovers a
hero portrait. We hook the virtual once, inspect the receiver's parent
field (offset `+0x18` for v1.26), and short-circuit to `true` iff the
parent is Merlin's herodef. Every other hero still runs the native
unlock check.

## 5. Why not patch the cooked herodef directly?

* The `.gen` payload sections are aligned + length-prefixed; rewriting
  them risks invalidating offsets recorded by `UsedRscList.ot` and the
  `rsmm` `asset_map`.
* A binary swap would persist a localized change but reverting requires
  the original file; the Lua hook is fully runtime-only.
* The hook approach also generalises trivially to every other locked
  hero — just rename the parent pointer match.

## 6. Reproducing the cooked-asset references

Merlin's encoded herodef lives at:

```text
DarkTalesResources/_Cooking/Nqhdzdidrzv/Aqurqv/Hquldz.nqurtqh.ri.NiAqurNqhdzdidrz.yqz
            ^---------------- "Definitions/Heroes/Merlin.herodef.ot.DtHeroDefinition.gen"
```

The encoding is the substitution cipher in
`src/rsmm/engine/cipher.py`; `./rsmm decode <file>` dumps the cooked
section table so you can read the embedded class list without Ghidra.

## 7. Save-file format

`_Save/Profile_1.ob` is the persistent per-profile save and is the
canonical store for unlock state — `strings` reveals fields like
`HeroRankGameLockConditionData`, `HeroProgressionUnlockConditionData`,
`HeroStoryUnlockConditionData`, `AdditionalContentGameUnlockConditionData`.
We deliberately do **not** edit it: Steam Cloud will fight us, and the
file is checksummed by `oCSaveSerializer`. The runtime hook in `MerlinUnlock`
is the durable answer.
