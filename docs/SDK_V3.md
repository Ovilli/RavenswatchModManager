# RSMM SDK v3 — Design Spec

> Status: design + scaffold landed (2026-05-19). Schema-mining + TLS-injection
> are scaffolded but their RE / native work is open. See "Open work" at the
> bottom for what is still empirical.

## Goals

1. **Add new content** — items, enemies, bosses, maps, heroes — declared from a
   mod, materialized as cooked-asset writes by RSMM.
2. **Edit existing content** — every kind above, plus stats, text, URLs, menu
   buttons. Reuse the existing `[[patch]]` merge pipeline.
3. **Open extensibility** — third parties contribute new content kinds, CLI
   subcommands, or runtime services as Python entry-point plugins. Core stays
   stable; ecosystem grows out of tree.
4. **Crash-safe** — apply transaction is atomic; a boot canary detects a crashy
   mod and bisects on next launch; per-mod Lua errors never escape `pcall`.
5. **Programmer freedom** — `R.call` (53k fns), `R.hook` (after TLS injection
   lands), `R.read/write` memory primitives, event bus, scheduler.
6. **Survives game updates** — pattern-resolver already byte-pattern not VA;
   manifests declare `target_game_build`; mods address fns by name; schemas
   are versioned and auto-migrated.
7. **Localization, config, inter-mod APIs** — first-class. Wired through the
   SDK runtime, not bolted on per mod.
8. **Distribution** — open spec (`repo.json`), SHA256 + optional Ed25519
   signature. No central host required.

## Module map

```
src/rsmm/sdk/
  __init__.py         # public Python surface: `from rsmm import sdk; sdk.Mod(...)`
  api.py              # @sdk_export + version pin (rsmm.sdk.api.v1)
  health.py           # apply-canary + crash-history bisect
  transaction.py      # stage -> swap install pipeline
  config.py           # schema-driven per-mod config, generates UI rows
  i18n.py             # lang/<locale>.toml merge into text banks
  content.py          # R.content.register(kind, def) facade
  intermod.py         # R.api.expose / R.api.require
  plugins.py          # entry-point discovery, version-gated load
  repo.py             # repo.json schema + sign/verify (Ed25519)
  versioning.py       # game-build hash check + schema migrations
  kinds/              # one module per content kind
    items.py          # magical objects
    enemies.py
    bosses.py
    maps.py
    heroes.py
    _schema_mining.py # Ghidra-driven class-cohort schema extractor
```

Lua side (loader DLL):

```
src/loader/lua/
  rsmm.lua            # R = require "rsmm" — re-exports everything below
  rsmm/health.lua     # R.health (crash count, last_error)
  rsmm/config.lua     # R.config.get/set/on_change
  rsmm/i18n.lua       # R.i18n.t
  rsmm/api.lua        # R.api.expose/require
  rsmm/events.lua     # R.on / R.emit
  rsmm/schedule.lua   # R.schedule.{next_frame, after}
```

`rsmm.lua` is rebuilt by `rsmm build` from the Python side so the Lua API
declarations stay in lockstep with the Python registrations.

## Manifest v2

```toml
[mod]
id = "MyMod"
name = "My Mod"
version = "1.2.3"             # semver
author = "Me"
description = "..."
enabled = true

sdk_version = ">=3.0,<4"      # required SDK API
target_game_build = "1.2.3"   # what game version it was built for
load_order = 100              # tiebreak ordering
priority   = 0

[dependencies]
otheritempack = ">=1.0"

[provides]
api = "myapi"                 # what `R.api.require("myapi")` resolves to

[[patch]]                     # existing field-merge support
...

[[content]]                   # NEW: declarative content registration
kind   = "item"               # one of: item, enemy, boss, map, hero
id     = "FrostBlade"
source = "content/frost_blade.toml"
```

## Apply transaction

`rsmm apply` becomes two-phase:

1. **Stage**: every write goes to `<cooking>/.rsmm_stage/<encoded>`. Backups
   created next to originals as before. Nothing in `_Cooking/` proper is
   touched yet.
2. **Commit**: atomic rename of staged files into place (POSIX `os.rename`,
   `MoveFileExW` w/ `MOVEFILE_REPLACE_EXISTING` on Windows). On the first
   error mid-commit, every successful rename is rolled back from `.rsmm.bak`.

State writes are also staged. `.rsmm_state.json` is written to
`.rsmm_state.json.tmp` then renamed.

