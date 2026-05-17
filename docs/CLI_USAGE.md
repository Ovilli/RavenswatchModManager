CLI Usage
=========

Overview of `rsmm` CLI tools found in `rsmm/cli/`.

Common commands
- `merge` — combine multiple mods into a single merged mod (see `rsmm/cli/merge.py`).
- `apply_mods` — apply mods to a target directory.
- `build` — helper to build packages or test assets.
- `lint` — run linters over mods and manifests.
- `doctor` — run sanity checks and diagnostics.

Example: build and apply mods

```bash
python -m rsmm.cli.merge --source mods/ --out mods/_merged/
python -m rsmm.cli.apply_mods --mod mods/_merged/ --target game_directory/
```

For detailed flags, open the command module in `rsmm/cli/` and run `--help`.
