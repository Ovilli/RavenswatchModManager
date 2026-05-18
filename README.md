# Ravenswatch Mod Manager (RSMM)

A script-based mod manager for **Ravenswatch** (OEngine, Steam). Mods
are folders under `mods/`; one CLI installs them; engine internals
stay hidden.

## Status

**v1 (cooked asset overrides) — working.** Verified on Linux + Steam
+ Proton. Confirmed end-to-end by replacing a hero portrait in-game.

**v2 (in-game UI, Lua-scripted mods) — partial.** Lua scripting via
the `winhttp.dll` proxy is online; engine event hooks (frame, damage,
spawn) are deferred. See `docs/ROADMAP.md`.

## Quick start

```sh
./rsmm build               # asset map + loader DLL + merge + apply
./rsmm doctor              # check everything is healthy
./rsmm run                 # launch Ravenswatch
./rsmm gui                 # browser-based mod manager (game-styled, no CLI)
# while iterating:
./rsmm watch               # auto-reapply on every mods/ change
# rollback:
./rsmm restore --all
```

Day-to-day:

```sh
./rsmm list                  # show installed mods
./rsmm apply                 # install mods/ into the game (auto-merges patches)
./rsmm new MyMod             # scaffold mods/MyMod/
./rsmm pack MyMod            # bundle into dist/MyMod.zip for sharing
./rsmm doctor                # health check (run this often)
```

Default game dir:
`~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/Ravenswatch`.
Pass `--game-dir /custom/path` to any subcommand that needs it.

## What you can mod today

| | Subcommand |
|---|---|
| Swap any cooked file (textures, audio banks, meshes, …) | `rsmm apply` (drop file under `mods/<id>/assets/`) |
| Swap textures by donor reference | `rsmm texture` |
| Patch balance / modifier / camp-difficulty floats | `rsmm stat` |
| Override translation strings (14 langs) | `rsmm text` |
| Redirect main-menu URLs | `rsmm url` |
| Rename the Discord menu button to "Mods" | `rsmm menu-button` |
| Add a Mods tab to the in-game Social book | `rsmm social-tab` |
| Ship a fresh cooked entity at a new path | `rsmm mods-list` |
| Author script behaviour in Lua | drop `init.lua` next to `manifest.toml`, run with the loader DLL |
| Call any of 53k game functions from Lua | `rsmm.call("name", "sig", ...)` — see `docs/_re/CALLING_GAME_FUNCTIONS.md` |
| Read / write process memory from Lua | `rsmm.read_u32(va)` / `rsmm.write_u32(va, v)` |
| Pin the run RNG seed (speedruns) | `mods/ExampleSeedPin/` — uses `rsmm.call` on built-in Forced-seed option |
| Author a mod in Python (SDK)   | `from rsmm import sdk; with sdk.Mod("Id") as m: m.stat(...)` |
| Merge conflicting mods         | `[[patch]]` blocks in `manifest.toml` — `./rsmm apply` field-merges |
| Live re-apply on file change   | `./rsmm watch` |
| System health check            | `./rsmm doctor` |
| Refuse shipping vanilla bytes  | `./rsmm pack <id>` SHA1s assets vs originals; bypass: `--allow-vanilla` |
| Browse uncooked game assets    | `python3 scripts/extract_uncooked.py` → `data/uncooked/` (3.2 GB, gitignored) |

Recipes for each in `docs/MODDING.md`.

## Writing a mod

```
mods/MyMod/
    manifest.toml            # id, name, version, author, enabled
    assets/
        <decoded-path>       # mirrors a path from data/asset_map.csv
    init.lua                 # optional, runs in loader DLL
    _root/                   # optional top-level overrides
        DarkTalesResources/
            ApplicationSettings.ot
```

Scaffold one:

```sh
./rsmm new MyMod
```

Distribute it:

```sh
./rsmm pack MyMod           # writes dist/MyMod.zip
```

Full guide: `docs/MODDING.md`.

## How it works (one paragraph)