Power-loss safety: `rsmm apply` is restartable — staged-but-uncommitted
files are detected at startup and either committed (if a `COMMIT` marker
exists) or discarded.

## Boot canary

Loader DLL writes `<cooking>/.rsmm_boot.json` at `DllMain` with:

```json
{"started_at": 1716120000, "mods": ["A", "B", "C"], "last_step": "init"}
```

`last_step` is updated as each mod's `init.lua` runs:

```
init        -> per_mod:A -> per_mod:B -> per_mod:C -> ready
```

On clean shutdown, the file is deleted.

Next launch, `rsmm` reads any stale canary. If `last_step` is `per_mod:X`,
mod X is flagged. Three strikes (configurable) → mod auto-disabled and
moved to `crash_history` in `R.health`.

## `R.health` API

```lua
R.health.crash_count()          -- int, since SDK install
R.health.last_error()           -- string|nil
R.health.last_mod()             -- string|nil
R.health.disable("modid", "reason")
R.health.set_threshold(n)
```

`rsmm safe-mode` CLI: disables every mod with `crash_count >= threshold`
and runs apply.

`rsmm safe-mode --bisect` (planned): disable half, launch, repeat.

## Config

`mods/<id>/config_schema.toml`:

```toml
[fields.damage_mult]
type    = "float"
min     = 0.1
max     = 10.0
default = 1.0
label   = "Damage multiplier"

[fields.enable_effect]
type    = "bool"
default = true
```

`mods/<id>/config.toml` is generated/written by the user via the web UI or
`rsmm config <id> set damage_mult 2.5`. SDK API:

```lua
local cfg = R.config              -- bound to the calling mod
local mult = cfg.get("damage_mult")
cfg.on_change("damage_mult", function(new, old) ... end)
```

Validation errors at write-time → rejected with explicit message.

## i18n

`mods/<id>/lang/<locale>.toml`:

```toml
[strings]
title  = "Frost Blade"
desc   = "An icy weapon."
```

Locales: `EN, JA, KO, RU, ES, DE, PL, FR, IT, PT-BR, ZH-S, ZH-T` (game's
existing 12 user locales + the `RAW` QA pseudo-locale).

At apply time, RSMM merges strings into per-locale text-bank overrides,
keys namespaced as `RSMM_<modid>_<key>`.

Lua API:

```lua
R.i18n.t("title")               -- "Frost Blade"
R.i18n.t("hello", {name="X"})   -- substitution: "Hello, X"
```

Missing locale → fall back to `EN`. Missing key in `EN` → return the key
literally and log warning.

## Inter-mod API

```lua
-- producer
R.api.expose({
  spawn_item = function(id, pos) ... end,
  version    = "1.0.0",
})

-- consumer
local items = R.api.require("itempack", ">=1.0")
items.spawn_item("FrostBlade", player.pos)
```

`expose` is implicitly namespaced to the calling mod's `id`. `require`
returns a proxy that:

* `pcall`s every call so the producer mod's failure can't crash the
  consumer,
* checks the producer's `version` against the semver spec on every call
  (cheap; cached after first hit),
* returns the version reported by `provides.api` in the producer's
  manifest if set.

## Plugin registry

Third-party Python packages can register SDK extensions via PEP-621
entry points:

```toml
# their pyproject.toml
[project.entry-points."rsmm.plugins"]
my_pack = "my_pack.entry:register"
```

`register(api)` is called with an `rsmm.sdk.api.v1` namespace and may:

