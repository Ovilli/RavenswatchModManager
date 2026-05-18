Mod Authoring
==============

Guidelines for creating mods compatible with RSMM.

Manifest
- Each mod should include a `manifest.toml` at its root.
- Required fields: `id`, `name`, `version`, `author`.

Assets
- Place assets under `assets/` with vendor folders like `GlobalValues`, `Ui`, etc.
- Observe the game's expected folder structure when providing definitions.

Examples
- See `mods/ExampleSdkMod/` for a minimal example.

Packaging
- Use the CLI `build` command or include a `build.py` to produce distributable archives.

Deactivation hook (`on_disable.py`)
- Optional. Place `on_disable.py` next to `manifest.toml`.
- Fires from `./rsmm apply` when the mod flips `enabled = true` -> `enabled = false` (tracked in `<cooking>/.rsmm_state.json` -> `enabled_mods`).
- Subprocess; 30s timeout; stdout printed indented under the apply log.
- Env: `RSMM_GAME_DIR`, `RSMM_COOKING`, `RSMM_MOD_DIR`.
- Use for cleanup the loader DLL can't do at apply time — clearing settings keys the mod wrote at runtime, deleting profile caches, etc. `mods/ExampleSeedPin/on_disable.py` is the canonical example: it strips `[Debug] Forced seed=` from `_Save/GameSettings.ini` so the seed unpins when the mod is disabled.

ConsoleRuntime / dev_mode
- The bundled `mods/ConsoleRuntime/` mod ships with a `dev_mode` flag in its `manifest.toml`. Off by default.
- When `dev_mode = true`, ConsoleRuntime additionally registers `/eval`, which executes arbitrary Lua inside the game process — anyone who can write `<game>/mods/_console.txt` then has full code execution. Useful for mod development; never ship a release with it on.
- Toggle: edit `mods/ConsoleRuntime/manifest.toml`, set `dev_mode = true`, then `./rsmm apply` (or relaunch the game).
