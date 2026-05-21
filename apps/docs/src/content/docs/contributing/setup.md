---
title: Development setup
description: Set up a local development environment for RSMM.
---

This guide covers setting up a development environment for working on RSMM itself.

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Node | >= 20.11 | `nvm install 22` recommended |
| pnpm | 9.x | `corepack enable && corepack prepare pnpm@9.12.0 --activate` |
| Docker | any modern | For local Postgres via `docker compose` |
| Rust | stable | Only for desktop (Tauri) builds |
| Python | >= 3.11 | The desktop app shells out to the Python CLI |
| CMake | >= 3.20 | For building the native loader DLL |
| Git | any | |

Platform extras for Tauri 2 desktop builds: see [tauri.app/start/prerequisites](https://tauri.app/start/prerequisites/).

## First-time bootstrap

```sh
# 1. Clone
git clone https://github.com/Ovilli/RavenswatchModManager.git
cd RavenswatchModManager

# 2. Python virtual env (for the rsmm CLI)
python3 -m venv .venv
source .venv/bin/activate       # Linux / macOS
# .venv\Scripts\activate        # Windows
pip install -e .

# 3. Workspace deps (TypeScript monorepo)
corepack enable
pnpm install

# 4. Local Postgres (optional, for API development)
cp .env.example .env
pnpm db:up        # docker compose up -d postgres
pnpm db:push      # Create tables via Drizzle
pnpm db:seed      # Optional sample data
```

## Daily commands

| Command | Description |
|---|---|
| `pnpm dev` | Desktop app (Tauri + Vite) |
| `pnpm dev:with-cli` | Desktop app using the system `rsmm` Python CLI |
| `pnpm api:dev` | Hono API on `:3001` |
| `pnpm www:dev` | Next.js website + registry on `:3000` |
| `pnpm docs:dev` | Astro Starlight docs on `:4321` |
| `pnpm lint` / `pnpm lint:fix` | Biome lint |
| `pnpm check-types` | TypeScript across all packages |
| `pnpm build` | Build every package + app |

### Platform-specific desktop dev

- **Linux with DMA-BUF issues**: `pnpm --filter desktop dev:linux`
- **Linux software fallback**: `pnpm --filter desktop dev:linux-soft`
- **Apple Silicon**: `pnpm --filter desktop dev:mac-arm`

### Production builds

```sh
pnpm --filter desktop build                # Native installer for current platform
pnpm --filter desktop build:universal      # macOS universal binary (Intel + Apple Silicon)
pnpm --filter desktop build:linux          # Linux x86_64
pnpm --filter desktop build:windows        # Windows x64
```

### Sidecar (Python CLI binary)

For production builds, the Python CLI must be bundled as a standalone binary:

```sh
pip install pyinstaller
python3 scripts/build-sidecar.py           # Build for current platform
python3 scripts/build-sidecar.py --all     # Build for all platforms
```

The sidecar binary is placed at `apps/desktop/src-tauri/binaries/rsmm-<target-triple>`.

## Building the native loader

```sh
# Linux (cross-compile for Windows via MinGW)
cd src/loader
./build.sh

# Windows (auto-detects Visual Studio or MinGW)
cd src\loader
fetch_deps.bat
build.bat
```

## Testing

```sh
# Python tests
pytest -q
```

## Architecture

```
apps/desktop    Tauri 2 shell. Vite + React. Calls `rsmm` CLI as sidecar.
apps/www        Next.js 15 marketing site + registry browser.
apps/api        Hono on Node. Better Auth + /mods + /telemetry endpoints.
apps/docs       Astro Starlight documentation site.
packages/db     Drizzle schema + migrations (Neon / pg dual driver).
packages/ui     Shared React components + Tailwind preset.
packages/api-client  Typed fetch client for apps/api.
packages/schemas     Zod schemas shared by client + server.
src/rsmm/       Python CLI + SDK.
src/loader/     Native DLL source (winhttp proxy + Lua VM, Windows only).
```
