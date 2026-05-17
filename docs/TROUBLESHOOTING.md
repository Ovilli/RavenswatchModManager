Troubleshooting
===============

Common issues and quick fixes.

Loader not starting
- Ensure the native loader binary is built and placed alongside the game executable.
- Check loader logs in the game directory.

Mods not applying
- Verify `manifest.toml` `id` and paths.
- Run `python -m rsmm.cli.doctor` for diagnostics.

Merge conflicts or asset collisions
- Inspect `mods/_merged/asset_map.json` and `asset_map.csv` for duplicates.
- Resolve by renaming or adjusting manifests.

Still stuck
- Open an issue with reproduction steps and attach logs.
