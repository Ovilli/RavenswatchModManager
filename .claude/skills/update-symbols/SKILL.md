---
name: update-symbols
description: Patch-day runbook for when Steam updates Ravenswatch.exe — snapshot the new build, remap data/symbols.json old→new, audit every match, relocate data globals, find moved struct field offsets and update the Lua SDK / C++ hook / spec mocks, rebuild the pattern DB, check cooked-data format changes, and ship. Use as soon as the game exe changes (rsmm says the pattern DB was built for another exe, `verify_symbol_resolve.py` fails, or a mod breaks right after a game update).
---

# Update symbols after a game patch

The ordered runbook. Tool details (Ghidra, BinDiff, `va_locators`, fingerprints, `disasm.py`) are in the `re-workflow` skill; this skill says which to run, in what order, and what to check. Helpers specific to this job are in `tools/update_symbols.py` (`preflight`, `snapshot`, `audit`, `callers`, `fields`, `class-versions`).

Moving functions is the easy half and every gate catches it. Struct fields moving is the half that breaks things silently (a damage meter reading the wrong offset shows wrong numbers, no error), and no gate catches it: step 6 is not optional.

Use `PYTHONUTF8=1` for `python rsmm …` and anything that writes `data/symbols.json` (under cp1252 a write truncated it once). Don't set it for pytest. `data/symbols.json` stays `indent=1` with raw UTF-8 (em dashes unescaped), which is what `remap_symbols.py` and `va_locators.py` write; check `git diff --stat` after every tool that writes it: a whole-file diff means the form changed. Make copies of it with bash `git show … >`, not PowerShell (which re-encodes the redirect).

Game bytes (exe copies, `.text` dumps, listings) never go in git. Keep them in a snapshot folder outside the clone, the `--out` folder you pass to `snapshot`.

## Machine paths

