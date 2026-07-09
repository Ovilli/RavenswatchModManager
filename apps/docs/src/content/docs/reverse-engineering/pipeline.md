---
title: RE pipeline
description: How the bulk decompile, symbol, and pattern artifacts are produced.
---

Everything under `docs/_re/` exists so a mod can call any function in
`Ravenswatch.exe` by name. This file documents the toolchain that
produces that capability and how to regenerate after a game patch.

## Inputs

```
~/Documents/Programming/ghidra_11.3_PUBLIC/      Ghidra install
~/.var/app/.../Ravenswatch/Ravenswatch.exe       target binary (~22 MB)
```

## Stages

```
                      ┌──────────────────────────────────┐
   Ravenswatch.exe →  │ Ghidra headless auto-analyzer    │
                      │ (project: docs/_re/project/RSMM) │
                      └──────────────┬───────────────────┘
                                     │
        ┌────────────────────────────┼──────────────────────────┐
        ▼                            ▼                          ▼
docs/_re/scripts/         docs/_re/scripts/         docs/_re/scripts/
dump_symbols_strings.py   decompile_all.py          xrefs_to_addrs.py
   │                            │                          │
   ▼                            ▼                          ▼
out/symbols.json          out/decompiled_all/       out/xref_targets/
out/strings.json          out/functions_index.tsv   out/xref_targets_summary.json
   │
   │  scripts/gen_function_patterns.py
   │  (capstone disasm → mask reloc-sensitive bytes →
   │   extend until pattern is unique-or-indexed)
   ▼
data/function_patterns.json (~20 MB, 53k entries)
   │
   │  shipped alongside winhttp.dll → game install
   ▼
src/loader/src/fn_resolver.cpp  (scans .text at runtime)
src/loader/src/fn_call.cpp      (invokes via Win x64 ABI)
src/loader/src/script_lua.cpp   (rsmm.resolve / rsmm.call bindings)
```

## Artifacts

| Path | Content | Size |
|---|---|---|
| `out/symbols.json` | 54,450 function entries — name, addr, signature, size | 9 MB |
| `out/strings.json` | 10,919 defined strings | 1 MB |
| `out/xrefs.json` | reference graph for hand-tagged hotspots | ~70 KB |
| `out/xref_targets_summary.json` | xrefs to seed/RNG/UI symbols | ~10 KB |
| `out/xref_targets/*.c` | decompiled containing function for each xref | small |
| `out/decompiled_all/<bucket>/*.c` | 46,963 pseudo-C function bodies | 218 MB |
| `out/functions_index.tsv` | flat index of decompile pass | (regen-on-demand) |
| `data/function_patterns.json` | byte-pattern signatures for `rsmm.resolve` | 20 MB |

Functions are bucketed in `decompiled_all/<bucket>/` by the top 4 hex
digits of their entry-point VA so no directory holds more than a
couple thousand `.c` files.

## Scripts

Ghidra Jython scripts (run inside the headless analyzer):

| Script | Purpose | Runtime |
|---|---|---|
| `scripts/dump_symbols_strings.py` | export every function + string to JSON | ~1 min |
| `scripts/decompile_all.py` | pseudo-C per function, bucketed | ~25 min |
| `scripts/decompile_by_addr.py` | decompile one address (debug aid) | seconds |
| `scripts/decompile_targets.py` | hand-curated list of hotspots | seconds |
| `scripts/dump_xrefs.py` | reference graph for tagged sites | <1 min |
| `scripts/xrefs_to.py` | xrefs to one address | seconds |
| `scripts/xrefs_to_addrs.py` | xrefs to a list of address targets | seconds |

Non-Ghidra (host Python) scripts:

| Script | Purpose | Runtime |
|---|---|---|
| `../../scripts/gen_function_patterns.py` | build pattern DB from exe + symbols.json | ~5 min |
| `../../scripts/test_pattern_resolve.py` | validate DB; resolve by name or addr | <30s for one, ~10 min for `--all` |

## Pattern signatures: how they survive patches

Every function's prologue (first 12–128 bytes) is disassembled with
capstone. Operand bytes that encode an address — branch displacements,
RIP-relative `lea`s, `mov mem disp32` — are replaced by `??`
wildcards. What stays is the instruction shape: opcodes, register
encoding, small constants.

When the game ships a patch, addresses shift but the instruction
*shape* mostly survives. `fn_resolver` re-scans `.text` at runtime,
finds the same pattern, and updates the resolved VA without any code
change in the manager.

For non-unique prologues (templated dtors, vtable thunks, tiny
wrappers — about 46% of functions), each entry records a
`match_index` = rank within all matches in `.text`, sorted by VA.
Validation rate on the current build: **99.50%** of entries resolve
to their recorded VA.

Cross-build accuracy (2026-07-09 patch): **77 of 92** hand-named function
symbols re-located automatically by byte pattern; the remaining ones had
prologues that changed too much and were flagged for manual RE (see the
remap pipeline below). The generic ~53k-entry DB regenerates wholesale.

