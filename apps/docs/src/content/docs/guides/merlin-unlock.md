---
title: Hero unlock gates
description: The five lock types on a hero definition, which ones a mod may open, and how to get the decompile that shows you.
---

Every locked hero on the picker screen is locked by one of five different
mechanisms. They are **not** interchangeable, and the distinction decides
whether a mod may touch them at all.

:::caution[This page used to say something else]
An earlier version of this guide described a `MerlinUnlock` mod that hooked
`IsUnlocked` unconditionally and short-circuited it to `true` for a chosen
herodef. That recipe is retracted. It did not distinguish a progression gate
from the ownership gate, so what it actually documented was a DLC bypass. The
script and mod it referenced (`scripts/mine_merlin_unlock.py`,
`mods/MerlinUnlock/`) never existed in this repo.
:::

## The five gates

A hero definition carries children derived from
`oIGameUnlockConditionSettings`. `IsUnlocked` is **vftable slot 14** on every
`oIGameUnlockConditionData` subclass — the base leaves 10/11/14 as stubs and
each subclass overrides them. `oCDtHeroPickerEntityCpnt` calls it when the
player hovers a portrait.

| Settings class | Symbol | Reads | Mod may open? |
|---|---|---|---|
| `HeroProgressionUnlockConditionSettings` | `HeroProgressionUnlock_IsUnlocked` | `required(settings+0xb0) <= reached(data+0x40)` | yes |
| `HeroRankGameLockConditionSettings` | `HeroRankLock_IsUnlocked` | profile rank vs. required rank | yes |
| `HeroStoryUnlockConditionSettings` | `HeroStoryUnlock_IsUnlocked` | story counter vs. threshold | yes |
| `ChallengeUnlockConditionSettings` | `ChallengeUnlock_IsUnlocked` | referenced challenge complete | yes |
| `AdditionalContentGameUnlockConditionSettings` | *(deliberately unnamed)* | Steam DLC entitlement | **no** |

The first four are grind gates. They read counters the player earns and that
live in `_Save/Profile_*.ob`. Opening them locally changes only which portraits
your own client offers.

The fifth is not a gate on progress, it is a gate on purchase. It resolves
through the content manager's vftable slot 1:

```text
oIAdditionalContentManager::vftable     @ 0x140f3e288   slot[1] = stub, always reject
oCNullAdditionalContentManager::vftable @ 0x140f3e1e0   same stub
oCLocalAdditionalContentManager::vftable@ 0x140f3e578   FUN_140647440 — GetFileAttributesW
oCSteamAdditionalContentManager::vftable@ 0x140f8db00   FUN_140a2c600 — ISteamApps::BIsDLCEnabled
```

On a Steam build `FUN_140a2c600` reads the u32 pack key at `node+0x3c` and asks
`ISteamApps::BIsDLCEnabled` whether the account owns it. That symbol is left
unnamed in `data/symbols.json` on purpose, so nothing in the SDK can resolve it
by semantic name.

Heroes sold as content packs — Merlin (Merlin HeroPack), the Romeo & Juliet
HeroPack roster — sit behind that fifth gate. Buy the pack and every mod here
works on them normally; there is no supported path around it.

## Opening the progression gates

`R.hero.unlock_progression()` hooks the four grind gates by symbol name and
returns how many armed. It resolves each through `I.resolve`, so a symbol that
is unverified for the current build fails closed rather than hooking a stale
address. Ownership is untouched.

```lua
local R = require "rsmm"
R.on("ready", function() R.hero.unlock_progression() end)
```

Shipped as `mods/hero-unlock/`. Runtime-only — the profile save is never
written, so disabling the mod restores the stock picker with no cleanup.

## Getting the decompile these addresses come from

```bash
python3 scripts/ghidra_export.py \
    --ghidra  /path/to/ghidra_11.3_PUBLIC \
    --exe     "$GAME/Ravenswatch.exe" \
    --project ghidra_project \
    --out     data/decompiled.jsonl
```

* First pass imports the PE and runs full auto-analysis; later passes reuse
  `ghidra_project/Ravenswatch.gpr`, so only the export repeats.
* Output is JSON-Lines, one function per line:
  `{"addr":"0x140abc...","name":"...","sig":"...","size":N,"code":"<C source>"}`.
* Wall time on the 22 MB PE: **30–90 min** (`_JAVA_OPTIONS=-Xmx8G` is set by
  the driver).

To find the gate implementations yourself:

```bash
jq -r 'select(.name | test("Unlock")) | "\(.addr)  \(.name)"' data/decompiled.jsonl
```

Or skip Ghidra entirely — `python scripts/disasm.py --resolve HeroRankLock_IsUnlocked`
disassembles the live exe with symbol annotation.

## Why not patch the cooked herodef instead?

* The `.gen` payload sections are aligned and length-prefixed; rewriting them
  risks invalidating offsets recorded by `UsedRscList.ot` and `asset_map`.
* A binary swap persists, but reverting needs the original file. The Lua hook
  is runtime-only.

Merlin's encoded herodef, for reference:

```text
DarkTalesResources/_Cooking/Nqhdzdidrzv/Aqurqv/Hquldz.nqurtqh.ri.NiAqurNqhdzdidrz.yqz
            ^---------------- "Definitions/Heroes/Merlin.herodef.ot.DtHeroDefinition.gen"
```

The encoding is the substitution cipher in `src/rsmm/engine/cipher.py`;
`./rsmm decode <file>` dumps the cooked section table.

## Save-file format

`_Save/Profile_1.ob` is the canonical store for unlock state — `strings` shows
`HeroRankGameLockConditionData`, `HeroProgressionUnlockConditionData`,
`HeroStoryUnlockConditionData`, `AdditionalContentGameUnlockConditionData`.

Do **not** edit it. Steam Cloud will fight you and `oCSaveSerializer`
checksums the file. Runtime hooks are the durable answer. If you want to
experiment, copy the profile to `/tmp` first.
