# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository shape

Hybrid monorepo with two parallel toolchains:

- **Python CLI** (`src/rsmm/`, entry point `./rsmm` at repo root) — all mod install / lifecycle logic. Stdlib-only at runtime (`pyproject.toml` declares no `dependencies`). Installed editable via `pip install -e .`.
- **TypeScript pnpm workspace** (`apps/*` + `packages/*`) — Tauri 2 desktop shell, Hono API, Next.js site, Astro docs, shared `@rsmm/*` packages. Orchestrated by Turbo (`turbo.json`).
- **Native loader DLL** (`src/loader/`, Windows-only) — `winhttp.dll` proxy + MinHook + Lua 5.4 VM injected into Ravenswatch for Lua-scripted mods. Built with CMake. Texture/asset overrides work without it.

The desktop app does **not** reimplement the CLI — it bundles the Python CLI as a PyInstaller sidecar (`apps/desktop/src-tauri/binaries/rsmm-<triple>[.exe]`) and shells out via Tauri's `shell:allow-execute`. See `scripts/build-sidecar.py` for the bundle definition (every data file the frozen CLI needs must be in `add_data_args` or it will crash on a fresh user install).

## Common commands

| Task | Command |
|------|---------|
| Install Python CLI editable | `pip install -e .` (after `python3 -m venv .venv && source .venv/bin/activate`) |
| Install JS deps | `pnpm install` |
| Desktop app (Tauri dev) | `pnpm dev` (= `turbo run dev --filter=desktop`) |
| Desktop app w/ local CLI | `pnpm --filter desktop dev:with-cli` (puts repo root on PATH so it uses `./rsmm` not the bundled sidecar) |
| API server (`:3001`) | `pnpm api:dev` |
| Website (`:3000`) | `pnpm www:dev` |
| Docs site (`:4321`) | `pnpm docs:dev` |
| Lint TS | `pnpm lint` / `pnpm lint:fix` (Biome) |
| Lint Python | `ruff check .` (config in `pyproject.toml` — `src/loader/third_party` excluded) |
| Type-check TS | `pnpm check-types` |
| All Python tests | `pnpm test:python` (= `python -m pytest`) |
| Single Python test | `pytest tests/test_apply_restore.py::test_name` |
| TS schema tests | `pnpm test:ts` |
| Local Postgres | `pnpm db:up` then `pnpm db:push` (Drizzle) |
| Build PyInstaller sidecar | `python scripts/build-sidecar.py` (CI replicates this inline in `.github/workflows/release.yml` — keep both in sync) |
| Build loader DLL (Win) | `src\loader\build.bat` |
| Build loader DLL (Linux→Win, MinGW) | `src/loader/build.sh` |
| Bump versions for release | `python scripts/bump-version.py patch` (or `minor`/`major`/explicit `0.1.12`) — updates all 4 version files atomically |

## Architecture notes worth knowing up front

**Asset application is install-time file replacement, not runtime patching.** Ravenswatch loads cooked assets from `<install>/DarkTalesResources/_Cooking/<encoded>` where `<encoded>` is the plaintext path run through a fixed Caesar cipher (`src/rsmm/engine/cipher.py`, `src/rsmm/engine/find_iyg.py`). `apply_mods.py` walks `mods/`, resolves decoded → encoded via `data/asset_map.json`, backs the original up as `<file>.rsmm.bak`, and copies the override into place. State lives in `<install>/DarkTalesResources/_Cooking/.rsmm_state.json`. Removing the manager is `./rsmm restore --all`. The engine accepts any byte-compatible file — no checksums, no signatures. This avoids the anti-tamper logic in `Ravenswatch.exe`; full background in `docs/ARCHITECTURE.md`.

**Path resolution in frozen mode.** `src/rsmm/engine/paths.py::_find_repo_root` resolves `REPO_ROOT` to PyInstaller's `_MEIPASS` when `sys.frozen` is set. Anything bundled in `build-sidecar.py`'s `add_data_args` is reachable at the same relative path it had in source; anything not bundled is silently missing at runtime. `DEFAULT_GAME_DIR` and `MODS_DIR` are PEP 562 lazy attrs — importing `rsmm.engine.paths` does *not* trigger the disk scan for Ravenswatch (slow on Windows with network drives).