Every path below is per machine; nothing in the repo knows them. Before step 0, look them up in your persistent memory (if you have one). For any that are missing, find them (ask the user when you can't) and save them to memory, one entry for this machine's patch-day paths, so the next patch day starts from them. Export the ones with an env var for the session.

| Path | Env var / flag | Used by |
|---|---|---|
| Game install | `RSMM_GAME_DIR` / `--game` | every step |
| Ghidra 12 install | `GHIDRA_INSTALL_DIR` (`GHIDRA_HOME` in older scripts) | step 1 fallback, `serve.sh` |
| Ghidra project (folder holding the `.gpr`) and its program name | `RSMM_GHIDRA_PROJECT` / `--ghidra-project` | step 0, step 1 fallback, `serve.sh` |
| Snapshots folder (outside the clone) | `snapshot --out` | steps 1-3, 6, 7 |
| Previous build's exe, if not in the snapshots folder | `--old-exe` | steps 2, 3, 6 |

When a patch day ends, update the memory: the new snapshot is next time's previous build.

## 0. Preflight

```
python tools/update_symbols.py preflight
```

- **Install clean?** `.rsmm_state.json` `active` must be empty and there must be no `*.rsmm.bak`. If mods were applied when Steam patched, patched files are mixed with mod files: sort that out first. Do **not** run `rsmm restore`/`apply` before step 7; a stale asset map can make restore delete files that moved.
- **Ghidra unlocked.** Stop the GUI / `tools/ghidra_mcp/serve.sh`. Set `RSMM_GHIDRA_PROJECT` to the folder holding your `.gpr` (or pass `--ghidra-project`); without it the lock is not checked. The game install comes from `--game` or `RSMM_GAME_DIR`, as for `rsmm`.
- **Patched?** It compares the exe with `data/function_patterns.meta.json`.
- `git pull --ff-only`, then branch `chore/remap-patch-<new-sha12>` from `origin/main`.

## 1. Snapshot the new build

```
python tools/update_symbols.py snapshot --out <snapshots>
```

Writes `<snapshots>/<sha12>/`: `Ravenswatch-<sha12>.exe`, the Steam `appmanifest_*.acf` (holds the `buildid`), `listing.tsv`, `sha256sums.txt`, `class_versions.json` (about 4 min; `--no-class-versions` skips it). It refuses a modded install (`--allow-modded` overrides; such a snapshot's listing and class versions are not the vanilla build's). Next patch's remap and class-version diff are made from this, so keep it.

You need the **previous** build's exe too: the snapshot from last patch day. If there is none, recover it from the Ghidra project, which stores the imported file's original bytes, before importing the new exe. Work on a copy of the project (a GUI project may hold the lock) and open it `-readOnly`:

```
$GHIDRA_INSTALL_DIR/support/analyzeHeadless[.bat] <project copy dir> <project name>     -process <old program, e.g. Ravenswatch.exe> -noanalysis -readOnly     -scriptPath tools/ghidra_scripts -postScript DumpOriginalBytes.java <snap>/Ravenswatch-old.exe
```

On Linux the default `MAXMEM=2G` OOMs on this exe: use the 6G `support/launch.sh … AnalyzeHeadless` form from `re-workflow`.

It prints the program's sha256: check it is the build you expect, not one from two patches back (a stale `.text` dump remapped from the wrong addresses on 2026-11-17). Then pass that file as `--old-exe`.

## 2. Remap function symbols

```
git show HEAD:data/symbols.json > <snap>/symbols.old.json
python scripts/remap_symbols.py --old-exe <snapshots>/<old-sha12>/Ravenswatch-<old-sha12>.exe \
    --write <snap>/remap-map.json --update-symbols
```

Matches each symbol's old prologue (relocation bytes wildcarded) in the new `.text`, then by neighbour delta. Expect almost all to match and a few `UNMATCHED`. A match is a hypothesis: prologues are not unique.

## 3. Audit every match

```
python tools/update_symbols.py audit --old-exe <old.exe> --new-exe <game>/Ravenswatch.exe \
    --old-symbols <snap>/symbols.old.json --json <snap>/audit.json
```

Compares old and new bodies (normalised mnemonic sequence), checks that callees agree through the map, and flags a start that stopped being a `.pdata` function or a symbol that did not move but whose body changed (= unmatched). Reading the output:

- **Wrong match**: body ratio far down (0.1–0.3 last time) and callees disagree. Relocate by hand.
- **Unmoved + body changed**: the remap did not match it. Relocate by hand.
- **Changed body, 0.85–0.97, callees agree**: usually the same function with shifted struct offsets. Read the diff to confirm it is offsets, not logic; these functions feed step 6.

Hand relocation, most reliable first:

1. **Call graph.** `python tools/update_symbols.py callers --exe <exe> --symbols <symbols.json> <Callee>` lists every `call`/`jmp` site and the function that holds it. Run it on both builds: "sole caller of X in the old build" → "sole caller of X in the new build" is unambiguous.
2. **RTTI / vtables.** A ctor is the function that writes its base vftable then its own; `va_locators` finds vftables by RTTI name.
3. **Arguments.** Among several callers of one function, the one passing the distinguishing argument (e.g. the 4th of 5 `OptionsMenu_AddCategory` callers, the only one passing category byte 5).

Put the address in `raw` and add a sentence to that symbol's `note` saying how it was found: next patch, that sentence is the recipe. Rerun `audit` until only explained rows remain.

**Anchors** (`anchor = parent + offset`, an inlined site): the parent moves with step 2, the offset does not. Disassemble `parent+offset` on both builds (`scripts/disasm.py --exe <exe> <va>`) and check the instruction is the same and its immediates are unchanged; only a rip displacement may differ.

## 4. Relocate data globals (`status=va`)

```
python tools/va_locators.py recover --exe <game>/Ravenswatch.exe --apply
```

Applies globals with ≥2 agreeing votes and no dissent. Check each single-vote one by hand (the same string table / the same first read at the new VA). For any left unplaced, show nothing in `src/loader` reads it by name before demoting it to `unverified` with a note naming the build it was last valid on. 

Then capture locators **on the new build**, so next patch's `recover` works:

```
python tools/va_locators.py capture --exe <game>/Ravenswatch.exe --force
python tools/va_locators.py verify --exe <game>/Ravenswatch.exe
```

`data/va_locators.json` is gitignored: copy it into the new build's snapshot folder so it survives a fresh clone.

## 5. Pattern DB, regenerate, gate

```
python rsmm symbols gen
python rsmm rebuild-fn-patterns --force
python rsmm symbols gen --check
python rsmm symbols check
python scripts/verify_symbol_resolve.py
```

`rebuild-fn-patterns` generates the DB from the exe's own `.pdata`, syncs the named entries from `symbols.json`, verifies and resolves every entry, and puts the old DB back on failure. It warns when the entry count drops more than 5% from the previous DB: patches add or remove a few hundred functions, so a big drop means the function list was from another build (2026-11-17: an old Ghidra export as the list gave ~50k patterns cut from mid-function code, 65,328 → 50,085 entries, while every named-symbol gate still passed).

`gen --check` only proves the generated files agree with the map. `verify_symbol_resolve.py` is the gate that says the addresses land on function starts.

## 6. Struct field offsets

For each engine struct the SDK or loader reads by offset, pick a **family**: functions that take the same object. One vote table across everything mixes unrelated structs and gives nonsense.

```
python tools/update_symbols.py fields --old-exe <old.exe> --new-exe <game>/Ravenswatch.exe \
    --old-symbols <snap>/symbols.old.json \
    --family "HeroController=HeroController_Ctor,HeroController_AddSkill,HeroStats_OnDamageDealt,..." \
    --family "GameOptions=0x<old ctor>:0x<new ctor>,OptionsMenu_BuildAudio,OptionsMenu_BuildLastCategory" \
    --family "RakNetConnection=RakNetConnection_Ctor"
```

A member is a symbol name or `0xOLD:0xNEW` for an unnamed function (resolve one through the pattern DB). It prints every displacement that moved, the vote count, and splits, then a delta summary. A real layout change looks like one delta from a boundary up (an inserted field): last time hero controller +0x18 from 0xcc0, game options +0x30 from 0xf10, RakNetConnection −0x10 from 0xe0. A one-vote outlier or a split near the boundary is unclear: settle it by reading the constructor's per-field writes old vs new (for options, the per-name slot writes). Include the relocated symbols from step 3 in their families; their reads were not covered by anything else.

A field no function in the family reads is invisible to this method. For each offset a consumer uses, make sure some family function reads it, or check it by hand.

Then update every consumer of a moved offset:

- `src/loader/lib/rsmm.lua`, `src/loader/lua/rsmm/*.lua` (damage, damage_netcode, entity, talent_events, talent_grant, items …)
- `src/loader/src/hook_*.cpp` (hook_events, hook_skins, hook_keybinds …)
- `tests/lua/rsmm_spec.lua` mock offsets: the mocks are engine-faithful, so they move with the engine
- `note` text in `data/symbols.json` and code comments that quote old offsets

Grep each moved literal across those paths; an offset against a different struct that happens to share the number stays. Then `lua tests/lua/rsmm_spec.lua`, and `cmake --build src/loader/build` if a `hook_*.cpp` changed.

## 7. Event data and cooked data

```
python tools/mine_event_names.py --verify
python tools/mine_event_payloads.py --verify
python rsmm rebuild-asset-map            # then git diff data/asset_map.*: order-only or real changes?
python tools/update_symbols.py class-versions --baseline <snapshots>/<old-sha12>/class_versions.json
pnpm test:python:fast
pytest -n auto -m slow
ruff check .
```

A miner `--verify` failure means a confirmed event name or payload layout is gone from the new build: find it in the miner's full output (`--json`), fix the event's entry in `data/symbols.json`, then `python rsmm symbols gen` (`events_gen.lua` is generated from the map).

A recook is a format change even when no asset path changed: the class-version diff shows which classes moved version. A test that leaned on a version mismatch in shipped data loses it when the patch recooks everything to one version; make such a test set up its own mismatch.

## 8. Ship

- Commit on `chore/remap-patch-<sha12>` in reviewable pieces (symbols + offsets + spec; asset map; pattern DB; any tool fix), push, open a PR (follow the repo's PR rules).
- Human-only, after merge: publish the pattern DB (`scripts/publish_pattern_db.sh`); dispatch the loader channel (`publish-loader.yml`, dry run first; see the `release` skill) whenever the Lua SDK or a `hook_*.cpp` constant changed.
- In game: `rsmm install-loader` (a Steam update deletes the loader), launch with the `RSMM_DUMP_SYMBOLS` loader flag, then `rsmm symbols audit`.
- Keep the snapshot folder: it is next patch's "old build".
