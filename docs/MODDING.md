# Writing a Ravenswatch mod

Author flow:

```sh
./rsmm new MyMod                  # scaffold mods/MyMod
# ... drop files / edit manifest / write init.lua / write build.py ...
./rsmm doctor                     # verify everything is healthy
./rsmm apply                      # install into the game (auto-merges patches)
./rsmm run                        # launch the game
./rsmm restore --all              # roll back when done
./rsmm pack MyMod                 # zip into dist/MyMod.zip to share
```

Iterate quickly with `./rsmm watch` running in another terminal — it
re-applies mods on every change under `mods/`.

## Two ways to write a mod

**1. Drop cooked files** (raw): mirror decoded paths under `assets/`.
   Full control, byte-for-byte. One mod owns each file.

**2. Author with `[[patch]]` blocks** (recommended for stats / text /
   URLs / textures): write declarative blocks in `manifest.toml`. The
   applier composes every mod's patches into a single coherent cooked
   file per target. Two mods touching *different* fields of the same
   file both take effect; conflicts on the *same* field resolve by
   `load_order` (lower = applies first; later wins on overlap).

Authoring the second way is much easier with the Python SDK:

```python
# mods/MyMod/build.py
from rsmm import sdk

with sdk.Mod("MyMod", author="me", load_order=50) as m:
    m.stat("Bleed_Duration_Value", value=10)        # global float
    m.stat("Easy", min=5, max=10)                   # camp difficulty
    m.text("Common", lang="EN", key="Menu_Discord", value="Mods")
    m.url("DiscordUrl", "https://example.com")
    m.texture("hero.romeo.portrait_active",
              donor="hero.sunwukong.portrait_active")
```

Run `python3 mods/MyMod/build.py` to emit `manifest.toml`. Friendly
aliases (`hero.<name>.portrait_<state>`) hide the cooked-path lookups.
Working example: `mods/ExampleSdkMod/build.py`.

## Mod layout

```
mods/MyMod/
    manifest.toml             # required
    assets/
        <decoded-path>/<file> # mirrors a path from data/asset_map.csv
    _root/                    # optional: top-level (non-_Cooking) overrides
        DarkTalesResources/
            ApplicationSettings.ot
    init.lua                  # optional: Lua executed by the loader DLL
```

`manifest.toml`:

```toml
[mod]
id          = "MyMod"
name        = "My Mod"
version     = "1.0.0"
author      = "you"
description = "what it does"
enabled     = true
```

## Recipes

### Replace a cooked file (raw)

```sh
./rsmm new MyMod
# Find the decoded path:
rg -i "hero.*portrait" data/asset_map.csv
# Copy a donor file in:
cp /path/to/donor.dxt \
   mods/MyMod/assets/Ui/BookMenu/Heroes/UI_HeroPortrait_Romeo_Active.png.Texture.dxt
./rsmm apply
```

### Texture swap (donor reference)

```sh
./rsmm texture --list --grep Hero_Romeo
./rsmm texture --mod-id RomeoIsMonkey \
    'Ui/BookMenu/Heroes/UI_HeroPortrait_Romeo_Active.png.Texture.dxt=Ui/BookMenu/Heroes/UI_HeroPortrait_SunWukong_Active.png.Texture.dxt'
./rsmm apply
```

Donor-swap only. PNG -> cooked texture cooker needs the `oCTexture`
container RE'd; see `docs/ROADMAP.md`.

### Numeric balance / modifier / camp difficulty

```sh
./rsmm stat --list                 # 143 globals + 19 modifiers + 6 camp bands
./rsmm stat --list --grep Bleed
./rsmm stat --mod-id LongerStatusEffects \
    Bleed_Duration_Value=10 \
    Ignite_Duration_Value=11 \
    Easy:min=5 Easy:max=10
./rsmm apply
```

Syntax: `<short_name>[:field]=<value>`. Multi-field classes use the
`:field` suffix.

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
./rsmm menu-button        # add a "Mods" entry to the title menu
./rsmm social-tab         # add a Mods tab to the in-game Social book
./rsmm mods-list          # ship a Mods_List cooked entity for the social tab
```

### Lua-scripted mod

The loader DLL (`dist/winhttp.dll`) runs `init.lua` once per launch in
a sandboxed `lua_State` per mod. Install it once:

```sh
./rsmm install-loader     # copies dist/winhttp.dll into the game install
```

Add to Steam launch options:
`WINEDLLOVERRIDES="winhttp=n,b" %command%`.

Currently exposed `rsmm.*` API (see `src/loader/include/script_lua.h`
and `src/loader/src/script_lua.cpp`):

```lua
-- Mod runtime
rsmm.log(msg)
rsmm.mod_dir()                       -- this mod's directory
rsmm.game_dir()                      -- absolute install dir
rsmm.is_in_main_menu()               -- bool
rsmm.list_mods()                     -- {id, name, version, author, enabled}[]
rsmm.encoded_path(decoded)           -- decoded -> encoded, or nil
rsmm.decoded_path(encoded)           -- encoded -> decoded, or nil
rsmm.register_asset_override(decoded, src_abs_path)
rsmm.commit()                        -- apply registered overrides
rsmm.on_event(name, fn)              -- "ready" | "exit"