**Re-invoking the CLI from itself uses `self_cmd()`** (`engine/paths.py`). In a frozen bundle `sys.executable` IS rsmm; in source mode it's the Python interpreter + the wrapper script. Never hardcode the entry point.

**Subcommand dispatch is dynamic** (`src/rsmm/cli/_dispatch.py`). Modules are loaded with `importlib`. PyInstaller can't see them statically — CI uses `--collect-submodules=rsmm.cli` etc., the local builder uses an explicit `HIDDEN_IMPORTS` list. Adding a new subcommand requires no edits to bundling if `--collect-submodules` covers it, but **does** require adding the module to `LEGACY` (or argparse subparsers) in `_dispatch.py`.

**Desktop ↔ CLI bridge.** Frontend calls Tauri's `Command` API to spawn the sidecar; responses come back as JSON via `rsmm.cli.json_bridge`. CSP in `apps/desktop/src-tauri/tauri.conf.json` whitelists `connect-src` for outbound API calls — if you add a new backend domain, add it there or fetches fail silently. API CORS in `apps/api/src/env.ts::trustedOrigins` must include every Tauri origin the desktop ships under; missing `http://tauri.localhost` (Windows WebView2) silently breaks every store fetch.

**Updater + signing.** Tauri updater feed is `https://github.com/Ovilli/RavenswatchModManager/releases/latest/download/latest.json`, assembled by the `publish-updater-manifest` job in `.github/workflows/release.yml` from `.sig` files produced by `pnpm tauri build`. Pubkey embedded in `tauri.conf.json`; signing private key lives in `TAURI_SIGNING_PRIVATE_KEY` repo secret. The job is skipped when `vars.HAS_UPDATER_SIGNING != 'true'`, in which case releases ship without auto-update support.

**Version sources.** Four files must move in lockstep on every release: `apps/desktop/src-tauri/tauri.conf.json`, `apps/desktop/src-tauri/Cargo.toml`, `apps/desktop/src-tauri/Cargo.lock` (the `rsmm-desktop` entry), `apps/desktop/package.json`. Root `package.json` and `pyproject.toml` stay at `0.1.0` — they are not user-facing release versions. Use `scripts/bump-version.py` to keep them aligned.

**Release flow.** Push a `v*` tag → `.github/workflows/release.yml` builds matrix (`ubuntu-22.04`, `windows-latest` — macOS support dropped; Windows + Linux only), each leg uploads bundles + `.sig` files to a draft GH release, then `publish-updater-manifest` assembles `latest.json`, then `finalize-release` flips the draft to published. Windows leg uses `shell: pwsh` (not bash) because Git Bash's `/usr/bin/link` shadows MSVC's `link.exe` and breaks Rust builds.

**Loader DLL bundling gotcha.** The Windows CI step builds `winhttp.dll` via `src\loader\build.bat` with `continue-on-error: true`, then PyInstaller bundles `dist/winhttp.dll` if it exists. If `build.bat` writes to the wrong path (it did — fixed in 0.1.11), the build "succeeds" but the DLL is missing from every released sidecar and `rsmm doctor` reports "loader DLL not built" on every user install. Always verify `dist/winhttp.dll` exists after the Windows leg.

**Telemetry / rate limiting.** API uses `createRateLimiter` keyed by user-id or `x-forwarded-for`. Trusted origins, secrets, S3 config all live in `apps/api/src/env.ts`. The auth handler at `/api/auth/*` is Better Auth.

