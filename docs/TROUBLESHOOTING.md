# Troubleshooting

Common issues and quick fixes.

> **First step:** always run `./rsmm doctor` — it catches most setup problems automatically.

## Loader not starting

- Ensure the loader DLL (`winhttp.dll`) is built and placed alongside `Ravenswatch.exe`.
- Check the loader log: `./rsmm log`
- Verify Steam launch options include `WINEDLLOVERRIDES="winhttp=n,b" %command%` (Proton/Linux).

## Mods not applying

- Run `./rsmm doctor` for diagnostics.
- Verify `manifest.toml` has `enabled = true`.
- Check `mods/_merged/asset_map.json` for duplicate entries.

## Merge conflicts or asset collisions

- Inspect `mods/_merged/asset_map.json` and `asset_map.csv` for duplicates.
- Resolve by renaming or adjusting manifests.

## Still stuck

Open an issue at [github.com/Ovilli/RavenswatchModManager/issues](https://github.com/Ovilli/RavenswatchModManager/issues) with:
- Your OS and Ravenswatch version
- Steps to reproduce
- Output of `./rsmm doctor`
- Any relevant log output

---

For more detailed setup help, see [Installation](INSTALLATION.md).
