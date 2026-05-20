# Development setup

The mod manager is a TypeScript monorepo (pnpm + Turborepo) plus the
existing Python CLI (`rsmm`). Local dev needs Node, pnpm, Docker, and —
for desktop builds — Rust.

## Prereqs

| Tool | Version | Notes |
|------|---------|-------|
| Node | >=20.11 | `nvm install 22` recommended |
| pnpm | 9.x | `corepack enable && corepack prepare pnpm@9.12.0 --activate` |
| Docker | any modern | for local Postgres via `docker-compose.yml` |
| Rust | stable | only for `pnpm desktop:dev` and `pnpm build` of Tauri shell. Install via `rustup` |
| Python | >=3.11 | the desktop app shells out to `rsmm` Python CLI |

Platform extras for Tauri 2 desktop builds: see
<https://tauri.app/start/prerequisites/>.

## First-time bootstrap

```sh
# 1. Workspace deps
corepack enable
pnpm install

# 2. Local Postgres
cp .env.example .env
# generate a real auth secret:
sed -i "s/replace-me-32-bytes-hex/$(openssl rand -hex 32)/" .env
pnpm db:up        # docker compose up -d postgres
pnpm db:push      # create tables via Drizzle
pnpm db:seed      # optional sample data
```

## Daily commands

| Command | Description |
|---------|-------------|
| `pnpm dev` | Desktop app (Tauri + Vite). Default dev target. |
| `pnpm desktop:dev` | Same as `pnpm dev`. |
| `pnpm api:dev` | Hono API on `:3001`. |
| `pnpm www:dev` | Next.js marketing + registry on `:3000`. |
| `pnpm docs:dev` | Astro Starlight on `:4321`. |
| `pnpm lint` / `pnpm lint:fix` | Biome lint. |
| `pnpm format` | Biome format. |
| `pnpm check-types` | TypeScript across all packages. |
| `pnpm db:push` | Push schema to DB without migration files. |
| `pnpm generate` | Generate SQL migrations in `packages/db/drizzle/`. |
| `pnpm db:migrate` | Apply migrations from `packages/db/drizzle/`. |
| `pnpm db:seed` | Seed sample registry data. |
| `pnpm db:studio` | Drizzle Studio at `https://local.drizzle.studio`. |
| `pnpm build` | Build every package + app. |

## Linux + NVIDIA: GBM/DRM errors when launching desktop dev

If `pnpm desktop:dev` prints `GBM-DRV error` / `DRM_IOCTL_MODE_CREATE_DUMB
failed: Permission denied` and the window never appears, webkit2gtk is
trying to use the DMA-BUF renderer against the NVIDIA driver. Use the
Linux-friendly dev scripts instead:

```sh
pnpm --filter desktop dev:linux        # disables DMA-BUF + compositing
pnpm --filter desktop dev:linux-soft   # last resort: software GL
```

The variables (`WEBKIT_DISABLE_DMABUF_RENDERER=1`,
`WEBKIT_DISABLE_COMPOSITING_MODE=1`, optionally `LIBGL_ALWAYS_SOFTWARE=1`)
are local-only — no app code change needed.

## Neon (production database)

1. Create a Neon project. Copy the pooled connection string.
2. Set in your deployment env:
   - `DATABASE_URL=postgresql://...neon.tech/...?sslmode=require`
   - `DB_DRIVER=neon`
3. Run `pnpm db:migrate` once after deploys (CI or one-shot job).

Drizzle is configured to work with both `pg` (docker local) and
`@neondatabase/serverless` (Neon HTTP/WS). The switch is the
`DB_DRIVER` env var.

## Architecture

```
apps/desktop  Tauri 2 shell. Vite + React. Spawns `rsmm` CLI as sidecar.
apps/www      Next.js 15 marketing + registry browser.
apps/api      Hono on Node. Better Auth + /mods + /telemetry endpoints.
apps/docs     Astro Starlight.
packages/db   Drizzle schema + migrations (Neon / pg dual driver).
packages/ui   Shared React components + Tailwind preset.
packages/api-client  Typed fetch client for apps/api.
packages/schemas     Zod schemas reused by client + server.
src/rsmm/     The original Python CLI + SDK. Untouched.
```

## Python bridge

The desktop app calls the Python CLI via the Tauri shell plugin:

```ts
import { rsmm } from './lib/rsmm';
const mods = await rsmm<LocalMod[]>(['list', '--json']);
```

The `rsmm` executable must be on `PATH`. For users that means
installing the Python package; for devs, the repo-root `./rsmm`
wrapper works. Each subcommand consumed by the UI must accept
`--json`. Subcommands without `--json` yet are tracked in
`docs/ROADMAP.md`.

## Object storage for mod uploads

`/mods/upload` returns a pre-signed PUT URL. Works with **AWS S3**,
**Cloudflare R2**, and **MinIO**. Fill in `S3_*` in `.env`. If unset,
the endpoint returns `503` and the registry stays read-only.

R2 example:

```
S3_BUCKET=rsmm-mods
S3_REGION=auto
S3_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
S3_PUBLIC_BASE_URL=https://cdn.rsmm.dev
```

Client flow:

1. `POST /mods/upload` with manifest + sha256 + sizeBytes → `{ uploadUrl, publicUrl, versionId }`
2. `PUT uploadUrl` with the `.zip` body and headers
   `Content-Type: application/zip` + `x-amz-checksum-sha256: <base64(sha256)>`
3. Done. The DB row already points at `publicUrl`.

## Releasing the desktop app

`.github/workflows/release.yml` runs on `git push --tags v*` and cuts
installers via `tauri-action` for Windows / macOS (universal) / Linux.
Local release: `pnpm build` produces installers under
`apps/desktop/src-tauri/target/release/bundle/`.

## Tauri icons

The committed `apps/desktop/src-tauri/icons/icon.png` is a placeholder
(solid colour). Replace it with a real 1024×1024 PNG, then from
`apps/desktop/`:

```sh
pnpm tauri icon icons/icon.png
```

This regenerates every required size + `.ico` + `.icns` + mobile variants.
