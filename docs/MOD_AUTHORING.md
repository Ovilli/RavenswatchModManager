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