-- Game function access (53k functions resolvable by name)
rsmm.resolve(name)                   -- "FUN_xxx" -> runtime VA or nil
rsmm.call(target, "sig", ...)        -- invoke; sig chars: i u l f d p s v
rsmm.module_base()                   -- Ravenswatch.exe image base
rsmm.read_u8/u16/u32/u64/f32/f64(va) -- raw memory read
rsmm.read_cstr(va, max)              -- read NUL-terminated string
rsmm.write_u8/u16/u32/u64/f32/f64(va, v)
```

Working examples: `mods/ExampleLuaMod/init.lua`,
`mods/ExampleSeedPin/init.lua`. Full game-function API + caveats:
`docs/_re/CALLING_GAME_FUNCTIONS.md`.

### Hot-reload (Lua iteration < 5 s)

Run `./rsmm watch` in a side terminal while the game is running. On
any save under `mods/`, watch:

1. Re-applies cooked overrides (existing behavior).
2. Syncs each mod's `manifest.toml` + `init.lua` into the game-dir
   `mods/<id>/`.

The loader DLL polls those files every ~1 s, tears down the changed
mod's `lua_State`, re-runs `init.lua`, and replays the `ready` event.
Tweak a number, hit save, see the result in-game without restarting.

Watch the live log to confirm:
```sh
./rsmm log -f --grep "lua\|reload"
```

Expected stream on a Lua-only edit:
```
[lua] ExampleSeedPin reload (init.lua changed)
[lua] ExampleSeedPin init OK
[SeedPin] forced seed = 12345 (enable=1) after 1 ticks
```

### Reading the loader log

The loader writes to `<game>/mods/_log.txt`. Tail it from the repo:

```sh
./rsmm log              # full dump
./rsmm log -n 80        # last 80 lines
./rsmm log -f           # follow live (Ctrl-C to stop)
./rsmm log --grep lua   # filter (case-insensitive)
./rsmm log --clear      # truncate before a fresh launch
```

Lua errors print as `[lua] <mod-id> ...`; `rsmm.log("msg")` calls
land in the same file.

## Don't ship vanilla bytes

`rsmm pack <id>` SHA1s every file in `mods/<id>/assets/` and `_root/`
against the original cooked asset (and the `data/uncooked/` mirror if
present). If any file is byte-identical to the original game asset,
pack **refuses** — shipping unmodified game bytes is redistribution of
copyrighted Ravenswatch content, not a mod.

```
$ ./rsmm pack MyMod
refusing to pack MyMod: contains files byte-identical to original game assets ...
  assets/Ui/BookMenu/Heroes/UI_HeroPortrait_Romeo_Active.png.Texture.dxt  (matches original cooked asset)
```

Fix by replacing the listed files with your own modified bytes, or
deleting them. Authors must ship only their changes, never the
originals. `--allow-vanilla` bypasses the check, intended only for
personal backup zips that are never distributed publicly.

`data/uncooked/` is git-ignored for the same reason — extract is for
local development reference (see `scripts/extract_uncooked.py`).

## Load order

When two mods override the same encoded path, the applier currently
keeps the **later mod by alphabetical id** and warns. Explicit load-
order control will come with the in-game UI. If order matters now,
encode it: `10_Patch`, `20_Skins`, …

## What you can't do yet

- **PNG -> cooked texture.** The `oCTexture` container is custom
  oCTextSaver, not plain DDS. Cook needs container RE.
- **Edit hero / enemy / item gameplay stats** (HP / damage / move).
  The `*Definition` classes are registry pointers — real stats live
  in per-entity `oCEntitySettingsResource` bodies, which need
  per-component schema work.
- **New heroes / enemies / items.** Needs the general text-`.ot` ->
  binary-`.gen` re-encoder.
- **New 3D meshes.** `oCGeometry` is 200 B – 4 MB packed binary; no
  partial cooker.
- **Engine event hooks** (OnDamage, OnSpawn, frame). The MinHook
  engine intercepts that previously powered the in-game click pipeline
  were pruned; restoring them is the path forward for Lua gameplay
  hooks. Note: you *can* `rsmm.call` any of 53k functions today (see
  `docs/_re/CALLING_GAME_FUNCTIONS.md`) — you just can't intercept
  them. Calling alone covers seed pinning, stat reads, save inspection,
  forced option overrides.

See `docs/INTERNALS.md` for the engine + format notes that ground all
of the above, and `docs/ROADMAP.md` for the open work.

## Reference: cooked-file inspector

```sh
./rsmm decode <path-to-cooked-file>            # structural dump
./rsmm decode <path> --raw                     # include hex payloads
```

Parses the class table + section structure. Won't fully decode
per-class property bodies (no schemas yet) but prints enough to
identify what you'd be modifying.
