# Mod Authoring Guide

This guide covers everything from scaffolding a mod to shipping a finished `.zip`. For CLI command details, see the [CLI Reference](CLI_USAGE.md).

---

## Quick start

```sh
# Scaffold a mod
./rsmm new MyMod

# Verify it's healthy
./rsmm doctor

# Install into the game
./rsmm apply

# Launch the game
./rsmm run

# Iterate with auto-reapply
./rsmm watch              # runs in background; reapplies on every change

# Roll back when done
./rsmm restore --all

# Package for sharing
./rsmm pack MyMod         # writes dist/MyMod.zip
```

---

## Two ways to write a mod

### 1. Drop cooked files (raw)

Mirror decoded paths under `assets/`. Full control, byte-for-byte. One mod owns each file.

### 2. Author with `[[patch]]` blocks (recommended)

Write declarative blocks in `manifest.toml` for stats, text, URLs, and textures. The applier composes every mod's patches into a single cooked file per target. Two mods touching *different* fields of the same file both take effect; conflicts on the *same* field resolve by `load_order` (lower = applies first; later wins on overlap).

Example using the Python SDK:

```python
# mods/MyMod/build.py
from rsmm import sdk

with sdk.Mod("MyMod", author="me", load_order=50) as m:
    m.stat("Bleed_Duration_Value", value=10)
    m.stat("Easy", min=5, max=10)
    m.text("Common", lang="EN", key="Menu_Discord", value="Mods")
    m.url("DiscordUrl", "https://example.com")
    m.texture("hero.romeo.portrait_active",
              donor="hero.sunwukong.portrait_active")
```

Run `python3 mods/MyMod/build.py` to emit `manifest.toml`. Friendly aliases (`hero.<name>.portrait_<state>`) hide the cooked-path lookups.

---

## Mod layout

```
mods/MyMod/
    manifest.toml              # Required: id, name, version, author
    assets/                    # Mirrors decoded paths from data/asset_map.csv
        <decoded-path>/<file>
    _root/                     # Optional: top-level overrides (outside _Cooking/)
        DarkTalesResources/
            ApplicationSettings.ot
    init.lua                   # Optional: Lua script run by the loader DLL
    build.py                   # Optional: Python SDK build script
    on_disable.py              # Optional: cleanup hook when mod is disabled
```

### manifest.toml

```toml
[mod]
id          = "MyMod"
name        = "My Mod"
version     = "1.0.0"
author      = "you"
description = "what it does"
enabled     = true
```

### on_disable.py (optional)

Place next to `manifest.toml`. Fires from `./rsmm apply` when the mod flips `enabled = true → false`. Subprocess with 30s timeout; receives `RSMM_GAME_DIR`, `RSMM_COOKING`, `RSMM_MOD_DIR` env vars.

Use for cleanup the loader DLL can't do at apply time — clearing settings keys, deleting profile caches, etc.

See `mods/ExampleSeedPin/on_disable.py` for a canonical example.

### ConsoleRuntime / dev_mode

The bundled `mods/ConsoleRuntime/` mod ships with a `dev_mode` flag in its `manifest.toml`. Off by default. When `dev_mode = true`, ConsoleRuntime registers `/eval`, which executes arbitrary Lua inside the game process.

Toggle: edit `mods/ConsoleRuntime/manifest.toml`, set `dev_mode = true`, then `./rsmm apply` (or relaunch the game). Never ship a release with it on.

---

## Recipes

### Replace a cooked file (raw)

```sh
# Find the decoded path:
rg -i "hero.*portrait" data/asset_map.csv

# Copy your file in:
cp /path/to/donor.dxt \
   mods/MyMod/assets/Ui/BookMenu/Heroes/UI_HeroPortrait_Romeo_Active.png.Texture.dxt

# Apply
./rsmm apply
```

### Texture swap (donor reference)

```sh
./rsmm texture --list --grep Hero_Romeo
./rsmm texture --mod-id RomeoIsMonkey \
    'Ui/BookMenu/Heroes/UI_HeroPortrait_Romeo_Active.png.Texture.dxt=Ui/BookMenu/Heroes/UI_HeroPortrait_SunWukong_Active.png.Texture.dxt'
./rsmm apply
```

Donor-swap only. PNG → cooked texture cooker needs the `oCTexture` container RE'd (see [Roadmap](ROADMAP.md)).

### Numeric balance / modifier / camp difficulty

```sh
./rsmm stat --list                    # See all available stats
./rsmm stat --list --grep Bleed       # Search
./rsmm stat --mod-id LongerStatusEffects \
    Bleed_Duration_Value=10 \
    Ignite_Duration_Value=11 \
    Easy:min=5 Easy:max=10
./rsmm apply
```

### Translation strings

```sh
./rsmm text --list Common --lang EN
./rsmm text --list Common --grep Menu_
./rsmm text --mod-id Relabel 'Common~EN:Menu_Discord=Mods'
./rsmm apply
```

Languages: `EN JA KO RU ES DE PL FR IT PT-BR ZH-S ZH-T RO`.

### Main-menu URLs

```sh
./rsmm url --list
./rsmm url --mod-id MyHub DiscordUrl=https://my-mods-site.example/
./rsmm apply
```

### In-game UI tweaks

