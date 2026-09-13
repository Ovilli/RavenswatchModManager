// Personal API tokens — non-interactive publishing from the CLI.
//
// Security model, in one place:
//
// * A token is 32 random bytes (256 bits) behind a fixed prefix. Brute force is
//   not a concern at that entropy, so the stored form is a plain SHA-256: it is
//   one-way and a lookup is a single unique-index probe (no per-row compare, so
//   nothing to time). The plaintext is returned once, at creation.
// * A token is honoured on the PUBLISH endpoints only (`TOKEN_ROUTES`). On every
//   other route a request carrying one is anonymous: a leaked token can upload a
//   version of its owner's mods — which still has to pass the malware scan before
//   anyone can download it — but it cannot read the account, change a password,
//   delete a mod, create or list tokens, or moderate.
// * Tokens are minted and revoked from a signed-in session only, so a stolen
//   token cannot mint a replacement or undo its own revocation.
// * Every token expires (max 365 days) and a user holds at most
//   `MAX_ACTIVE_TOKENS`. A banned or (in production) unverified owner's tokens
//   stop working on the next request, the same gate the session middleware
//   applies.
//
// The pure pieces (format, hashing, route allowlist) are dependency-free so the
// invariants can be unit-tested without a database — see test/api-tokens.test.ts.

import { createHash, randomBytes } from 'node:crypto';

export const TOKEN_PREFIX = 'rsmm_pat_';
/** 32 bytes as unpadded base64url is exactly 43 characters. */
const TOKEN_RE = /^rsmm_pat_[A-Za-z0-9_-]{43}$/;
export const MAX_ACTIVE_TOKENS = 10;
export const MAX_TOKEN_DAYS = 365;
/** Characters of the plaintext kept for display (prefix + a few random chars). */
const DISPLAY_CHARS = TOKEN_PREFIX.length + 6;

/** A fresh token: the plaintext (show once), its hash and its display prefix. */
export function generateToken(): { token: string; hash: string; prefix: string } {
  const token = TOKEN_PREFIX + randomBytes(32).toString('base64url');
  return { token, hash: hashToken(token), prefix: token.slice(0, DISPLAY_CHARS) };
}

export function hashToken(token: string): string {
  return createHash('sha256').update(token, 'utf8').digest('hex');
}

/**
 * The token in an `Authorization` header, or null. Only a well-formed
 * `Bearer rsmm_pat_…` counts — anything else (a session, another scheme, a
 * truncated paste) is not a token and is ignored rather than looked up.
 */
export function bearerToken(header: string | null | undefined): string | null {
  if (!header) return null;
  const m = /^Bearer\s+(\S+)$/.exec(header.trim());
  const token = m?.[1];
  return token && TOKEN_RE.test(token) ? token : null;
}

const UUID = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';

/** Exactly the requests a token may authenticate. Anchored, method-bound. */
export const TOKEN_ROUTES: ReadonlyArray<{ method: string; path: RegExp }> = [
  // Who am I — lets the CLI verify a token before packing anything.
  { method: 'GET', path: /^\/api\/me\/?$/ },
  // Presign an upload (creates the mod on first publish; owner-checked).
  { method: 'POST', path: /^\/api\/mods\/upload\/?$/ },
  // Finalize + queue the malware scan, then poll it.
  { method: 'POST', path: new RegExp(`^/api/mods/versions/${UUID}/scan/?$`) },
  { method: 'GET', path: new RegExp(`^/api/mods/versions/${UUID}/scan-status/?$`) },
];

export function isTokenRoute(method: string, path: string): boolean {
  const m = method.toUpperCase();
  return TOKEN_ROUTES.some((r) => r.method === m && r.path.test(path));
}
