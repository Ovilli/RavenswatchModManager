# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository shape

Hybrid monorepo with two parallel toolchains:

- **Python CLI** (`src/rsmm/`, entry point `./rsmm` at repo root) — all mod install / lifecycle logic. Stdlib-only at runtime (`pyproject.toml` declares no `dependencies`). Installed editable via `pip install -e .`.
- **TypeScript pnpm workspace** (`apps/*` + `packages/*`) — Tauri 2 desktop shell, Hono API, Next.js site, Astro docs, shared `@rsmm/*` packages. Orchestrated by Turbo (`turbo.json`).
- **Native loader DLL** (`src/loader/`, Windows-only) — `winhttp.dll` proxy + MinHook + Lua 5.4 VM injected into Ravenswatch for Lua-scripted mods. Built with CMake. Texture/asset overrides work without it. The Lua SDK (`src/loader/lib/rsmm.lua` + the generated `engine_gen.lua`/`events_gen.lua`, plus the `src/loader/lua/rsmm/*.lua` submodules it requires) is **disk-loaded from `<game>/rsmm/lib/`, not embedded in the DLL** — a Lua-only change ships via `rsmm install-loader` (or a straight file copy), no rebuild.

The desktop app does **not** reimplement the CLI — it bundles the Python CLI as a PyInstaller sidecar (`apps/desktop/src-tauri/binaries/rsmm-<triple>[.exe]`) and shells out via Tauri's `shell:allow-execute`. `scripts/build-sidecar.py` is the only bundle definition (release.yml and the CI `sidecar` job both call it): every data file the frozen CLI needs must be in its `BUNDLE` list, and its post-build check fails when a listed file is missing from the binary or a subcommand crashes when run frozen.

## Common commands

| Task | Command |
|------|---------|
| Desktop app (Tauri dev) | `pnpm dev` (= `turbo run dev --filter=desktop`). **Not `npm run dev`** — that makes corepack fetch the pinned `pnpm@9.12.0`, and turbo swallows corepack's confirm prompt, so the run stops dead after `! Corepack is about to download …` with no window and no error. `export COREPACK_ENABLE_DOWNLOAD_PROMPT=0` in your shell rc; it recurs on a fresh clone or an nvm version switch. |
| Desktop app w/ local CLI | `pnpm --filter desktop dev:with-cli` (puts repo root on PATH so it uses `./rsmm` not the bundled sidecar) |
| Item / talent / ability / map editor | `rsmm editor [--tab items\|talents\|abilities\|map]` (local page); the same editors run in the browser at `docs.rsmm.me/editor/` |
| Lint Python | `ruff check .` (config in `pyproject.toml` — `src/loader/third_party` excluded) |
| Fast Python tests (~2s) | `pnpm test:python:fast` (= `pytest -n auto -m "not slow"`; heavy corpus-scan tests are auto-marked `slow`) |
| Loader Lua SDK spec | `lua tests/lua/rsmm_spec.lua` (also wrapped as `pytest tests/test_loader_lua.py`) — engine-faithful mocks; extend it when touching `rsmm.lua` engine-call paths |
| TS tests (vitest) | `pnpm test:ts` — `@rsmm/schemas` + `@rsmm/api-client` + `desktop` + `www` |
| Regen symbol artifacts | `rsmm symbols gen` (after editing `data/symbols.json`; CI runs `--check`) |
| Inspect a profile save | `rsmm save` (read-only; container + CRC + class registry). **Never write to `<game>/_Save/Profile_*.ob`** — copy to /tmp to experiment |

Reverse-engineering / patch-day / data-mining commands (`rsmm symbols`, `scripts/disasm.py`, Ghidra, BinDiff, vtable typing, `extract_uncooked.py`, `extract_audio.py`, …) and the **new-capability workflow** (recon → dynamic proof → symbol entry) live in the `re-workflow` skill — load it before any RE on a subsystem with no `status="ok"` symbol. Release / publish procedures (version bump, tag flow, `publish-loader.yml`, changelog, updater signing) live in the `release` skill. Directory-specific notes load from `CLAUDE.md` in `src/loader/`, `src/rsmm/engine/`, `src/rsmm/cli/` and `apps/desktop/`.