**Engine symbol map (Minecraft-style mappings).** `data/symbols.json` is the canonical, human-authored map from semantic names (`MagicalObject_SpawnAllObjects`) to engine functions/globals — the source of truth. The Ghidra DB names, the loader C++ header (`src/loader/src/symbols.gen.h`), and the Python constants (`src/rsmm/engine/_symbols_gen.py`) are all GENERATED from it via `rsmm symbols gen` (CI `--check`s freshness). Resolution forms, most to least version-resilient: `raw` (`FUN_<addr>` whose byte pattern is in `data/function_patterns.json`, so the loader re-scans across game updates), `anchor` (inlined routine = parent pattern + offset), `va` (base-relative absolute for data globals). Each symbol carries a `status`: `ok` (pattern/anchor resolvable now), `va`, or `unverified` (documented in an older corpus, address not re-confirmed — these are skipped by `rsmm symbols ghidra-export` unless `--include-unverified`). Don't hardcode engine addresses in the loader or SDK; add a symbol and reference `Sym::Name` / `ADDR["Name"]`. To stop functions reading as `FUN_xxxxxxxx` in your own Ghidra, run `rsmm symbols ghidra-export` and apply the script (or feed the `--json` table to the Ghidra MCP bridge). Layers generated on top of the map (the Minecraft Forge/Fabric analogs): (1) **callable typed API** — a symbol with a `cabi` (ret + params) gets a typed, pattern-resolved C++ accessor `engine::Name()` (`src/loader/include/symbols_api.gen.h`) so you call named functions instead of casting raw addresses, plus a Lua resolver `engine_gen.lua`; (2) **event bus** — symbols with `kind="event"` + `lua_event` generate the `EventHook` table spliced into `hook_events.cpp` (`event_table.gen.h`); mods subscribe via `R.on("<lua_event>", cb)`, browse with `rsmm symbols events`; (3) **Lua high-level API** — `R.engine.resolve(name)` / `R.engine.call(name, ...)` in `rsmm.lua` resolve by semantic name through the native `_internal.resolve`/`call`; (4) **engine API docs** — `docs/SYMBOLS.md` (Javadoc analog). All six generated artifacts are `rsmm symbols gen --check`'d in CI.

## Conventions

- **Mods ship data, not code. A discovery script is never the deliverable.** When building a mod, the artifact is a declarative `manifest.toml` (`[[content]]` / `[[patch]]`) plus assets the SDK emits — *not* a bespoke python script. One-off scripts to reverse a byte layout are fine as throwaway *discovery*, but the capability must then graduate into `rsmm.sdk` (a kind builder in `src/rsmm/sdk/kinds/`, an engine cooker in `src/rsmm/engine/`, or the apply pipeline) and the mod re-expressed declaratively; delete the script. `rsmm lint` enforces this — any `*.py` in a mod that isn't a sanctioned lifecycle hook (`on_disable.py`) fails CI. The full custom-magic-item pipeline already lives in the SDK end-to-end (`kinds/item` → `engine/magic_item_cook` → `apply_mods.sync_versiondef`/`sync_usedrsclist`), so a new item = manifest + `rsmm apply`, no script.
- Commit messages follow `chore(release): bump to 0.1.x + <short reason>` for releases; otherwise free-form imperative. Don't add `Co-Authored-By` lines (see memory).
- Python uses ruff with `line-length=100`, `target-version=py311`. `F401` (unused imports) is intentionally ignored to keep `__init__.py` re-exports clean.
- Biome formats/lints TS. Many paths are excluded (`biome.json` `files.ignore`) including `src/rsmm/**`, `scripts/**`, and generated files — touching those won't lint.
- Tests live in `tests/` (pytest, `testpaths` in `pyproject.toml`). Schema/TS tests are scoped to `@rsmm/schemas` via `pnpm test:ts`.

## Useful docs

Prose docs now live as a Starlight site in `apps/docs/` (deployed to `docs.ravenswatch.ovilli.de`; `pnpm docs:dev` to preview). The old `docs/*.md` files are one-line stubs pointing at the site — edit the Markdown under `apps/docs/src/content/docs/` instead. The exception is the generated SDK/CLI reference (see below). `pnpm --filter docs build` runs `starlight-links-validator` (broken internal link → build fails, gated in CI) and `astro-mermaid` (```mermaid fences render as diagrams).

| Topic | File |
|-------|------|
| Full architecture + threat model | `apps/docs/src/content/docs/architecture/overview.md` |
| Asset cipher + cooked-format internals | `apps/docs/src/content/docs/architecture/internals.md` |
| Dev environment setup | `apps/docs/src/content/docs/contributing/setup.md` |
| CLI reference (prose) | `apps/docs/src/content/docs/reference/cli.md` |
| SDK/CLI reference (generated) | `rsmm docs-gen` writes plain Markdown to `docs/api/` **and** Starlight pages to `apps/docs/src/content/docs/reference/sdk-api/`; CI `--check`s both. Source of truth = `@sdk_export` registrations. |
| Authoring mods | `apps/docs/src/content/docs/guides/modding.md` |
| Tauri updater specifics | `apps/desktop/UPDATER.md` |
