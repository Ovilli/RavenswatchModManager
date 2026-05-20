# Security

## Supply-chain audit

Every `pnpm install` in CI is followed by `pnpm audit:supply-chain`,
which runs `scripts/audit-supply-chain.mjs`. It scans `pnpm-lock.yaml`
against a baked-in list of known-compromised `package@version` pairs
and exits non-zero on any hit.

`pnpm install` in CI uses `--ignore-scripts`. Lifecycle scripts run
only after the audit gate passes (`pnpm rebuild`). This prevents a
compromised tarball's `prepare`/`postinstall` from executing before
the audit notices it.

### Updating the known-bad list

When a new advisory is published:

1. Identify affected `package@version` pairs from the GHSA or vendor advisory.
2. Append them to `KNOWN_BAD` in `scripts/audit-supply-chain.mjs`.
3. Add a `# Source:` comment with the GHSA / CVE / blog URL.
4. Run `pnpm audit:supply-chain` locally — it must pass before committing.

### Current baked-in advisories

| ID | Date | Packages | Notes |
|---|---|---|---|
| [GHSA-g7cv-rxg3-hmpx](https://github.com/advisories/GHSA-g7cv-rxg3-hmpx) | 2026-05-11 | 42 `@tanstack/*` packages, 84 versions | TanStack supply-chain incident. `@tanstack/query*`, `@tanstack/table*`, `@tanstack/form*`, `@tanstack/virtual*`, `@tanstack/store`, `@tanstack/start` (meta) confirmed clean. |

## Incident response — if the audit fails

Treat the install host as potentially compromised. Even a partial
install of a malicious tarball can run the `prepare` lifecycle script
before npm/pnpm errors out.

1. **Stop.** Do not run further `pnpm`/`npm`/`yarn` commands on the host.
2. **Rotate credentials reachable from the host** — AWS, GCP, Kubernetes,
   Vault, GitHub, npm, SSH. (Per GHSA-g7cv-rxg3-hmpx, the exfil channel
   is the Session/Oxen messenger network at `filev2.getsession.org` /
   `seed{1,2,3}.getsession.org`. End-to-end encrypted, so DNS/IP blocks
   are the only network mitigation.)
3. **Audit dotfiles** that contained credentials:
   - `~/.npmrc`
   - `~/.git-credentials`
   - `~/.aws/credentials`
   - `~/.kube/config`
   - `~/.ssh/`
4. **Wipe and reinstall** the workspace:
   ```sh
   rm -rf node_modules pnpm-lock.yaml
   pnpm store prune
   pnpm install --ignore-scripts
   pnpm audit:supply-chain
   pnpm rebuild
   ```
5. **Check your maintained npm packages** — the GHSA-g7cv-rxg3-hmpx
   malware self-propagates by republishing other packages owned by the
   victim. Verify with `npm view <pkg> versions --json` that no
   unexpected version was published from your account.

## Threat model — what RSMM ships

The desktop app (`apps/desktop`) is a Tauri 2 shell. It executes the
`rsmm` Python CLI as a sidecar with a narrowly scoped allow-list in
`src-tauri/capabilities/default.json`. The webview cannot execute
arbitrary shell commands; only `rsmm <args>` invocations are permitted.

The API (`apps/api`) trusts only the origins enumerated in
`TRUSTED_ORIGINS`. Better Auth sessions are HTTP-only cookies; the
client sends them via `credentials: 'include'`.

The signed-PUT upload flow (`/mods/upload`) only issues URLs to
authenticated users and requires `x-amz-checksum-sha256` matching the
declared body hash — the storage backend rejects mismatched uploads.

## Reporting a vulnerability

Email `security@rsmm.dev` (or, until that is provisioned, open a
private security advisory on the GitHub repo). Do not file public
issues for security reports.
