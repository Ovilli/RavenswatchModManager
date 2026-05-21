# Ravenswatch Mod Manager (RSMM)

**A cross-platform mod manager for Ravenswatch.** Swap textures, edit stats, override translations, and author Lua-scripted mods — all from a desktop app or CLI. Works on **Windows, macOS, and Linux**.

[![Windows](https://img.shields.io/badge/Windows-x64-blue?logo=windows)](https://github.com/Ovilli/RavenswatchModManager/releases/latest)
[![macOS](https://img.shields.io/badge/macOS-universal-black?logo=apple)](https://github.com/Ovilli/RavenswatchModManager/releases/latest)
[![Linux](https://img.shields.io/badge/Linux-x64-orange?logo=linux)](https://github.com/Ovilli/RavenswatchModManager/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](docs/CONTRIBUTING.md)

## Download

No terminal required. Grab the desktop app for your OS:

| Platform | Installer |
|---|---|
| **Windows** 10/11 | [`RSMM-x64.msi`](https://github.com/Ovilli/RavenswatchModManager/releases/latest) |
| **macOS** 12+ (Intel & Apple Silicon) | [`RSMM-universal.dmg`](https://github.com/Ovilli/RavenswatchModManager/releases/latest) |
| **Linux** (AppImage) | [`RSMM-x86_64.AppImage`](https://github.com/Ovilli/RavenswatchModManager/releases/latest) |
| **Linux** (Debian/Ubuntu) | [`rsmm_amd64.deb`](https://github.com/Ovilli/RavenswatchModManager/releases/latest) |
| **Arch Linux** | `yay -S rsmm` |

## What you can do

| Capability | Desktop app | CLI |
|---|---|---|
| Browse & install mods from the Registry | ✅ Click to install | `rsmm apply` |
| Swap textures, audio, meshes | ✅ Built-in | `rsmm apply` |
| Edit balance numbers | ✅ Coming soon | `rsmm stat` |
| Override translations | ✅ Coming soon | `rsmm text` |
| Manage multiple profiles | ✅ Dropdown menu | — |
| Health check | ✅ Doctor button | `rsmm doctor` |
| Launch the game | ✅ Play button | `rsmm run` |
| Author mods in Lua | — | `rsmm new`, `rsmm pack` |
| Live re-apply on file changes | — | `rsmm watch` |

> **Lua scripting is Windows-only** (requires a native DLL loaded into the game process). Texture swaps, stat edits, and text overrides work on all platforms.

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
  desktop/            Tauri 2 desktop app (Windows, macOS, Linux)
  www/                Next.js website + registry browser
  api/                Hono API server
  docs/               Astro Starlight documentation site
packages/             Shared packages (db, ui, api-client, schemas, tsconfig)
src/rsmm/             Python CLI + SDK
src/loader/           Native DLL (winhttp proxy + Lua VM, Windows only)
docs/                 User + developer documentation
mods/                 Installed mods (one folder per id)
data/                 Asset maps + pattern signatures (gitignored)
dist/                 Built loader DLL + packed mod zips
```

## License

MIT — see [LICENSE](LICENSE). The loader DLL bundles third-party code (MinHook, Dear ImGui, Lua 5.4); their licenses are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Legal

RSMM is a **single-player** modding tool. It does not bypass anti-cheat, does not modify `Ravenswatch.exe`, and requires a legitimate copy of the game. It ships no game content — `data/asset_map.json` is a reconstructed path index, not game assets. Mods authored with RSMM are the modder's own work.