```sh
./rsmm menu-button        # Add a "Mods" entry to the title menu
./rsmm social-tab         # Add a Mods tab to the in-game Social book
./rsmm mods-list          # Ship a Mods_List entity for the social tab
```

### Lua-scripted mod

The loader DLL (`dist/winhttp.dll`) runs `init.lua` once per launch in a sandboxed `lua_State` per mod.

```sh
./rsmm install-loader     # Copy the DLL into the game install
```

Add to Steam launch options: `WINEDLLOVERRIDES="winhttp=n,b" %command%`.

Lua API exposed to mods:

```lua
-- Runtime
rsmm.log(msg)
rsmm.mod_dir()                       -- this mod's directory
rsmm.game_dir()                      -- absolute install dir
rsmm.is_in_main_menu()               -- bool
rsmm.list_mods()                     -- {id, name, version, author, enabled}[]
rsmm.encoded_path(decoded)           -- decoded -> encoded path
rsmm.decoded_path(encoded)           -- encoded -> decoded path
rsmm.register_asset_override(decoded, src_abs_path)
rsmm.commit()                        -- apply registered overrides
rsmm.on_event(name, fn)              -- "ready" | "exit"

-- Game function access (53k functions resolvable by name)
rsmm.resolve(name)                   -- "FUN_xxx" -> runtime VA
rsmm.call(target, "sig", ...)        -- invoke by signature
rsmm.module_base()                   -- Ravenswatch.exe image base
rsmm.read_u8/u16/u32/u64/f32/f64(va) -- raw memory read
rsmm.read_cstr(va, max)              -- read NUL-terminated string
rsmm.write_u8/u16/u32/u64/f32/f64(va, v)
```

See `mods/ExampleLuaMod/init.lua` and `mods/ExampleSeedPin/init.lua` for working examples. Full game-function API + caveats: [docs/_re/CALLING_GAME_FUNCTIONS.md](_re/CALLING_GAME_FUNCTIONS.md).

### Hot-reload (Lua iteration < 5 seconds)

Run `./rsmm watch` in a side terminal while the game runs. On any save under `mods/`:

1. Re-applies cooked overrides.
2. Syncs `manifest.toml` + `init.lua` into the game-dir `mods/<id>/`.
3. The loader polls those files every ~1 second, tears down the changed mod's `lua_State`, and re-runs `init.lua`.

Tweak a number, hit save, see the result in-game without restarting.

Watch the live log:

```sh
./rsmm log -f --grep "lua\|reload"
```

Expected output on a Lua-only edit:

```
[lua] ExampleSeedPin reload (init.lua changed)
[lua] ExampleSeedPin init OK
[SeedPin] forced seed = 12345 (enable=1) after 1 ticks
```

---

## Reading the loader log

The loader writes to `<game>/mods/_log.txt`. Read it from the repo:

```sh
./rsmm log              # Full dump
./rsmm log -n 80        # Last 80 lines
./rsmm log -f           # Follow live (Ctrl-C to stop)
./rsmm log --grep lua   # Filter (case-insensitive)
./rsmm log --clear      # Clear before a fresh launch
```

Lua errors print as `[lua] <mod-id> ...`; `rsmm.log("msg")` calls land in the same file.

---

## Don't ship vanilla bytes

`rsmm pack <id>` hashes every file against the original cooked asset. If any file is byte-identical to the original, pack **refuses** — shipping unmodified game bytes is redistribution of copyrighted game content, not a mod.

```
$ ./rsmm pack MyMod
refusing to pack MyMod: contains files byte-identical to original game assets ...
  assets/Ui/BookMenu/Heroes/UI_HeroPortrait_Romeo_Active.png.Texture.dxt  (matches original cooked asset)
```

Fix: replace the listed files with your own modified bytes. `--allow-vanilla` bypasses the check for personal backup zips only.

The `data/uncooked/` mirror is git-ignored for the same reason — it exists for local reference only (see [Uncooked Assets](UNCOOKED_ASSETS.md)).

---

## Load order

When two mods override the same encoded path, the applier keeps the **later mod by alphabetical id** and warns. Explicit load-order control will come with the in-game UI. If order matters now, encode it: `10_Patch`, `20_Skins`, ...

---

## What you can't do yet

- **PNG → cooked texture** — The `oCTexture` container is custom, not plain DDS.
- **Edit hero/enemy/item gameplay stats** (HP, damage, move speed) — Per-entity schemas need more RE work.
- **New heroes/enemies/items** — Needs the text-`.ot` → binary-`.gen` re-encoder.
- **New 3D meshes** — No partial cooker for `oCGeometry`.
- **Engine event hooks** (OnDamage, OnSpawn) — MinHook targets were pruned due to anti-tamper.

Note: you *can* call any of 53k game functions from Lua today via `rsmm.call` — calling alone covers seed pinning, stat reads, save inspection, and forced option overrides. You just can't intercept them yet.

See [docs/INTERNALS.md](INTERNALS.md) for the engine notes that ground all of the above, and [docs/ROADMAP.md](ROADMAP.md) for open work.

---

## Cooked-file inspector

```sh
./rsmm decode <path-to-cooked-file>       # Structural dump
./rsmm decode <path> --raw                # Include hex payloads
```

Parses the class table + section structure. Won't fully decode per-class property bodies (schemas live in `Ravenswatch.exe`) but prints enough to identify what you'd be modifying.
