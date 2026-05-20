# Online services — step-by-step setup

This guide covers every external service you sign up for to take the
project from "running locally on my laptop" to "publicly hosted with
real users". Everything is free-tier where possible.

Order matters — later steps need values from earlier ones. Do them
top-to-bottom.

## What you'll provision

| Service | Why | Free? |
|---------|-----|-------|
| GitHub | Source repo, CI, Releases | yes |
| Neon | Serverless Postgres for prod registry + telemetry | yes (0.5 GB) |
| Cloudflare R2 | Object storage for uploaded mod `.zip` files | yes (10 GB/mo egress free) |
| Vercel | Hosting for `apps/www` (Next.js) | yes |
| Fly.io OR Railway | Hosting for `apps/api` (Hono/Node) | free trial only — paid after |
| Cloudflare Pages | Hosting for `apps/docs` (Astro) | yes |
| Domain (rsmm.dev or similar) | Friendly URL + email | ~$10/yr |

If money is the issue, you can host the API on Fly's free tier (1 shared
CPU, 256 MB RAM — fine for a registry) or Railway's $5/mo plan. Skip the
domain for v1 and use the `*.vercel.app` and `*.fly.dev` URLs.

---

## Step 1: GitHub repo + Actions secrets

1. Push the monorepo to GitHub if you haven't already:
   ```sh
   git remote -v
   # if no origin: gh repo create Ovilli/RavenswatchModManager --source=. --public --push
   git push -u origin main
   ```
2. Open **github.com/Ovilli/RavenswatchModManager → Settings → Secrets and variables → Actions**.
3. You'll come back to add secrets here in later steps. Leave this tab open.

The release workflow (`.github/workflows/release.yml`) already runs on
`git push --tags v*` — no secrets needed for basic Tauri builds; the
default `GITHUB_TOKEN` is enough for creating the draft release.

---

## Step 2: Neon (serverless Postgres)

1. Sign up at **<https://neon.tech>** (GitHub login is fastest).
2. Click **"New Project"**:
   - Name: `rsmm-prod`
   - Postgres version: 16
   - Region: pick whatever's closest to where your API will run (see Step 5)
3. After creation, Neon shows a **Connection string**. It looks like:
   ```
   postgresql://rsmm_owner:abc123@ep-cool-snow-12345.us-east-2.aws.neon.tech/rsmm?sslmode=require
   ```
   Copy it. This is `DATABASE_URL`.
4. In your Neon project, go to **Branches → main → Database**. The default
   `neondb` may be the DB name; create one called `rsmm` via **Tables → New database** if you prefer a cleaner name. Update the connection string accordingly.
5. Apply the schema once from your laptop, against the Neon URL:
   ```sh
   DATABASE_URL='paste-neon-url' DB_DRIVER=neon pnpm db:push
   ```

You now have a production DB. Save the connection string somewhere
secure (1Password, Bitwarden) — you'll paste it into Vercel and Fly env
vars in later steps.

---

## Step 3: Cloudflare R2 (object storage for uploads)

R2 is S3-compatible. The API code already supports it via the same
`S3_*` env vars.

1. Sign up at **<https://dash.cloudflare.com>**.
2. Left sidebar → **R2 Object Storage**. Click **Purchase R2** — the free tier costs nothing but Cloudflare wants a card on file. Free tier: 10 GB storage + 10M Class A ops + unlimited egress.
3. Click **Create bucket**:
   - Name: `rsmm-mods`
   - Location: Automatic
4. After creation, open the bucket → **Settings**. Note the bucket name + the **Account ID** (top of the page or right sidebar).
5. Left sidebar → **R2 → Manage R2 API Tokens → Create API token**:
   - Token name: `rsmm-api-write`
   - Permissions: **Object Read & Write**
   - Specify bucket: `rsmm-mods`
   - TTL: leave blank (or set to 1 year)
   - Click **Create API Token**
6. R2 shows the credentials **once** — copy these now:
   - Access Key ID
   - Secret Access Key
   - **Endpoint** for S3-compatible clients: `https://<account-id>.r2.cloudflarestorage.com`
7. (Optional) Enable a **public r2.dev URL** for the bucket so clients can download mods without signed URLs:
   - Bucket → **Settings → Public access → Allow Access** → opt into `r2.dev`
   - Note the public URL: `https://pub-<hash>.r2.dev`
   - This is `S3_PUBLIC_BASE_URL`. Skip if you want all downloads gated by signed URLs.

You'll paste these into the API env in Step 5:

```
S3_BUCKET=rsmm-mods
S3_REGION=auto
S3_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
S3_ACCESS_KEY_ID=<from step 6>
S3_SECRET_ACCESS_KEY=<from step 6>
S3_PUBLIC_BASE_URL=https://pub-<hash>.r2.dev   # only if Step 7 done
```

---

## Step 4: Generate the Better Auth secret

You already have one in your local `.env`. For prod, generate a fresh one:

```sh
openssl rand -hex 32
```

Copy the 64-char hex string. This is `BETTER_AUTH_SECRET` for the API
host (Step 5). Never commit it.

---