Ravenswatch loads every cooked asset from
`<install>/DarkTalesResources/_Cooking/<encoded>` where `<encoded>` is
the asset's name run through a fixed substitution cipher
(`src/rsmm/engine/cipher.py`). The cooked bytes carry no checksum or
signature; any byte-compatible file at the encoded path is accepted by
the engine. `rsmm apply` walks `mods/`, translates each mod file's
**decoded** path to its **encoded** path under `_Cooking/`, backs up
the original, and drops the mod file in place. No DLL injection
required for asset overrides.

The loader DLL (`dist/winhttp.dll`, optional) ships as a `winhttp`
proxy and adds Lua scripting per mod. Install it via
`./rsmm install-loader`. Steam launch options:
`WINEDLLOVERRIDES="winhttp=n,b" %command%`.

Deep RE notes: `docs/INTERNALS.md`. Open work: `docs/ROADMAP.md`.

## Repository layout

```
rsmm                        single CLI entry — every workflow starts here
README.md                   this file
docs/
    MODDING.md              how-to for mod authors
    UNCOOKED_ASSETS.md      data/uncooked/ extract pipeline + pack guard
    INTERNALS.md            engine RE notes (formats, cipher, schemas)
    ROADMAP.md              open work toward the v2 surface
    _re/                    Ghidra project + scripts (54k decompiled functions)
        PIPELINE.md         how to regen after a game patch
        CALLING_GAME_FUNCTIONS.md  rsmm.resolve / rsmm.call / memory API
        SEED_MAPGEN.md      worked example: forced-seed surface
        out/                symbols.json, strings.json, decompiled_all/, …
data/
    asset_map.json          encoded -> decoded cooked-asset index
    asset_map.csv           same, csv form
    function_patterns.json  pattern signatures for rsmm.resolve (gitignored)
    uncooked/               readable asset mirror (gitignored, 3.2 GB)
mods/                       installed mods (one folder per id)
    ExampleSeedPin/         calls into game's Forced-seed option from Lua
dist/                       built winhttp.dll + packed mod zips
scripts/                    host-Python helpers
    extract_uncooked.py     cooked -> readable mirror (decodes textures)
    decode_gen_sidecars.py  .gen -> .gen.txt structural dumps
    gen_function_patterns.py
                            symbols.json + exe bytes -> pattern signatures
    test_pattern_resolve.py validate pattern DB
src/
    rsmm/                   Python package
        cli/                subcommand modules (apply, stat, texture, …)
        engine/             cipher, decoder, asset map (internals)
        dev/                RE / dev-only scripts (class_diff, trace_parse, …)
    loader/                 native DLL source (winhttp proxy + Lua VM)
        src/fn_resolver.cpp pattern scanner: name -> runtime VA
        src/fn_call.cpp     Win x64 ABI generic invoker
```

Everything modders touch lives at the top: `rsmm`, `mods/`, `docs/`.
Engine internals stay in `src/rsmm/engine/` and are imported, not
called directly.

## Legal / Scope

RSMM is a **single-player** modding tool. It does not bypass any
anti-cheat, does not patch or hide itself from server-side telemetry,
and is not intended to confer an advantage in any online competitive
context. The loader runs purely in-process and only modifies cooked
assets and scripted behaviour on the local machine; multiplayer
sessions remain at the mercy of the host's own integrity checks. **A
legitimate Steam copy of Ravenswatch is required** — RSMM ships no
game content and cannot run without an installed game.

`data/asset_map.json` and `data/asset_map.csv` are **derived metadata**
(encoded-path ↔ decoded-path index) reconstructed from the running
game; they contain no Ravenswatch art, audio, code, or text. They are
no more redistributable game content than a file listing of your `_Cooking/`
directory would be. Mods authored with RSMM are the modder's own work
and inherit the modder's chosen license.

## License

RSMM is released under the MIT License — see [`LICENSE`](LICENSE).

The loader DLL bundles third-party code (MinHook, Dear ImGui, Lua 5.4);
their license texts are reproduced in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