**Engine symbols:** never hardcode engine addresses in the loader or SDK — add a symbol to `data/symbols.json` and reference `Sym::Name` / `ADDR["Name"]`; run `rsmm symbols gen` after editing it (CI `--check`s it), and `python scripts/verify_symbol_resolve.py` after any remap (`--check` never proves an address is CORRECT).

## Architecture notes worth knowing up front

**Asset application is install-time file replacement, not runtime patching.** Ravenswatch loads cooked assets from `<install>/DarkTalesResources/_Cooking/<encoded>` where `<encoded>` is the plaintext path run through a fixed Caesar cipher (`src/rsmm/engine/cipher.py`, `src/rsmm/engine/find_iyg.py`). `apply_mods.py` walks `mods/`, resolves decoded → encoded via `data/asset_map.json`, backs the original up as `<file>.rsmm.bak`, and copies the override into place. State lives in `<install>/DarkTalesResources/_Cooking/.rsmm_state.json`. Removing the manager is `./rsmm restore --all`. The engine accepts any byte-compatible file — no checksums, no signatures. This avoids the anti-tamper logic in `Ravenswatch.exe`; full background in `apps/docs/src/content/docs/architecture/overview.md`.

**Never `vercel env pull` into `apps/api/`.** Vite substitutes `process.env.X` into `apps/api/src/**` at TRANSFORM time from the env files beside the vitest root, so a pulled `apps/api/.env.local` bakes real production credentials into the code under test — `Object.keys(process.env)` shows nothing while a static `process.env.KV_REST_API_URL` returns the live URL, which is what makes it so hard to see. The consequence is not a stale value: it flipped `upstashEnabled` on inside the suite, so `pnpm test` on a developer's machine incremented PRODUCTION rate-limit counters over the network. Setting `envDir` does not fix it (tried, reverted — it does not stop the substitution). The fix is to not have the file: root `.env.local` is what `pnpm api:dev` and `test/setup-env.ts` read, and nothing needs a per-package copy. `vercel link --cwd apps/api` writes one as a side effect, so delete it afterwards.

**Telemetry / rate limiting.** API uses `createRateLimiter` keyed by user-id or `x-forwarded-for`. Trusted origins, secrets, S3 config all live in `apps/api/src/env.ts`. The auth handler at `/api/auth/*` is Better Auth.

## Conventions

