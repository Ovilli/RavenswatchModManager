# Ravenswatch Mod Manager (RSMM)

A cross-platform mod manager for **Ravenswatch** (Steam, OEngine). Swap textures, tweak balance, edit translation strings, redirect URLs, and author Lua-scripted mods — all from one CLI.

## Quick start

```sh
git clone https://github.com/Ovilli/RavenswatchModManager.git
cd RavenswatchModManager
python3 -m venv .venv && source .venv/bin/activate && pip install -e .
./rsmm doctor
```

See the [Installation Guide](docs/INSTALLATION.md) for full setup on Linux and Windows.

## What you can do

| Capability | How |
|---|---|
| Swap textures, audio, meshes | `./rsmm apply` — drop files under `mods/<id>/assets/` |
| Edit balance numbers | `./rsmm stat` — 143 globals, 19 modifiers, 6 camp tiers |
| Override translations | `./rsmm text` — 14 languages |
| Redirect main-menu URLs | `./rsmm url` |
| Add a "Mods" menu button | `./rsmm menu-button` |
| Add a Mods in-game tab | `./rsmm social-tab` |
| Author behaviour in Lua | Drop `init.lua` + loader DLL; call 53k game functions |
| Merge conflicting mods | `[[patch]]` blocks in `manifest.toml` — field-level merge |
| Live re-apply on edit | `./rsmm watch` |
| Package for sharing | `./rsmm pack <id>` — verifies no game bytes leaked |

## Documentation

| For you | Start here |
|---|---|
| End-user (install and mod) | [docs/INSTALLATION.md](docs/INSTALLATION.md) |
| Mod author | [docs/MODDING.md](docs/MODDING.md) |
| CLI reference | [docs/CLI_USAGE.md](docs/CLI_USAGE.md) |
| Developer / contributor | [docs/SETUP.md](docs/SETUP.md) |
| Everything else | [docs/README.md](docs/README.md) |

## Repo layout

```
rsmm                   CLI entry point — every workflow starts here
docs/                  User + developer documentation
mods/                  Installed mods (one folder per id)
data/                  Asset maps + pattern signatures (gitignored)
dist/                  Built loader DLL + packed mod zips
src/rsmm/              Python CLI + SDK
src/loader/            Native DLL (winhttp proxy + Lua VM)
apps/                  TypeScript monorepo (Tauri desktop, Next.js site, Hono API, Astro docs)
packages/              Shared TS packages (db, ui, api-client, schemas)
```

## License

MIT — see [LICENSE](LICENSE). The loader DLL bundles third-party code (MinHook, Dear ImGui, Lua 5.4); their licenses are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Legal

RSMM is a **single-player** modding tool. It does not bypass anti-cheat, does not modify `Ravenswatch.exe`, and requires a legitimate Steam copy of the game. It ships no game content — `data/asset_map.json` is a reconstructed path index, not game assets. Mods authored with RSMM are the modder's own work.
