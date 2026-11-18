---
title: RE pipeline
description: How the bulk decompile, symbol, and pattern artifacts are produced.
---

Everything under `docs/_re/` exists so a mod can call any function in
`Ravenswatch.exe` by name. This file documents the toolchain that
produces that capability and how to regenerate after a game patch.

## Inputs

```
$GHIDRA_INSTALL_DIR                                     Ghidra install
<game dir>/Ravenswatch.exe                       target binary (~22 MB; RSMM_GAME_DIR)
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
| `docs/_re/scripts/dump_symbols_strings.py` | export every function + string to JSON | ~1 min |
| `docs/_re/scripts/decompile_all.py` | pseudo-C per function, bucketed | ~25 min |
| `docs/_re/scripts/decompile_by_addr.py` | decompile one address (debug aid) | seconds |
| `docs/_re/scripts/decompile_targets.py` | hand-curated list of hotspots | seconds |
| `docs/_re/scripts/dump_xrefs.py` | reference graph for tagged sites | <1 min |
| `docs/_re/scripts/xrefs_to.py` | xrefs to one address | seconds |
| `docs/_re/scripts/xrefs_to_addrs.py` | xrefs to a list of address targets | seconds |

Non-Ghidra (host Python) scripts:

| Script | Purpose | Runtime |
|---|---|---|
| `scripts/gen_function_patterns.py` | build pattern DB from exe + symbols.json | ~5 min |
| `scripts/test_pattern_resolve.py` | validate DB; resolve by name or addr | <30s for one, ~10 min for `--all` |

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
Every pattern is scanned against the whole `.text`, counting matches exactly
as the loader does (every start position, overlapping hits included). A
pattern that matches more than once is lengthened as far as its own function
goes, so it becomes unique where it can and falls back to an index where it
cannot. On the 2026-10-03 build, **100%** of 50,056 entries resolve to their
recorded VA (`scripts/test_pattern_resolve.py --all`). One scanner,
`gen_function_patterns.scan_offsets`, is shared by every pattern script so they
cannot drift from each other or from the loader.

The DB published before this fix indexed only the patterns repeated inside its
own symbol list, and counted non-overlapping matches: about 73% of its generic
entries resolve to the address they were made for. The hand-mapped symbols the
loader uses were unaffected (all 192 `status=ok` symbols verify). Republish to
ship the fixed DB.

Cross-build accuracy (2026-07-09 patch): **77 of 92** hand-named function
symbols re-located automatically by byte pattern; the remaining ones had
prologues that changed too much and were flagged for manual RE (see the
remap pipeline below). The generic ~53k-entry DB regenerates wholesale.

## Rebuild for the installed game

`./rsmm rebuild-fn-patterns` regenerates the DB for the exe you have, adds the
stable named entries, and checks the result: every `status=ok` symbol must land
on a function boundary and every entry must resolve to its recorded address.
The old DB is kept as `*.prev` and put back if any step fails or you interrupt
it. About 2–3 minutes. `--ghidra` re-dumps `symbols.json` first; `--dry-run`
prints the plan. It needs `capstone` and uses the repo's `.venv` if the current
interpreter lacks it. It does not remap `data/symbols.json` after a patch,
rebuild the loader, or publish.

## Regen on a fresh checkout

First run (imports + analyzes the exe; ~10–20 min):

```sh
export GHIDRA_INSTALL_DIR=/path/to/ghidra          # every run_*.sh needs it
export RAVENSWATCH_EXE=/path/to/Ravenswatch.exe   # run_analysis.sh only
bash docs/_re/run_analysis.sh        # creates project, auto-analyzes
bash docs/_re/run_dump_symbols.sh    # symbols.json + strings.json
bash docs/_re/run_decompile_all.sh   # full pseudo-C corpus
python3 scripts/gen_function_patterns.py
```

The Ghidra project and the dumps under `docs/_re/out*/` are local (see
`.gitignore`). `data/function_patterns.json` is committed, so a checkout
has the DB for the current game build.

## Recovering the symbol map after a game patch

A game patch shifts every address. The generic pattern DB self-heals at
runtime (the scan finds the same byte shape), but two things need active
recovery: `data/symbols.json` (the hand-named semantic addresses that the
loader's typed API, events, and hooks reference) and the semantic pattern
entries the loader resolves by name. This is what the remap pipeline does —
no hand-RE of every address.

The full runbook, with the checks for each stage, is the `update-symbols`
skill in the repo (`.claude/skills/update-symbols/SKILL.md`). In short:

```sh
# Snapshot the new build (outside the repo); the previous snapshot is the old build.
python tools/update_symbols.py preflight
python tools/update_symbols.py snapshot --out <snapshots>

# Remap function symbols: old prologue pattern -> scan new .text, then audit
# every match (prologues are not unique) and relocate the flagged ones by hand.
python scripts/remap_symbols.py --old-exe <old Ravenswatch.exe> --update-symbols
python tools/update_symbols.py audit --old-exe <old> --new-exe <new> --old-symbols <old symbols.json>

# Relocate va data globals by locator vote, then capture locators on the new build.
python tools/va_locators.py recover --apply

# Rebuild the DB from the new exe's own .pdata, sync the named entries, verify.
./rsmm symbols gen
./rsmm rebuild-fn-patterns --force
python scripts/verify_symbol_resolve.py

# Struct fields that moved: diff displacements per struct family, then update
# the Lua SDK, the loader hooks and the spec mocks.
python tools/update_symbols.py fields --old-exe <old> --new-exe <new> --old-symbols <old> --family ...
```

**Why semantic pattern names matter.** The loader bakes pattern *names*
(`Sym::X_Pattern`) at build time. If those were address-derived
(`FUN_140391d30`) every patch would strand shipped DLLs. Instead the DB
carries stable semantic keys (`NamedEvent_Dispatch`, `Foo.parent` for
anchor parents); `sync_symbol_patterns.py` rebuilds them against the new
exe each regen, plus legacy `FUN_<oldaddr>` aliases so already-shipped
DLLs keep resolving.

**Delivery without an app release.** `data/function_patterns.json` is
committed for contributors; players get it as assets on the rolling `pattern-db`
GitHub release (`scripts/publish_pattern_db.sh`). Users pull it with
`rsmm update-data`, which the desktop app runs silently on startup —
so a republished DB reaches every install without a Tauri update. See
`src/rsmm/engine/data_update.py`.

The raw `.text` dumps (`text_section.bin`, `out_new/`) are gitignored —
they are copyrighted game bytes and must never be committed.

## What this enables

See:

- [Calling game functions](/reverse-engineering/calling-game-functions/) — the runtime API
  (`rsmm.resolve`, `rsmm.call`, memory r/w).
- [Seed + mapgen](/reverse-engineering/seed-mapgen/) — worked example: the seed surface.
- `examples/ExampleSeedPin/` — minimal mod that pins the run seed.

## What it doesn't enable

- **A general cooked-file re-encoder.** New items, heroes and enemies are
  cooked by the SDK content kinds from a shipped file; building an
  arbitrary class from scratch is still not supported.