* declare new `R.content` kinds (via `api.content.register_kind(...)`),
* add CLI subcommands (`api.cli.register(name, fn)`),
* expose Lua-side modules (file copied to the loader's `lua/` dir).

Discovery: `importlib.metadata.entry_points(group="rsmm.plugins")`.
Each plugin declares `requires_api = ">=1.x,<2"`; unsatisfied plugins
are skipped with a warning.

## Content kinds

`R.content.register(kind, def)` (Lua) and `rsmm.sdk.content.register(...)`
(Python) both funnel into one Python pipeline. Per kind:

* `items` — magical-object registry entry + entity cooked file + text-bank
  keys + icon texture override.
* `enemies` — entity clone of a vanilla base enemy + AI controller + stat
  globals + spawn-table entry.
* `bosses` — same as enemies + boss-fight controller + arena patch.
* `maps` — biome entry into level list + tile/spawn-weight patch.
* `heroes` — entity + portraits + power tree + i18n keys + character-select
  slot patch.

Each kind module owns:

1. Its template `.gen` byte slice (extracted from a vanilla cooked file at
   build time, cached under `data/templates/<kind>/`).
2. A field-by-field patcher (id, name, stats, icon path, …) that emits a
   modified `.gen`.
3. The reverse-translation back into a decoded `mods/_merged/assets/...`
   tree consumed by `apply_mods.py`.

## Schema mining

`src/rsmm/sdk/kinds/_schema_mining.py` drives a Ghidra-headless pipeline:

1. For each class involved (e.g. `oCEntityCpntMagicalObjectSettings`),
   bucket every vanilla cooked file by body size and call `class_diff` to
   identify field offsets.
2. Cross-reference with strings from `docs/_re/out/strings.json` to label
   text-bank-key offsets.
3. Emit `data/schemas/<class>.json` consumed by `_schema_mining.encode()`.

This is an empirical RE task; it lands kind by kind. v3 ships with items
first, then enemies; bosses/maps/heroes are template-clone-only until
their schemas are mined.

## Distribution (`repo.json`)

A mod-repo index file any host can publish:

```json
{
  "schema": "rsmm.repo.v1",
  "name": "Ovilli's mods",
  "updated_at": "2026-05-19T00:00:00Z",
  "mods": [
    {
      "id": "FrostBlade",
      "version": "1.2.3",
      "sdk_version": ">=3.0,<4",
      "target_game_build": "1.2.3",
      "url": "https://example.com/FrostBlade-1.2.3.zip",
      "sha256": "...",
      "size": 12345,
      "sig": "...",          // optional Ed25519, base64
      "pubkey_id": "ovilli"  // matches a key in user's ~/.rsmm/keys/
    }
  ]
}
```

CLI:

```sh
rsmm repo add https://example.com/repo.json
rsmm install FrostBlade            # resolves to one of the registered repos
rsmm pack MyMod --sign keys/me     # writes dist/MyMod-1.2.3.zip + .sig
rsmm verify dist/FrostBlade.zip    # SHA256 + sig vs ~/.rsmm/keys/
```

Trust model:

* Unsigned: install proceeds with `WARN unsigned mod`.
* Signed by an unknown key: install proceeds with `WARN unknown signer
  (pubkey_id=...). Trust? [y/N]`.
* Signed by a known + trusted key: silent install.

No revocation list in v3 (out of scope). Users can hand-delete keys from
`~/.rsmm/keys/`.

## TLS-callback DLL injection (unlocks `R.hook`)

Goal: install our DLL before Ravenswatch.exe's entry-point runs, so
MinHook patches land before the AT integrity sweep.

* The `winhttp.dll` proxy is already loaded via `WINEDLLOVERRIDES=…n,b…`.
  That happens before `_DllMainCRTStartup` of the EXE, but the runtime is
  not yet initialized.
* TLS callback signature `PIMAGE_TLS_CALLBACK` runs once per process at
  `DLL_PROCESS_ATTACH`. By placing the MinHook initialization in a TLS
  callback inside our DLL, we run earlier than `DllMain`, which is enough
  to land hooks before the EXE's `main()` initializes anti-tamper.
* Gated by env var `RSMM_TLS_HOOK=1` during the trial period; default off.

Plumbing scaffold lives in `src/loader/src/tls_callback.cpp`.

## Versioning + game updates

* Loader writes the running EXE's SHA256 to
  `<cooking>/.rsmm_game_build.json` after a successful boot. Next apply
  compares — mismatch → warn + soft-disable mods that use raw VAs.
* `rsmm doctor` flags mods whose `target_game_build` differs from the
  current `.rsmm_game_build.json`.
* Each SDK-managed content def carries `schema_version`. On schema bump,
  migrations under `src/rsmm/sdk/kinds/<kind>/migrations/<from>_to_<to>.py`
  run at build time.

## Open work

* Schema mining for non-item kinds. Items first, then enemies, then the
  rest.
* TLS-callback hook reliability under Proton + Wine.
* `rsmm safe-mode --bisect` driver.
* In-game config panel (loader-side ImGui).
* Web GUI updates to surface health + config + i18n.

## Migration

* `manifest.toml` v1 still parses; v2 fields are all optional with sane
  defaults. No mod break.
* `apply_mods.py` keeps the same CLI surface; the staging dir is invisible
  to users.
* `R.hook` exposes "not supported" today and silently upgrades when
  TLS injection lands.
