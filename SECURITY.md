# Security policy

## Reporting a vulnerability

Please **don't** open a public issue. Report it privately instead:

- [Open a private security advisory](https://github.com/Ravenswatch-Modding/RavenswatchModManager/security/advisories/new), or
- email [contact@rsmm.me](mailto:contact@rsmm.me) with "security" in the subject.

Include what you found, how to reproduce it and which part is affected (desktop app,
CLI, loader, rsmm.me or the API). We'll acknowledge within a few days and keep you
updated until it's fixed.

## Scope

- The desktop app and its updater, the `rsmm` CLI, the Lua loader (`winhttp.dll`).
- rsmm.me, its API and the mod registry, including the upload scan pipeline.
- Mod archives that escape their sandbox (path traversal, writes outside the game
  folder, code that runs without the loader).

Only the latest release is supported. How RSMM treats mods as untrusted input is
described in the [security reference](https://docs.rsmm.me/reference/security/).

## Review focus

Mods, uploads and registry metadata are untrusted input. A PR review treats any of
the following as P0 or P1.

**Mod archives and install** (`src/rsmm/cli/cmd_install.py`, `cmd_pack.py`,
`update_cmd.py`, `src/rsmm/engine/loader_update.py`)

- Extraction that trusts member names. Every path must resolve inside the target
  folder; `..`, absolute paths, drive letters and symlinks are rejected before
  anything is written.
- Writes outside the game folder or the mods folder, or a write to
  `<game>/_Save/`.
- A downloaded loader or CLI that is installed without checking its signature.

**Desktop app** (`apps/desktop/src-tauri/`)

- Any widening of `capabilities/default.json`: a new `shell:allow-execute` or
  `shell:allow-spawn` entry, a looser argument scope, or a new plugin permission.
  The webview may only run `rsmm <args>`.
- Building a sidecar argument from mod or registry text without validating it.
- Changes to updater endpoints or the updater public key in `tauri.conf.json`.

**API and registry** (`apps/api/`; access model in `apps/api/SECURITY.md`)

- A mutation route that skips the `ownerId === user.id` check, or an admin route
  that skips `ADMIN_USER_IDS`.
- A route added to `TOKEN_ROUTES` in `src/api-tokens.ts`, or a token path that can
  mint or revoke tokens. Tokens are minted and revoked from a cookie session only.
- Storing, logging or returning a token's plaintext after creation, or a user's
  email in a public response.
- A version that becomes downloadable without passing the scan gate
  (`src/scan-gate.ts`).
- A `createRateLimiter` without a unique `name`, or a sensitive route with no limiter.
- An S3 key built from anything other than the validated slug, or a presign that
  drops the content-type, length or checksum pin.
- Secrets read from anywhere but `src/env.ts`, or an `apps/api/.env.local` added
  to the tree.

**Website** (`apps/www/`)

- New HTML reaching `dangerouslySetInnerHTML` from anything except
  `lib/markdown.ts`, or a change to that module without a test in its suite.

**Loader** (`src/loader/`)

- A Lua primitive that reads or writes memory without the page guard, or a new
  primitive exposed to mod Lua.

**CI and releases** (`.github/workflows/`, `scripts/audit-supply-chain.mjs`)

- `pnpm install` without `--ignore-scripts`, or lifecycle scripts running before
  `pnpm audit:supply-chain`.
- A workflow that exposes the signing secret to a `pull_request` run from a fork,
  uses `pull_request_target` with a checkout of the PR head, or interpolates
  `${{ github.event.* }}` text straight into a `run:` step.
