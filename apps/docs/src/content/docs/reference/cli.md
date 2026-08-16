---
title: CLI reference
description: Every rsmm subcommand and what it does.
---

All commands are run via the `rsmm` entry point:

```sh
./rsmm <command> [options]     # Linux
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

Health check, and the repair path for what it finds. Run this often — it is the
first thing to try when something "just doesn't work".

```sh
./rsmm doctor                      # report only (never writes)
./rsmm doctor --fix                # run the safe repairs, then re-check
./rsmm doctor --fix --force        # also run destructive repairs
./rsmm doctor --only loader        # one section; --only list names them all
./rsmm doctor --json               # machine-readable findings
```

Findings carry a stable `code` and, where one exists, the exact rsmm command
that repairs them. `--fix` runs those repairs and then re-runs every check, so a
repair is only reported as fixed when the check actually goes green.

| Flag | Meaning |
|------|---------|
| `--fix` | Run each finding's automated repair (`apply`, `install-loader`, `rebuild-asset-map`, `update-data`). Repairs are ordinary rsmm commands — doctor never reimplements one. |
| `--force` | With `--fix`, also run repairs that roll the install back or delete installed files (`restore --all`). |
| `--only CHECK` | Restrict to named checks; repeatable. `--only list` prints them. |
| `--json` | Structured report: per-finding kind, code, detail, and whether a repair is automatic. |
| `--game-dir` | Point at a non-default install. |

Plain `doctor` is read-only on purpose: a health check that silently rewrites a
game install on every run is a footgun, so repairs are opt-in.

What it covers: game install reachable and writable, asset map freshness, game
version drift, the loader (DLL bytes by hash, the disk-loaded Lua SDK under
`<game>/rsmm/lib`, the planted pattern DB, dangerous feature flags left armed,
and — on Proton — whether Steam's launch options still carry the
`WINEDLLOVERRIDES` the loader needs), mod manifests and asset paths, raw-file
and `[[patch]]` conflicts, the dependency graph, applier state versus what is
actually on disk, `UsedRscList.ot` record alignment, and recent crash dumps.

:::tip
A planted `winhttp.dll` is only half an install. The Lua SDK and pattern DB are
loaded from `<game>/rsmm/`, and a Steam update replaces the DLL while deleting
that tree — which looks exactly like "the loader is broken". Doctor checks all
three.
:::

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

### `rsmm overlay`

Read the live HUD data a mod publishes. Overlays are **declared by mods** (an
`[overlay]` block in `manifest.toml`) and filled at runtime with
`R.overlay.publish` — the client hardcodes none of them.

```sh
./rsmm overlay                     # every installed mod that declares one
./rsmm overlay damage-meter        # that mod's board
./rsmm overlay damage-meter -w     # live, e.g. on a second monitor
./rsmm overlay damage-meter --json # machine-readable
```

Columns, sorting and the highlighted row come from the declaration, so the
terminal view and the desktop app's overlay window show the same thing.

---

## Mod management

### `rsmm new <id>`

Scaffold a new mod directory:

```sh
./rsmm new MyMod
# Creates: mods/MyMod/manifest.toml

./rsmm new MyMod --kind item        # also seeds a [[content]] block
```

`--kind` takes `item`, `talent`, `enemy`, `boss`, `map` or `hero`. Kinds that
aren't confirmed are scaffolded with `experimental = true` and `enabled = false`.

For `--kind item` the block is read out of the base you clone rather than
templated — its icon, rarity and every patchable value field with its true
current value, so the scaffold applies without hand-editing:

```sh
./rsmm new IronCrabHide --kind item --base Common/Armor_Per_Object \
    --name "Iron Crab Hide" --desc "Bonus armor per rare object."
```

| Flag | Meaning |
|------|---------|
| `--base ID` | Vanilla id to clone. Bare (`Armor_Per_Object`) or rarity-qualified (`Common/Armor_Per_Object`). Omit it at a terminal to get a searchable picker. |
| `--name TEXT` | Display name for the mod and its content. |
| `--desc TEXT` | Description shown in-game. |
| `--icon ID` | Vanilla icon stem (`rsmm items icons`) or `assets/<file>.png`. Defaults to the base's own icon. |
| `--rarity R` | `Common`, `Rare`, `Epic`, `Legendary`, `Cursed` or `Powerups`. Defaults to the base's rarity. |

See [Custom items](/guides/custom-items/) for the full walkthrough.

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