## Step 5: Fly.io (host for apps/api)

The API is a Node Hono server. Fly is the simplest free-ish host that
keeps the process alive (Vercel serverless cold-starts hurt Better Auth
session handling, hence not Vercel for this one).

1. Sign up at **<https://fly.io>**. Card required even for free tier.
2. Install the CLI on your laptop:
   ```sh
   curl -L https://fly.io/install.sh | sh
   fly auth login
   ```
3. Create `apps/api/Dockerfile`:
   ```Dockerfile
   FROM node:22-alpine AS base
   RUN corepack enable && corepack prepare pnpm@9.12.0 --activate
   WORKDIR /repo

   FROM base AS deps
   COPY pnpm-lock.yaml pnpm-workspace.yaml package.json ./
   COPY apps/api/package.json apps/api/
   COPY packages/db/package.json packages/db/
   COPY packages/schemas/package.json packages/schemas/
   COPY packages/tsconfig/package.json packages/tsconfig/
   RUN pnpm install --frozen-lockfile --filter api... --ignore-scripts

   FROM deps AS build
   COPY . .
   RUN pnpm --filter api build

   FROM base AS runtime
   ENV NODE_ENV=production
   COPY --from=build /repo/node_modules /repo/node_modules
   COPY --from=build /repo/packages /repo/packages
   COPY --from=build /repo/apps/api/dist /repo/apps/api/dist
   COPY --from=build /repo/apps/api/package.json /repo/apps/api/
   WORKDIR /repo/apps/api
   EXPOSE 3001
   CMD ["node", "dist/index.js"]
   ```
4. Create `apps/api/fly.toml`:
   ```toml
   app = "rsmm-api"
   primary_region = "iad"          # pick one close to Neon's region

   [build]
     dockerfile = "Dockerfile"

   [http_service]
     internal_port = 3001
     force_https = true
     auto_stop_machines = "stop"
     auto_start_machines = true
     min_machines_running = 0

   [[vm]]
     cpu_kind = "shared"
     cpus = 1
     memory_mb = 256
   ```
5. From the repo root:
   ```sh
   fly launch --no-deploy --copy-config --name rsmm-api --region iad --org personal
   ```
6. Set production env vars on Fly:
   ```sh
   fly secrets set \
     DATABASE_URL='postgresql://...neon.tech/rsmm?sslmode=require' \
     DB_DRIVER=neon \
     BETTER_AUTH_SECRET='<from step 4>' \
     BETTER_AUTH_URL='https://rsmm-api.fly.dev' \
     TRUSTED_ORIGINS='https://www.rsmm.dev,https://rsmm.vercel.app,tauri://localhost' \
     S3_BUCKET=rsmm-mods \
     S3_REGION=auto \
     S3_ENDPOINT='https://<account-id>.r2.cloudflarestorage.com' \
     S3_ACCESS_KEY_ID='<from step 3>' \
     S3_SECRET_ACCESS_KEY='<from step 3>' \
     S3_PUBLIC_BASE_URL='https://pub-<hash>.r2.dev'
   ```
7. Deploy:
   ```sh
   fly deploy
   ```
8. Verify:
   ```sh
   curl https://rsmm-api.fly.dev/health
   # → {"ok":true,"ts":...}
   ```

The API is now live at `https://rsmm-api.fly.dev`. Save that URL — Vercel and the desktop app need it.

---

## Step 6: Vercel (host for apps/www)

1. Sign up at **<https://vercel.com>**, GitHub login.
2. Click **Add New → Project**. Pick the `RavenswatchModManager` repo.
3. Vercel detects Next.js. Override these settings:
   - **Root Directory**: `apps/www`
   - **Build Command**: `cd ../.. && pnpm install --frozen-lockfile && pnpm --filter www build`
   - **Install Command**: `pnpm install --filter www...`
   - **Framework Preset**: Next.js
4. **Environment Variables**:
   - `NEXT_PUBLIC_API_URL` = `https://rsmm-api.fly.dev`
5. Click **Deploy**. First build takes ~2 min.
6. Vercel gives you a URL like `rsmm.vercel.app`. Open it. The landing
   page should load; `/auth/signin` should work because it talks to your
   Fly API.

If sign-in fails with CORS errors: go back to Step 5 and make sure your
Vercel URL is in `TRUSTED_ORIGINS`, then `fly deploy` again to pick up
the env change.

---

## Step 7: Cloudflare Pages (host for apps/docs)

1. Back to **<https://dash.cloudflare.com>**, left sidebar → **Workers & Pages → Create application → Pages → Connect to Git**.
2. Pick the `RavenswatchModManager` repo.
3. Build settings:
   - **Production branch**: `main`
   - **Framework preset**: Astro
   - **Build command**: `pnpm install --frozen-lockfile && pnpm --filter docs build`
   - **Build output directory**: `apps/docs/dist`
   - **Root directory**: leave blank (Cloudflare runs build from repo root)
4. **Environment variables** (under Settings → Environment variables):
   - `NODE_VERSION` = `22`
   - `PNPM_VERSION` = `9.12.0`
5. Click **Save and Deploy**.

