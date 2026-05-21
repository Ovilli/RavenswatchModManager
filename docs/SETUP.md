# Development Setup

This guide covers setting up a development environment for hacking on RSMM itself. If you just want to *use* the mod manager, see [Installation](INSTALLATION.md).

> **Note about paths:** throughout this document, `./rsmm <name>` refers to the repo-root entry point. The equivalent Python module lives at `src/rsmm/cli/<name>.py` or `src/rsmm/engine/<name>.py`.

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Node | >= 20.11 | `nvm install 22` recommended |
| pnpm | 9.x | `corepack enable && corepack prepare pnpm@9.12.0 --activate` |
| Docker | any modern | For local Postgres via `docker compose` |
| Rust | stable | Only for desktop (Tauri) builds. Install via `rustup` |
| Python | >= 3.11 | The desktop app shells out to the Python CLI |
| CMake | >= 3.20 | For building the native loader DLL |
| Git | any | |

Platform extras for Tauri 2 desktop builds: see [tauri.app/start/prerequisites](https://tauri.app/start/prerequisites/).

---

## First-time bootstrap

```sh
# 1. Clone
git clone https://github.com/Ovilli/RavenswatchModManager.git
cd RavenswatchModManager

# 2. Python virtual env (for the rsmm CLI)
python3 -m venv .venv
source .venv/bin/activate       # Linux
# .venv\Scripts\activate        # Windows
pip install -e .

# 3. Workspace deps (TypeScript monorepo)
corepack enable
pnpm install

# 4. Local Postgres
cp .env.example .env
sed -i "s/replace-me-32-bytes-hex/$(openssl rand -hex 32)/" .env
pnpm db:up        # docker compose up -d postgres
pnpm db:push      # Create tables via Drizzle
pnpm db:seed      # Optional sample data
```

## Daily commands

| Command | Description |
|---|---|
| `pnpm dev` | Desktop app (Tauri + Vite) |
| `pnpm dev:with-cli` | Desktop app (uses system `rsmm` Python CLI from repo root) |
| `pnpm api:dev` | Hono API on `:3001` |
| `pnpm www:dev` | Next.js website + registry on `:3000` |
| `pnpm docs:dev` | Astro Starlight docs on `:4321` |
| `pnpm lint` / `pnpm lint:fix` | Biome lint |
| `pnpm format` | Biome format |
| `pnpm check-types` | TypeScript across all packages |
| `pnpm db:push` | Push schema to local DB |
| `pnpm db:migrate` | Apply migrations |
| `pnpm build` | Build every package + app |

### Platform-specific desktop dev

| Command | Platform | Use case |
|---|---|---|
| `pnpm --filter desktop dev` | All | Standard development |
| `pnpm --filter desktop dev:linux` | Linux | If WebKit DMA-BUF errors occur |
| `pnpm --filter desktop dev:linux-soft` | Linux | Software GL fallback (last resort) |
| `pnpm --filter desktop dev:mac-arm` | macOS (Apple Silicon) | Native ARM64 development |

### Production builds

| Command | Output |
|---|---|
| `pnpm --filter desktop build` | Native platform installer (MSI/DMG/AppImage) |
| `pnpm --filter desktop build:universal` | macOS universal binary (Intel + Apple Silicon) |
| `pnpm --filter desktop build:linux` | Linux x86_64 build |
| `pnpm --filter desktop build:windows` | Windows x64 build |

### Sidecar (Python CLI binary)

For production builds, the Python CLI must be bundled as a standalone executable:

```sh
python3 scripts/build-sidecar.py              # Build for current platform
python3 scripts/build-sidecar.py --target linux
python3 scripts/build-sidecar.py --target macos
python3 scripts/build-sidecar.py --target windows
python3 scripts/build-sidecar.py --all         # Build for all platforms
```

Requires PyInstaller (`pip install pyinstaller`). The output binary is placed at
`apps/desktop/src-tauri/binaries/rsmm-<target-triple>` where Tauri's sidecar resolver expects it.

For development, you can use the system Python CLI instead (`rsmm` on PATH from `pip install -e .`).
The desktop app falls back to the system command if the sidecar binary is not found.

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

The compiled `winhttp.dll` appears in `dist/`.

## Testing

```sh
# Python tests
pytest -q                                    # From repo root

# Regenerate dev artifacts (optional, not committed)
pip install --user texture2ddecoder Pillow capstone
python3 scripts/extract_uncooked.py           # Uncooked asset mirror
python3 scripts/decode_gen_sidecars.py        # .gen sidecars
bash docs/_re/run_dump_symbols.sh             # Ghidra symbol dump
python3 scripts/gen_function_patterns.py      # Pattern DB
python3 scripts/test_pattern_resolve.py --all # Validate patterns
```

## IDE setup

Open the workspace in VS Code. Install the CMake Tools and Python extensions. Point the Python interpreter to `.venv`.

## Architecture

```
apps/desktop    Tauri 2 shell. Vite + React. Spawns `rsmm` CLI as sidecar.
apps/www        Next.js 15 marketing site + registry browser.
apps/api        Hono on Node. Better Auth + /mods + /telemetry endpoints.
apps/docs       Astro Starlight documentation site.
packages/db     Drizzle schema + migrations (Neon / pg dual driver).
packages/ui     Shared React components + Tailwind preset.
packages/api-client  Typed fetch client for apps/api.
packages/schemas     Zod schemas shared by client + server.
src/rsmm/       Python CLI + SDK. Untouched by the TypeScript monorepo.
src/loader/     Native DLL source (winhttp proxy + Lua VM).
```

## Python bridge

The desktop app calls the Python CLI via the Tauri shell plugin:

```ts
import { rsmm } from './lib/rsmm';
const mods = await rsmm<LocalMod[]>(['list', '--json']);
```

The `rsmm` executable must be on `PATH`. For devs, the repo-root `./rsmm` wrapper works.

## Local vs production database

Local: Docker Postgres via `docker compose up -d postgres`. Connection string in `.env`.

Production: [Neon](https://neon.tech) serverless Postgres. Set `DATABASE_URL` and `DB_DRIVER=neon` in your deployment environment. Run `pnpm db:migrate` once after deploy.

Drizzle is configured for both drivers — the switch is the `DB_DRIVER` env var.

## Tauri icons

The committed `apps/desktop/src-tauri/icons/icon.png` is a placeholder. Replace with a real 1024×1024 PNG, then:

```sh
cd apps/desktop
pnpm tauri icon icons/icon.png
```

This regenerates every required size + `.ico` + `.icns` + mobile variants.

## Linux + NVIDIA

If `pnpm desktop:dev` prints GBM/DRM errors and the window never appears:

```sh
pnpm --filter desktop dev:linux          # Disable DMA-BUF + compositing
pnpm --filter desktop dev:linux-soft     # Last resort: software GL
```

---

## Contributing

### Reporting issues

- Search existing issues first.
- Provide reproduction steps, OS, game version, and relevant logs.

### Code style

- Follow existing formatting in `src/` and `apps/`.
- Use `clang-format` for C++ and `black` for Python where applicable.

### Pull requests

- Fork the repo and create a focused topic branch.
- Include a clear description, related issue, and testing steps.
- Ensure CI passes before requesting review.

### Communication

- Be responsive to review comments and keep PRs small.
