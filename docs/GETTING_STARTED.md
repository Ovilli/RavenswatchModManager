Getting Started
===============

Quick steps to use Ravenswatch Mod Manager (RSMM).

1. Install the loader or use the packaged installer (see Installation guide).
2. Place mods in the `mods/` directory. Each mod should include `manifest.toml`.
3. Use the CLI to apply mods and build merged outputs: see CLI Usage.
4. Launch the game with the loader present; the loader will load merged mods from `_merged`.

Example (build a merged mod):

1. `python -m rsmm.cli.merge --source mods/ --out mods/_merged/`
2. Verify `mods/_merged/manifest.toml` and `mods/_merged/assets`.

For authors: see Mod Authoring for manifest and asset conventions.