You'll get a URL like `rsmm-docs.pages.dev`.

---

## Step 8: Custom domain (optional but recommended)

Buy `rsmm.dev` (or whatever) from **Cloudflare Registrar** (cheapest,
no upsells) or Namecheap.

After registering at Cloudflare:

| Subdomain | Points to | How |
|-----------|-----------|-----|
| `rsmm.dev` (apex) | Vercel (www) | Vercel project → Settings → Domains → add `rsmm.dev` → Cloudflare DNS: `A @ 76.76.21.21` |
| `www.rsmm.dev` | Vercel (www) | Vercel adds this automatically with the apex |
| `api.rsmm.dev` | Fly | Fly: `fly certs create api.rsmm.dev` → follow CNAME instructions in Cloudflare DNS |
| `docs.rsmm.dev` | Cloudflare Pages | Pages project → Custom domains → add `docs.rsmm.dev` |
| `cdn.rsmm.dev` | R2 public bucket | R2 bucket → Settings → Custom Domains → `cdn.rsmm.dev` |

After domain is live, update:
- Fly secret `BETTER_AUTH_URL` → `https://api.rsmm.dev`
- Fly secret `TRUSTED_ORIGINS` → `https://rsmm.dev,https://www.rsmm.dev,tauri://localhost`
- Fly secret `S3_PUBLIC_BASE_URL` → `https://cdn.rsmm.dev`
- Vercel env `NEXT_PUBLIC_API_URL` → `https://api.rsmm.dev` + redeploy

---

## Step 9: Desktop app distribution

Tag a release to trigger the `tauri-action` workflow:

```sh
git tag v0.1.0
git push origin v0.1.0
```

GitHub Actions builds installers for Windows / macOS (universal) /
Linux and posts them as a **draft** GitHub Release. Visit the release
page, edit the notes, click **Publish**.

Users download from `github.com/Ovilli/RavenswatchModManager/releases`.

For code signing (Windows SmartScreen / macOS notarization), you'll
need separate paid certs ($99/yr Apple, ~$200/yr Windows). Skip these
until the project has users.

---

## Step 10: Production env summary

When everything is live, this is what each host runs:

**Fly (api.rsmm.dev)**
```
DATABASE_URL=postgresql://...neon.tech/rsmm?sslmode=require
DB_DRIVER=neon
BETTER_AUTH_SECRET=<random 64 hex>
BETTER_AUTH_URL=https://api.rsmm.dev
TRUSTED_ORIGINS=https://rsmm.dev,https://www.rsmm.dev,tauri://localhost
S3_BUCKET=rsmm-mods
S3_REGION=auto
S3_ENDPOINT=https://<account>.r2.cloudflarestorage.com
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
S3_PUBLIC_BASE_URL=https://cdn.rsmm.dev
```

**Vercel (rsmm.dev)**
```
NEXT_PUBLIC_API_URL=https://api.rsmm.dev
```

**Cloudflare Pages (docs.rsmm.dev)**
```
NODE_VERSION=22
PNPM_VERSION=9.12.0
```

**Desktop installer (built by tauri-action)** — talks to whatever
`VITE_API_URL` is baked in at build time. For a release pointing at
prod, add to `.github/workflows/release.yml`:

```yaml
- name: Build desktop
  uses: tauri-apps/tauri-action@v0
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    VITE_API_URL: https://api.rsmm.dev
```

---

## Smoke test checklist

After every step:

- [ ] Step 2: `psql 'postgresql://...neon.tech/...?sslmode=require' -c '\dt'` lists tables
- [ ] Step 3: `curl -X PUT 'https://<endpoint>/rsmm-mods/test.txt' -H 'x-amz-content-sha256: UNSIGNED-PAYLOAD' -H 'authorization: ...'` returns 200 (or use a tool like rclone)
- [ ] Step 5: `curl https://rsmm-api.fly.dev/health` → `{"ok":true}`
- [ ] Step 5: `curl https://rsmm-api.fly.dev/mods` → `{"items":[],"total":0}`
- [ ] Step 6: `curl https://rsmm.vercel.app/` returns HTML
- [ ] Step 6: open `https://rsmm.vercel.app/auth/signup`, create account, check Neon `user` table has row
- [ ] Step 7: open `docs.rsmm.dev` → Starlight site loads

If any step fails, the rest will fail too. Don't skip ahead.

---

## Cost reality check

| Item | Free tier holds up to | Paid trigger |
|------|----------------------|--------------|
| Neon | ~100 active users, 0.5 GB | $19/mo Pro |
| R2 | 10 GB, 10M Class A ops/mo | $0.015/GB after |
| Vercel | 100 GB egress, no commercial use on free | $20/mo Pro |
| Fly | 3 shared-CPU 256MB VMs in trial | $2-5/mo per VM |
| Cloudflare Pages | 500 builds/mo, unlimited bandwidth | rarely paid |
| GitHub Actions | 2000 min/mo private (unlimited public) | $0 for public repos |
| Domain | n/a | $10/yr |

Total for a small launch: **~$0–15/mo + $10/yr domain**.
