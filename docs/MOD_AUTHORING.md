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

ConsoleRuntime / dev_mode
- The bundled `mods/ConsoleRuntime/` mod ships with a `dev_mode` flag in its `manifest.toml`. Off by default.
- When `dev_mode = true`, ConsoleRuntime additionally registers `/eval`, which executes arbitrary Lua inside the game process — anyone who can write `<game>/mods/_console.txt` then has full code execution. Useful for mod development; never ship a release with it on.
- Toggle: edit `mods/ConsoleRuntime/manifest.toml`, set `dev_mode = true`, then `./rsmm apply` (or relaunch the game).
