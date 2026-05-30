# CLI Reference

All commands are run via the `rsmm` entry point:

```sh
./rsmm <command> [options]     # Linux / macOS
rsmm <command> [options]       # Windows
```

---

## Core commands

### `rsmm apply`

Install all enabled mods into the game directory. Backs up originals, applies patches, and merges `[[patch]]` blocks from `manifest.toml`.

```sh
./rsmm apply
./rsmm apply --game-dir /custom/path
```

Rollback: `./rsmm restore --all`

### `rsmm list`

Show installed mods and their status.

```sh
./rsmm list
```

### `rsmm doctor`

Health check. Verifies the asset map, game directory, mod structure, and loader DLL. Run this often.

```sh
./rsmm doctor
./rsmm doctor --mod MyMod          # Check a specific mod
```

### `rsmm run`

Launch Ravenswatch from the CLI.

```sh
./rsmm run
./rsmm run --game-dir /custom/path
```

### `rsmm watch`

Re-apply mods automatically whenever a file changes under `mods/`. Keeps running in the background.

```sh
./rsmm watch
```

### `rsmm restore`

Restore original game files. Reverses `rsmm apply`.

```sh
./rsmm restore --all               # Restore everything
./rsmm restore --mod MyMod         # Restore files for one mod
```

### `rsmm log`

Read the loader log file (`<game>/mods/_log.txt`).

```sh
./rsmm log                         # Full dump
./rsmm log -n 80                   # Last 80 lines
./rsmm log -f                      # Follow live (Ctrl-C to stop)
./rsmm log --grep lua              # Filter (case-insensitive)
./rsmm log --clear                 # Clear the log before a fresh launch
```

---

## Mod management

### `rsmm new <id>`

Scaffold a new mod directory:

```sh
./rsmm new MyMod
# Creates: mods/MyMod/manifest.toml
```

### `rsmm pack <id>`

Package a mod for distribution. Verifies no vanilla (unmodified game) bytes are included.

```sh
./rsmm pack MyMod                  # Writes dist/MyMod.zip
./rsmm pack MyMod --allow-vanilla  # Skip vanilla-byte check (personal backups only)
```

### `rsmm install-loader`

Copy the loader DLL (`dist/winhttp.dll`) into the game installation directory.

```sh
./rsmm install-loader
```

---

## Asset editing

### `rsmm decode <file>`

Structural dump of a cooked file (class table, sections, embedded strings).

```sh
./rsmm decode path/to/cooked.gen
./rsmm decode path/to/cooked.gen --raw   # Include hex payloads
```

### `rsmm uncook <file>`

Extract a cooked asset to an editable source-format file. Per-class schemas
are reversed-engineered incrementally (see `docs/RE_NOTES.md`); when the
schema isn't ready yet, `--raw` extracts section bytes directly so byte-level
mods are unblocked.

```sh
./rsmm uncook path/to/cooked.yqz                # uncook to source format (schema-dependent)
./rsmm uncook path/to/cooked.yqz --info         # print container header + class table
./rsmm uncook path/to/cooked.yqz --raw          # dump all section payloads to <name>.raw
./rsmm uncook path/to/cooked.yqz --raw --section 3 -o sec3.bin
```

### `rsmm cook --from <reference> <source>`

Pack a source asset into a cooked Ravenswatch file. Until per-class encoders
land, `--from <reference.yqz>` is required: the reference supplies the
container header + class table + version. `--raw` substitutes the input
bytes verbatim as section payload, giving a byte-level edit path today.

```sh
# Round-trip section 3 byte-identically:
./rsmm uncook --raw --section 3 ref.yqz -o sec3.bin
./rsmm cook   --raw --from ref.yqz --section 3 sec3.bin -o out.yqz

# Once schemas land, cook from source format:
./rsmm cook --from ref.yqz model.gltf -o out.yqz
```

### `rsmm texture`

Swap a texture by donor reference.

```sh
./rsmm texture --list                              # List all textures
./rsmm texture --list --grep Hero_Romeo           # Search
./rsmm texture --mod-id MyMod                      \
    'Ui/path/to/target.dxt=Ui/path/to/donor.dxt'  # Assign
./rsmm apply                                       # Apply
```

### `rsmm stat`

Edit numeric game values (globals, modifiers, camp difficulty).

```sh
./rsmm stat --list                                 # List all stats (143 globals + 19 modifiers + 6 camp bands)
./rsmm stat --list --grep Bleed                   # Search
./rsmm stat --mod-id LongerStatusEffects           \
    Bleed_Duration_Value=10                        \
    Ignite_Duration_Value=11                       \
    Easy:min=5 Easy:max=10                         # Assign
./rsmm apply                                       # Apply
```

Syntax: `<short_name>[:field]=<value>`. Multi-field classes use the `:field` suffix.

### `rsmm text`

Override translation strings.

```sh
./rsmm text --list Common --lang EN                # List keys
./rsmm text --list Common --grep Menu_            # Search
./rsmm text --mod-id Relabel                       \
    'Common~EN:Menu_Discord=Mods'                  # Assign
./rsmm apply                                       # Apply
```

Languages: `EN`, `JA`, `KO`, `RU`, `ES`, `DE`, `PL`, `FR`, `IT`, `PT-BR`, `ZH-S`, `ZH-T`, `RO`.

### `rsmm url`

Redirect main-menu URLs.

```sh
./rsmm url --list                                  # List all URLs
./rsmm url --mod-id MyHub                          \
    DiscordUrl=https://my-mods-site.example/       # Assign
./rsmm apply                                       # Apply
```

### `rsmm menu-button`

Add a "Mods" entry to the title menu.

```sh
./rsmm menu-button
```

### `rsmm social-tab`

Add a Mods tab to the in-game Social book.

```sh
./rsmm social-tab
```

### `rsmm mods-list`

Ship a Mods_List cooked entity for the social tab.

```sh
./rsmm mods-list
```

---

## Debugging

### `rsmm doctor`

See [Core commands](#core-commands).

### `rsmm trace <id>`

Run a specific mod with `RSMM_TRACE=1` and surface the log output inline.

```sh
./rsmm trace MyMod
```

### `rsmm diff <id>`

Show which cooked files a mod would change (dry-run).

```sh
./rsmm diff MyMod
```

### `rsmm decode <file>`

See [Asset editing](#asset-editing).

---

## Common workflows

| Goal | Commands |
|---|---|
| First-time setup | `./rsmm doctor` |
| Install all mods | `./rsmm apply` |
| Iterate on a mod | `./rsmm watch` (runs in background) |
| Package for sharing | `./rsmm pack MyMod` |
| Roll back everything | `./rsmm restore --all` |
| Launch the game | `./rsmm run` |

---

## Global options

| Flag | Description |
|---|---|
| `--game-dir <path>` | Custom Ravenswatch installation path |
| `--help` | Show help for any command |
| `--version` | Show RSMM version |
