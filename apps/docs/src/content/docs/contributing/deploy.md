---
title: Deployment
description: Provision every external service to host RSMM, step by step.
---

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
| Vercel | Hosting for `apps/www` (Next.js), `apps/api` (Hono/Node), **and** `apps/docs` (Astro/Starlight) — three projects, same repo | yes |
| Domain (rsmm.me or similar) | Friendly URL + email | ~$10/yr |

If money is the issue, everything runs on Vercel's Hobby tier. Skip the
domain for v1 and use the `*.vercel.app` URLs.

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

6. (Optional) **Discord release notifications**:
   - Create a webhook in your Discord server (Server Settings → Integrations → Webhooks).
   - Copy the webhook URL and add it as a repository secret:
     **Settings → Secrets and variables → Actions → New repository secret**
     - Name: `DISCORD_WEBHOOK_URL`
     - Value: `https://discord.com/api/webhooks/...`
   - Tag-driven releases notify Discord from the `finalize-release` job in
     `release.yml` (GitHub does not fire `release: published` for publishes
     done via `GITHUB_TOKEN`). Manual/UI publishes still trigger
     `discord-notify.yml`.

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
secure (1Password, Bitwarden) — you'll paste it into the Vercel env
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

## Step 5: Vercel (host for apps/api)

The API is a Node Hono server, deployed as its own Vercel project.
`apps/api/vercel.json` already pins the install and build commands
(`pnpm --filter api vercel-build`), so the dashboard setup is minimal.

1. Sign up at **<https://vercel.com>**, GitHub login.
2. Go to **<https://vercel.com/new>** and **Import** the
   `RavenswatchModManager` repo as a **new project** (separate from the
   `apps/www` and `apps/docs` projects).
3. In **Configure Project**:
   - **Root Directory**: `apps/api` (click *Edit* → select the folder).
     Vercel still installs the whole pnpm workspace from the repo root.
   - Build Command / Install Command: leave as-is — `vercel.json`
     provides them.
4. **Environment Variables** (Production + Preview):
   ```
   DATABASE_URL=postgresql://...neon.tech/rsmm?sslmode=require
   DB_DRIVER=neon
   BETTER_AUTH_SECRET=<from step 4>
   BETTER_AUTH_URL=https://<your-api-project>.vercel.app
   TRUSTED_ORIGINS=https://www.rsmm.me,https://rsmm.vercel.app,tauri://localhost
   S3_BUCKET=rsmm-mods
   S3_REGION=auto
   S3_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
   S3_ACCESS_KEY_ID=<from step 3>
   S3_SECRET_ACCESS_KEY=<from step 3>
   S3_PUBLIC_BASE_URL=https://pub-<hash>.r2.dev
   UPSTASH_REDIS_REST_URL=https://<db>.upstash.io
   UPSTASH_REDIS_REST_TOKEN=<from the Upstash console>
   ```

   The Upstash pair is easiest to get by provisioning the Marketplace
   integration rather than by hand:

   ```sh
   vercel integration add upstash/upstash-kv --no-claim
   ```

   It provisions a free-tier Redis and injects the credentials into the
   project. Note it injects them as `KV_REST_API_URL` / `KV_REST_API_TOKEN`,
   not under the `UPSTASH_REDIS_REST_*` names Upstash's own docs use — the
   limiter reads both spellings for exactly that reason. Afterwards, delete any
   `apps/api/.env.local` the CLI wrote: Vite bakes those values into the test
   transform, and the suite then talks to production.

   :::caution[Set the Upstash pair before going public]
   Without it, rate limiting falls back to an in-memory window that is
   **per process**. On Vercel that means every concurrently warm instance
   keeps its own counter, so the real limit is `maxHits x instances` — not an
   approximation of the configured limit but an independent copy of it.

   That is survivable for read endpoints. It is not for `/api/logs`, which
   stores up to 150 KB of user-supplied text per accepted call and relies on
   its hourly cap to stay a support tool rather than free file hosting. The
   API logs a warning at boot in production when the pair is missing.
   :::
5. Click **Deploy**.
6. Verify:
   ```sh
   curl https://<your-api-project>.vercel.app/health
   # → {"ok":true,"ts":...}
   ```

The API is now live. Save that URL — the www project and the desktop app
need it. Remember: Vercel does **not** apply env-var changes to a running
deployment — redeploy after every env edit.

---