## Regen on a fresh checkout

First run (imports + analyzes the exe; ~10–20 min):

```sh
bash docs/_re/run_analysis.sh        # creates project, auto-analyzes
bash docs/_re/run_dump_symbols.sh    # symbols.json + strings.json
bash docs/_re/run_decompile_all.sh   # full pseudo-C corpus
python3 scripts/gen_function_patterns.py
```

The Ghidra project (`docs/_re/project/RSMM.gpr` + `.rep/`) is
committed. The big derivatives (`out/`, `data/function_patterns.json`)
are local — see `.gitignore`.

## Recovering the symbol map after a game patch

A game patch shifts every address. The generic pattern DB self-heals at
runtime (the scan finds the same byte shape), but two things need active
recovery: `data/symbols.json` (the hand-named semantic addresses that the
loader's typed API, events, and hooks reference) and the semantic pattern
entries the loader resolves by name. This is what the remap pipeline does —
no hand-RE of every address.

Run the stages **in this order** (the old build's `.text` must be dumped
*before* the exe is re-imported, because the project is overwritten):

```sh
# 1. Dump the OLD build's .text from the still-current project (pre-import).
bash docs/_re/scripts/run_dump_text.sh          # -> docs/_re/out/text_section.{bin,json}
#    (or: analyzeHeadless ... -process Ravenswatch.exe -postScript dump_text_section.py)

# 2. Re-import + analyze the NEW exe into a fresh project (RSMM2), dumping
#    symbols, strings, xrefs, .text, and vftables of the new build.
bash docs/_re/run_analysis.sh                    # imports new exe
#    also run ExportVftables.java -> docs/_re/out_new/vftables.jsonl

# 3. Remap function symbols: old prologue pattern -> scan new .text.
python3 scripts/remap_symbols.py --update-symbols

# 4. Rewire va data symbols: vftables by RTTI name, globals by data-ref vote.
python3 scripts/rewire_va_globals.py --remap data/.symbol_remap.json \
    --vftables data/vftables.jsonl docs/_re/out_new/vftables.jsonl --update-symbols

# 5. Downgrade any symbol whose pattern is unbuildable/ambiguous to
#    status=unverified (loader skips these — fails safe vs. calling a wrong
#    address). Then regenerate the DB from the NEW exe and inject the stable
#    semantic-named entries + legacy FUN_ aliases.
python3 scripts/gen_function_patterns.py --symbols docs/_re/out_new/symbols.json
python3 scripts/sync_symbol_patterns.py --legacy-map data/.symbol_remap.json

# 6. Regenerate all six symbol artifacts, verify, rebuild the loader.
./rsmm symbols gen
python3 -m pytest tests/test_symbols.py scripts/test_pattern_resolve.py
bash src/loader/build.sh

# 7. Publish so every user picks it up without an app release.
bash scripts/publish_pattern_db.sh
```

**Why semantic pattern names matter.** The loader bakes pattern *names*
(`Sym::X_Pattern`) at build time. If those were address-derived
(`FUN_140391d30`) every patch would strand shipped DLLs. Instead the DB
carries stable semantic keys (`NamedEvent_Dispatch`, `Foo.parent` for
anchor parents); `sync_symbol_patterns.py` rebuilds them against the new
exe each regen, plus legacy `FUN_<oldaddr>` aliases so already-shipped
DLLs keep resolving.

**Delivery without an app release.** `data/function_patterns.json` is
gitignored (game-derived); it ships as assets on the rolling `pattern-db`
GitHub release (`scripts/publish_pattern_db.sh`). Users pull it with
`rsmm update-data`, which the desktop app runs silently on startup —
so a republished DB reaches every install without a Tauri update. See
`src/rsmm/engine/data_update.py`.

The raw `.text` dumps (`text_section.bin`, `out_new/`) are gitignored —
they are copyrighted game bytes and must never be committed.

## What this enables

See:

- `docs/_re/CALLING_GAME_FUNCTIONS.md` — the runtime API
  (`rsmm.resolve`, `rsmm.call`, memory r/w).
- `docs/_re/SEED_MAPGEN.md` — worked example: the seed surface.
- `mods/ExampleSeedPin/` — minimal mod that pins the run seed.

## What it doesn't enable

- **Native hooks** (`MH_CreateHook` etc). The hook engine in
  `src/loader/` builds, but every hookpoint we've tried crashes the
  game's anti-tamper layer at startup. Until we have an injection
  mechanism that survives that check, mods can only *call* and
  *read/write memory* — not *intercept*. See `docs/INTERNALS.md`
  §anti-tamper.
- **New entities / heroes / items**. Still gated on the text-`.ot` →
  binary-`.gen` re-encoder. RE work toward this is what `decompiled_all/`
  is for.