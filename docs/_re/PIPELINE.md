# Reverse-engineering pipeline

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

Cross-build accuracy hasn't been measured — when the next patch ships
we'll know. Regen is one command if it drifts:

```sh
bash docs/_re/run_dump_symbols.sh
python3 scripts/gen_function_patterns.py
python3 scripts/test_pattern_resolve.py --all
```

## Regen on a fresh checkout

First run (imports + analyzes the exe; ~10–20 min):

```sh
bash docs/_re/run_analysis.sh        # creates project, auto-analyzes
bash docs/_re/run_dump_symbols.sh    # symbols.json + strings.json
bash docs/_re/run_decompile_all.sh   # full pseudo-C corpus
python3 scripts/gen_function_patterns.py
```

Subsequent runs (after a game patch, re-using the project):

```sh
bash docs/_re/run_dump_symbols.sh
python3 scripts/gen_function_patterns.py
```

The Ghidra project (`docs/_re/project/RSMM.gpr` + `.rep/`) is
committed. The big derivatives (`out/`, `data/function_patterns.json`)
are local — see `.gitignore`.

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
