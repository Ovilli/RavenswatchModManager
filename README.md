# Ravenswatch Mod Manager (RSMM)

**A mod manager for Ravenswatch.** Swap textures, edit stats and talent values, override translations, and author Lua-scripted mods from a desktop app or CLI. Ravenswatch ships on **Windows** (and runs on **Linux** via Proton / Steam Deck); RSMM supports both. There is no native macOS release of the game.

[![Windows](https://img.shields.io/badge/Windows-x64-blue?logo=windows)](https://github.com/Ovilli/RavenswatchModManager/releases/latest)
[![Linux](https://img.shields.io/badge/Linux-x64-orange?logo=linux)](https://github.com/Ovilli/RavenswatchModManager/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## Download

No terminal required. Grab the desktop app for your OS:

| Platform | Installer |
|---|---|
| **Windows** 10/11 | [`RSMM-x64.msi`](https://github.com/Ovilli/RavenswatchModManager/releases/latest) |
| **Linux** (AppImage) | [`RSMM-x86_64.AppImage`](https://github.com/Ovilli/RavenswatchModManager/releases/latest) |
| **Linux** (Debian/Ubuntu) | [`rsmm_amd64.deb`](https://github.com/Ovilli/RavenswatchModManager/releases/latest) |

## What you can do

✅ works today · ⬜ planned (not built yet)

| Capability | Desktop app | CLI |
|---|---|---|
| Install mods (local folder or registry) | ✅ Click to install | `rsmm apply` |
| Swap textures | ✅ Built-in | `rsmm apply` |
| Edit balance numbers | ⬜ Planned | ✅ SDK `m.stat()` / `[[patch]] kind="stat"` |
| Edit talent / item values | ⬜ Planned | ✅ `rsmm talents`, `value_patches` |
| Override translations | ⬜ Planned | ✅ SDK `m.text()` / `[[patch]] kind="text"` |
| Add a custom magic item | ⬜ Planned | ✅ `kind="item"` |
| Manage multiple profiles | ✅ Dropdown menu | — |
| Health check | ✅ Doctor button | ✅ `rsmm doctor` |
| Launch the game | ✅ Play button | ✅ `rsmm run` |
| Author mods in Lua | — | ✅ `rsmm new`, `rsmm pack` |
| Live re-apply on file changes | — | ✅ `rsmm watch` |

> **Lua scripting is Windows-only** (a native DLL is loaded into the game process). Texture/stat/talent/item edits are install-time file replacement and work wherever the game runs.

> **The registry is new and holds very few mods yet** — RSMM mostly installs mods you point it at locally. Content kinds beyond the ones above (custom enemies, heroes, bosses, skins) are **experimental or unproven in-game**; see the confidence table in [docs/MODDING.md](docs/MODDING.md#content-kinds--confidence) for exactly what to trust.

## Quick start (desktop app)

1. [Download](https://github.com/Ovilli/RavenswatchModManager/releases/latest) and install RSMM for your OS
2. Launch the app — it auto-detects your Ravenswatch installation
3. Browse the Registry tab and install mods
4. Click **Apply** to copy mods into the game
5. Click **Play** to launch Ravenswatch

See [Installation Guide](docs/INSTALLATION.md) for full setup including the CLI.

## Quick start (CLI)

```sh
git clone https://github.com/Ovilli/RavenswatchModManager.git
cd RavenswatchModManager
python3 -m venv .venv && source .venv/bin/activate && pip install -e .
./rsmm doctor
./rsmm new MyMod
./rsmm apply
```

## Documentation

| For you | Start here |
|---|---|
| Installing the mod manager | [docs/INSTALLATION.md](docs/INSTALLATION.md) |
| Using the desktop app | [RSMM Docs](https://rsmm.dev) |
| Creating mods | [docs/MODDING.md](docs/MODDING.md) |
| CLI reference | [docs/CLI_USAGE.md](docs/CLI_USAGE.md) |
| Contributing | [docs/SETUP.md](docs/SETUP.md) |

## Repo layout

```
rsmm                  CLI entry point — every workflow starts here
apps/                 TypeScript monorepo (Tauri desktop, Next.js site, Hono API, Astro docs)
  desktop/            Tauri 2 desktop app (Windows, Linux)
  www/                Next.js website + registry browser
  api/                Hono API server
  docs/               Astro Starlight documentation site
packages/             Shared packages (db, ui, api-client, schemas, tsconfig)
src/rsmm/             Python CLI + SDK
src/loader/           Native DLL (winhttp proxy + Lua VM, Windows only)
docs/                 User + developer documentation
mods/                 Installed mods (one folder per id)
data/                 Symbol map (tracked) + asset maps / pattern sigs (gitignored)
dist/                 Built loader DLL + packed mod zips
```

## License

MIT — see [LICENSE](LICENSE). The loader DLL bundles third-party code (MinHook, Dear ImGui, Lua 5.4); their licenses are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Legal

RSMM is a **single-player** modding tool. It does not bypass anti-cheat, does not modify `Ravenswatch.exe`, and requires a legitimate copy of the game. It ships no game content — `data/asset_map.json` is a reconstructed path index, not game assets. Mods authored with RSMM are the modder's own work.