- **Mods ship data, not code. A discovery script is never the deliverable.** When building a mod, the artifact is a declarative `manifest.toml` (`[[content]]` / `[[patch]]`) plus assets the SDK emits — *not* a bespoke python script. One-off scripts to reverse a byte layout are fine as throwaway *discovery*, but the capability must then graduate into `rsmm.sdk` (a kind builder in `src/rsmm/sdk/kinds/`, an engine cooker in `src/rsmm/engine/`, or the apply pipeline) and the mod re-expressed declaratively; delete the script. `rsmm lint` enforces this — any `*.py` in a mod that isn't a sanctioned lifecycle hook (`on_disable.py`) fails CI. The full custom-magic-item pipeline already lives in the SDK end-to-end (`kinds/item` → `engine/magic_item_cook` → `apply_mods.sync_versiondef`/`sync_usedrsclist`), so a new item = manifest + `rsmm apply`, no script.
- **Mod Lua never touches engine internals directly.** `rsmm lint` ERRORs on literal game VAs (`0x14xxxxxxx`) or low-level primitives (`_internal`, `peek/poke`, `read_*/write_*`, `call_raw`, `engine.resolve`) in any mod's `*.lua`. New capability goes into the SDK (`src/loader/lib/rsmm.lua` + a symbol in `data/symbols.json`); the mod consumes only high-level `R.*`.
- **Never hand a probed or baked pointer to `R.engine.call` without validating the full structure the callee will traverse.** Every loader in-game crash so far was this bug (ctx deref, probe→engine walk). Native `read_*` is page-guarded (bad read → nil, no fault) so probing is safe, but the instant a pointer is a *call argument* the engine owns the deref. Use the pointer-safety library in `rsmm.lua` (`R.ptr.plausible/in_image/has_vtable/vector_valid`) to build the validator and prefer `R.engine.call_safe(name, ptr_arg_specs, ...)` so the guard can't be forgotten. `R.debug.dump(ptr)` / `R.debug.find_arrays(obj)` turn multi-launch struct-hunting into one launch.
- **Some kinds are override-only by design, not by omission.** `reward` and `melody` edit a *retail* def in place (the emitted asset lands at the vanilla decoded path and `apply` backs up + replaces it) rather than cloning under a new id. For `melody` that is forced: the 12 retail melodydefs' `field_a` values are exactly `{0..11}` and `Ui\Melodies` ships exactly 12 icons with no icon ref in the def, so a 13th melody has no index and no icon — the same wall documented for skins and heroes. Don't "fix" these kinds by adding a clone path.
- **Content kinds carry confidence ratings** (`src/rsmm/sdk/content.py::KIND_CONFIDENCE`: confirmed/experimental/guess). Registering a non-confirmed kind raises unless the mod opts in with `sdk.Mod(..., experimental=True)`; lint enforces the manifest flag. When a kind is proven in-game, flip its rating and keep the docs confidence table in sync.
- Commit messages follow `chore(release): bump to 0.1.x + <short reason>` for releases; otherwise free-form imperative. Don't add `Co-Authored-By` lines (see memory).
- Ruff's `F401` (unused imports) is intentionally ignored to keep `__init__.py` re-exports clean.
- Biome formats/lints TS. Many paths are excluded (`biome.json` `files.ignore`) including `src/rsmm/**`, `scripts/**`, and generated files — touching those won't lint.
- Tests must never mutate tracked `data/` files — an autouse conftest guard fails the offender; `cmd_apply` tests must stub `rsmm.engine.find_iyg.main`. `apps/www`'s suite is `src/**/*.test.ts` only (plain modules, no jsdom); it exists for `lib/markdown.ts`, whose output reaches `dangerouslySetInnerHTML`.
- **Never `monkeypatch.setattr` `rsmm.engine.paths.MODS_DIR` / `DEFAULT_GAME_DIR`.** They are PEP 562 `__getattr__` attrs, not dict entries: setattr reads the *real* repo `mods/` as the old value and its undo writes that real path into the module dict, permanently shadowing `__getattr__` — even across `importlib.reload`. Every later `RSMM_MODS_DIR` override is then ignored and `rsmm new` scaffolds into the developer's actual `mods/`. Serial-only failure; xdist hides it by splitting the polluter onto another worker. Use `monkeypatch.setenv("RSMM_MODS_DIR"/"RSMM_GAME_DIR", ...)`; `tests/conftest.py::_guard_lazy_paths` and `_guard_real_mods_dir` fail-close on both. `default_game_dir()` reads its override at call time (only the candidate scan, `_scan_game_dir()`, is `@cache`d) — there is no `default_game_dir.cache_clear()`.

## Useful docs

Prose docs now live as a Starlight site in `apps/docs/` (deployed to `docs.rsmm.me`; `pnpm docs:dev` to preview). The old `docs/*.md` files are one-line stubs pointing at the site — edit the Markdown under `apps/docs/src/content/docs/` instead. The exception is the generated SDK/CLI reference (see below). `pnpm --filter docs build` runs `starlight-links-validator` (broken internal link → build fails, gated in CI) and `astro-mermaid` (```mermaid fences render as diagrams).

| Topic | File |
|-------|------|
| Full architecture + threat model | `apps/docs/src/content/docs/architecture/overview.md` |
| Asset cipher + cooked-format internals | `apps/docs/src/content/docs/architecture/internals.md` |
| Dev environment setup | `apps/docs/src/content/docs/contributing/setup.md` |
| CLI reference (prose) | `apps/docs/src/content/docs/reference/cli.md` |
| SDK/CLI reference (generated) | `rsmm docs-gen` writes plain Markdown to `docs/api/` **and** Starlight pages to `apps/docs/src/content/docs/reference/sdk-api/`; CI `--check`s both. Source of truth = `@sdk_export` registrations. |
| Authoring mods | `apps/docs/src/content/docs/guides/modding.md` |
| Tauri updater specifics | `apps/desktop/UPDATER.md` |