## Step 5b: Social sign-in (optional — Google / GitHub)

The "Continue with Google" / "Continue with GitHub" buttons are **already
built** into the sign-in and sign-up pages. They stay hidden until the
matching OAuth credentials exist in the API env — `/api/auth-config`
reports which providers are configured and the UI renders only those. No
code change is needed to enable them.

> The callback URL **must** be `<BETTER_AUTH_URL>/api/auth/callback/<provider>`
> where `BETTER_AUTH_URL` is whatever the deployed API actually serves under.
> If the API runs on Vercel (the current setup) at `https://api.rsmm.me`, the
> callback is `https://api.rsmm.me/api/auth/callback/google`. A mismatch here
> is the #1 cause of `Error 400: redirect_uri_mismatch`. Changing
> `BETTER_AUTH_URL` later means updating BOTH the env var *and* the console.

To turn on **Google**:

1. **Google Cloud Console** → *APIs & Services* → *Credentials* →
   *Create Credentials* → *OAuth client ID*. Application type:
   **Web application**.
2. Under **Authorized redirect URIs**, add (must match `BETTER_AUTH_URL`
   exactly — no trailing slash):
   ```
   https://api.rsmm.me/api/auth/callback/google
   ```
   Add a second entry `http://localhost:3001/api/auth/callback/google` if you
   want Google sign-in to work in local dev too — and run the API locally with
   `BETTER_AUTH_URL=http://localhost:3001` so the generated callback matches
   (you can't test locally while `BETTER_AUTH_URL` points at prod).
3. Set the generated client ID + secret on the API host. On **Vercel**:
   Project → Settings → Environment Variables → add `GOOGLE_CLIENT_ID` and
   `GOOGLE_CLIENT_SECRET` (Production + Preview), then **redeploy** — Vercel
   does not apply env changes to the running deployment until you redeploy.
4. After the redeploy, reload `/auth/signin` — the Google button appears once
   `/api/auth-config` reports `google: true`.

**GitHub** is identical: register an OAuth App at
*GitHub → Settings → Developer settings → OAuth Apps*, set the callback to
`https://api.rsmm.me/api/auth/callback/github`, then set
`GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` the same way and redeploy.

Both providers are off by default and safe to skip — email/password
sign-in works without them.

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
   - `NEXT_PUBLIC_API_URL` = `https://<your-api-project>.vercel.app` (from Step 5)
5. Click **Deploy**. First build takes ~2 min.
6. Vercel gives you a URL like `rsmm.vercel.app`. Open it. The landing
   page should load; `/auth/signin` should work because it talks to your
   API project.

If sign-in fails with CORS errors: go back to Step 5 and make sure your
Vercel www URL is in the API project's `TRUSTED_ORIGINS`, then redeploy
the API to pick up the env change.

---

## Step 7: Vercel (host for apps/docs)

The docs are a static Astro/Starlight site. `apps/docs/vercel.json` already
pins the framework, install, build, and output — so the only thing you set in
the dashboard is the **Root Directory**.

1. Go to **<https://vercel.com/new>** and **Import** the `RavenswatchModManager` repo as a **new project** (separate from the `apps/www` project).
2. In **Configure Project**:
   - **Root Directory**: `apps/docs` (click *Edit* → select the folder). Vercel still installs the whole pnpm workspace from the repo root.
   - **Framework Preset**: Astro (auto-detected; `vercel.json` also sets it).
   - Build Command / Output Directory / Install Command: leave as-is — `vercel.json` provides them (`pnpm --filter docs build` → `dist`).
3. Click **Deploy**.

You'll get a URL like `rsmm-docs.vercel.app`.

> The build runs `starlight-links-validator`; a broken internal link **fails the
> deploy**, same as CI. Fix links locally with `pnpm --filter docs build` before
> pushing.

---

## Step 8: Custom domain (optional but recommended)

Buy `rsmm.me` (or whatever) from **Cloudflare Registrar** (cheapest,
no upsells) or Namecheap.

After registering at Cloudflare:

| Subdomain | Points to | How |
|-----------|-----------|-----|
| `rsmm.me` (apex) | Vercel (www) | Vercel project → Settings → Domains → add `rsmm.me` → Cloudflare DNS: `A @ 76.76.21.21` |
| `www.rsmm.me` | Vercel (www) | Vercel adds this automatically with the apex |
| `api.rsmm.me` | Vercel (api) | Vercel api project → Settings → Domains → add `api.rsmm.me` → add the CNAME it shows in your DNS |
| `docs.rsmm.me` | Vercel (docs) | Vercel docs project → Settings → Domains → add `docs.rsmm.me` → add the CNAME it shows in your DNS |
| `cdn.rsmm.me` | R2 public bucket | R2 bucket → Settings → Custom Domains → `cdn.rsmm.me` |

After domain is live, update (api project env, then redeploy the api):
- `BETTER_AUTH_URL` → `https://api.rsmm.me`
- `TRUSTED_ORIGINS` → `https://rsmm.me,https://www.rsmm.me,tauri://localhost`
- `S3_PUBLIC_BASE_URL` → `https://cdn.rsmm.me`
- www project env `NEXT_PUBLIC_API_URL` → `https://api.rsmm.me` + redeploy www

---

## Step 9: Desktop app distribution

Tag a release to trigger the `tauri-action` workflow:

```sh
git tag v0.1.0
git push origin v0.1.0
```

GitHub Actions builds installers for Windows / Linux and posts them as
a **draft** GitHub Release. Visit the release page, edit the notes,
click **Publish**.

Users download from `github.com/Ovilli/RavenswatchModManager/releases`.

For code signing (Windows SmartScreen), you'll need a paid cert
(~$200/yr). Skip it until the project has users.

---

## Step 10: Production env summary

When everything is live, this is what each host runs:

**Vercel (api — api.rsmm.me)**
```
DATABASE_URL=postgresql://...neon.tech/rsmm?sslmode=require
DB_DRIVER=neon
BETTER_AUTH_SECRET=<random 64 hex>
BETTER_AUTH_URL=https://api.rsmm.me
TRUSTED_ORIGINS=https://rsmm.me,https://www.rsmm.me,tauri://localhost
S3_BUCKET=rsmm-mods
S3_REGION=auto
S3_ENDPOINT=https://<account>.r2.cloudflarestorage.com
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
S3_PUBLIC_BASE_URL=https://cdn.rsmm.me
```

**Vercel (rsmm.me)**
```
NEXT_PUBLIC_API_URL=https://api.rsmm.me
```

**Vercel (docs — docs.rsmm.me)**

No environment variables required — the docs site is fully static. Vercel
auto-selects a recent Node version; pin it under Settings → General → Node.js
Version if you want to match CI (22).

**Desktop installer (built by tauri-action)** — talks to whatever
`VITE_API_URL` is baked in at build time. For a release pointing at
prod, add to `.github/workflows/release.yml`:

```yaml
- name: Build desktop
  uses: tauri-apps/tauri-action@v0
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    VITE_API_URL: https://api.rsmm.me
```

---

## Smoke test checklist

After every step:

- [ ] Step 2: `psql 'postgresql://...neon.tech/...?sslmode=require' -c '\dt'` lists tables
- [ ] Step 3: `curl -X PUT 'https://<endpoint>/rsmm-mods/test.txt' -H 'x-amz-content-sha256: UNSIGNED-PAYLOAD' -H 'authorization: ...'` returns 200 (or use a tool like rclone)
- [ ] Step 5: `curl https://<your-api-project>.vercel.app/health` → `{"ok":true}`
- [ ] Step 5: `curl https://<your-api-project>.vercel.app/mods` → `{"items":[],"total":0}`
- [ ] Step 6: `curl https://rsmm.vercel.app/` returns HTML
- [ ] Step 6: open `https://rsmm.vercel.app/auth/signup`, create account, check Neon `user` table has row
- [ ] Step 7: open `docs.rsmm.me` → Starlight site loads

If any step fails, the rest will fail too. Don't skip ahead.

---

## Cost reality check

| Item | Free tier holds up to | Paid trigger |
|------|----------------------|--------------|
| Neon | ~100 active users, 0.5 GB | $19/mo Pro |
| R2 | 10 GB, 10M Class A ops/mo | $0.015/GB after |
| Vercel (www + api) | 100 GB egress, no commercial use on free | $20/mo Pro |
| Vercel (docs) | static, shares the Vercel Hobby free tier | $20/mo Pro |
| GitHub Actions | 2000 min/mo private (unlimited public) | $0 for public repos |
| Domain | n/a | $10/yr |

Total for a small launch: **~$0–15/mo + $10/yr domain**.