# Ravenswatch Mod Manager — Documentation

RSMM runs on **Windows, macOS, and Linux**. Pick your path.

> **Source of truth:** these `docs/*.md` files are the canonical, in-depth
> docs. [rsmm.dev](https://rsmm.dev) is a lighter, polished mirror of the
> user-facing pages (sourced from `apps/docs/`). `docs/api/` is **generated**
> by `rsmm docs-gen` — never hand-edit it (CI fails if it drifts).

---

## 🎮 I just want to mod the game

| Guide | What you'll learn |
|---|---|
| [Installation](INSTALLATION.md) | Download and install the desktop app on Windows, macOS, or Linux |
| [Desktop app guide](https://rsmm.dev/getting-started/desktop-app/) | Full walkthrough of the graphical interface |
| [Quick Start](INSTALLATION.md#cli-advanced) | CLI setup (advanced users) |
| [Troubleshooting](INSTALLATION.md#troubleshooting) | Fix common issues |

## ✏️ I want to write mods

| Guide | What you'll learn |
|---|---|
| [Mod Authoring](MODDING.md) | How to create, build, and share mods |
| [CLI Reference](CLI_USAGE.md) | Every `rsmm` command explained |
| [Lua Scripting](MODDING.md#lua-scripted-mod) | Write game behaviour (Windows only) |
| [Uncooked Asset Mirror](UNCOOKED_ASSETS.md) | Browse readable game assets as reference |

## 🛠️ I want to contribute to RSMM

| Guide | What you'll learn |
|---|---|
| [Development Setup](SETUP.md) | Clone, build, and run everything locally |
| [Architecture](ARCHITECTURE.md) | How the mod manager works under the hood |
| [Contributing](SETUP.md#contributing) | Pull requests, code style, CI |

## 📖 Reference

| Document | What it covers |
|---|---|
| [Roadmap](ROADMAP.md) | What's built, what's next |
| [SDK v3 Spec](SDK_V3.md) | Design for the next-gen modding SDK |
| [SDK + CLI API reference](api/README.md) | **Generated** — every `@sdk_export` + every `rsmm` subcommand ([cli.md](api/cli.md)) |
| [Engine Internals](INTERNALS.md) | Reverse-engineering notes (advanced) |
