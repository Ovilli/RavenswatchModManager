#!/usr/bin/env node
/**
 * Lockfile audit: fails (exit 1) if any installed dependency matches a
 * known-compromised package@version from a baked-in supply-chain advisory
 * list. Run on every CI install and pre-publish.
 *
 * Sources:
 *   - GHSA-g7cv-rxg3-hmpx (TanStack supply-chain incident, 2026-05-11)
 *
 * Update procedure: when a new advisory is published, append entries to
 * KNOWN_BAD below as `package@version` strings.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const lockfilePath = resolve(__dirname, '..', 'pnpm-lock.yaml');

// GHSA-g7cv-rxg3-hmpx (TanStack, 2026-05-11). Two versions per package,
// published ~6 min apart. Source of truth:
// https://github.com/advisories/GHSA-g7cv-rxg3-hmpx
const KNOWN_BAD = new Set([
  '@tanstack/arktype-adapter@1.166.12',
  '@tanstack/arktype-adapter@1.166.15',
  '@tanstack/eslint-plugin-router@1.161.9',
  '@tanstack/eslint-plugin-router@1.161.12',
  '@tanstack/eslint-plugin-start@0.0.4',
  '@tanstack/eslint-plugin-start@0.0.7',
  '@tanstack/history@1.161.9',
  '@tanstack/history@1.161.12',
  '@tanstack/nitro-v2-vite-plugin@1.154.12',
  '@tanstack/nitro-v2-vite-plugin@1.154.15',
  '@tanstack/react-router@1.169.5',
  '@tanstack/react-router@1.169.8',
  '@tanstack/react-router-devtools@1.166.16',
  '@tanstack/react-router-devtools@1.166.19',
  '@tanstack/react-router-ssr-query@1.166.15',
  '@tanstack/react-router-ssr-query@1.166.18',
  '@tanstack/react-start@1.167.68',
  '@tanstack/react-start@1.167.71',
  '@tanstack/react-start-client@1.166.51',
  '@tanstack/react-start-client@1.166.54',
  '@tanstack/react-start-rsc@0.0.47',
  '@tanstack/react-start-rsc@0.0.50',
  '@tanstack/react-start-server@1.166.55',
  '@tanstack/react-start-server@1.166.58',
  '@tanstack/router-cli@1.166.46',
  '@tanstack/router-cli@1.166.49',
  '@tanstack/router-core@1.169.5',
  '@tanstack/router-core@1.169.8',
  '@tanstack/router-devtools@1.166.16',
  '@tanstack/router-devtools@1.166.19',
  '@tanstack/router-devtools-core@1.167.6',
  '@tanstack/router-devtools-core@1.167.9',
  '@tanstack/router-generator@1.166.45',
  '@tanstack/router-generator@1.166.48',
  '@tanstack/router-plugin@1.167.38',
  '@tanstack/router-plugin@1.167.41',
  '@tanstack/router-ssr-query-core@1.168.3',
  '@tanstack/router-ssr-query-core@1.168.6',
  '@tanstack/router-utils@1.161.11',
  '@tanstack/router-utils@1.161.14',
  '@tanstack/router-vite-plugin@1.166.53',
  '@tanstack/router-vite-plugin@1.166.56',
  '@tanstack/solid-router@1.169.5',
  '@tanstack/solid-router@1.169.8',
  '@tanstack/solid-router-devtools@1.166.16',
  '@tanstack/solid-router-devtools@1.166.19',
  '@tanstack/solid-router-ssr-query@1.166.15',
  '@tanstack/solid-router-ssr-query@1.166.18',
  '@tanstack/solid-start@1.167.65',
  '@tanstack/solid-start@1.167.68',
  '@tanstack/solid-start-client@1.166.50',
  '@tanstack/solid-start-client@1.166.53',
  '@tanstack/solid-start-server@1.166.54',
  '@tanstack/solid-start-server@1.166.57',
  '@tanstack/start-client-core@1.168.5',
  '@tanstack/start-client-core@1.168.8',
  '@tanstack/start-fn-stubs@1.161.9',
  '@tanstack/start-fn-stubs@1.161.12',
  '@tanstack/start-plugin-core@1.169.23',
  '@tanstack/start-plugin-core@1.169.26',
  '@tanstack/start-server-core@1.167.33',
  '@tanstack/start-server-core@1.167.36',
  '@tanstack/start-static-server-functions@1.166.44',
  '@tanstack/start-static-server-functions@1.166.47',
  '@tanstack/start-storage-context@1.166.38',
  '@tanstack/start-storage-context@1.166.41',
  '@tanstack/valibot-adapter@1.166.12',
  '@tanstack/valibot-adapter@1.166.15',
  '@tanstack/virtual-file-routes@1.161.10',
  '@tanstack/virtual-file-routes@1.161.13',
  '@tanstack/vue-router@1.169.5',
  '@tanstack/vue-router@1.169.8',
  '@tanstack/vue-router-devtools@1.166.16',
  '@tanstack/vue-router-devtools@1.166.19',
  '@tanstack/vue-router-ssr-query@1.166.15',
  '@tanstack/vue-router-ssr-query@1.166.18',
  '@tanstack/vue-start@1.167.61',
  '@tanstack/vue-start@1.167.64',
  '@tanstack/vue-start-client@1.166.46',
  '@tanstack/vue-start-client@1.166.49',
  '@tanstack/vue-start-server@1.166.50',
  '@tanstack/vue-start-server@1.166.53',
  '@tanstack/zod-adapter@1.166.12',
  '@tanstack/zod-adapter@1.166.15',
]);

let text;
try {
  text = readFileSync(lockfilePath, 'utf8');
} catch (err) {
  console.error(`error: cannot read pnpm-lock.yaml at ${lockfilePath}`);
  console.error(err.message);
  process.exit(2);
}

// Match pnpm v9 lockfile package keys, e.g.
//   '@tanstack/react-router@1.169.5':
//   '@tanstack/react-router@1.169.5(react-dom@19.0.0)':
const installed = new Set();
const re = /^\s*'?([@\w./\-]+)@([\w.+\-]+)(?:\([^)]*\))*'?:/gm;
for (const m of text.matchAll(re)) {
  installed.add(`${m[1]}@${m[2]}`);
}

const hits = [];
for (const id of installed) {
  if (KNOWN_BAD.has(id)) hits.push(id);
}

if (hits.length === 0) {
  console.log(`audit ok: scanned ${installed.size} installed packages, no compromised versions.`);
  process.exit(0);
}

console.error('COMPROMISED PACKAGES DETECTED IN pnpm-lock.yaml:');
for (const id of hits) console.error(`  ${id}`);
console.error('');
console.error('Treat install host as potentially compromised:');
console.error('  1. Delete node_modules + pnpm-lock.yaml');
console.error('  2. Rotate AWS, GCP, Kubernetes, Vault, GitHub, npm, SSH credentials');
console.error('  3. Audit ~/.npmrc, ~/.git-credentials, ~/.ssh for unexpected changes');
console.error('  4. Reinstall with a known-good version range');
process.exit(1);
