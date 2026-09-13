import { describe, expect, it, vi } from 'vitest';

/**
 * Personal API tokens. Two layers:
 *
 * 1. The pure rules in api-tokens.ts — token shape, hashing, and above all the
 *    ROUTE ALLOWLIST, which is what limits a leaked token to publishing.
 * 2. The session middleware wired to them, with the DB lookup stubbed: a token
 *    must be looked up on the publish routes only, and must never authenticate
 *    anything else — least of all the routes that mint or revoke tokens.
 */
process.env.DATABASE_URL ??= 'postgres://user:pass@localhost:5432/db';
process.env.BETTER_AUTH_SECRET ??= 'x'.repeat(32);

const { bearerToken, generateToken, hashToken, isTokenRoute, TOKEN_PREFIX } = await import(
  '../src/api-tokens.js'
);

const SCAN = '/api/mods/versions/0b8f5f5e-3c1a-4f7e-9a0b-6d2c8e1f4a77/scan';

describe('token format', () => {
  it('is a 256-bit random secret behind a fixed prefix, stored only as its SHA-256', () => {
    const a = generateToken();
    const b = generateToken();
    expect(a.token).toMatch(/^rsmm_pat_[A-Za-z0-9_-]{43}$/);
    expect(a.token).not.toBe(b.token);
    expect(a.hash).toBe(hashToken(a.token));
    expect(a.hash).toMatch(/^[0-9a-f]{64}$/);
    // The display prefix is too short to be the secret.
    expect(a.prefix.startsWith(TOKEN_PREFIX)).toBe(true);
    expect(a.prefix.length).toBeLessThan(a.token.length / 2);
  });

  it('only a well-formed Bearer token is recognised', () => {
    const { token } = generateToken();
    expect(bearerToken(`Bearer ${token}`)).toBe(token);
    expect(bearerToken(`bearer ${token}`)).toBeNull();
    expect(bearerToken(token)).toBeNull();
    expect(bearerToken(`Bearer ${token.slice(0, -1)}`)).toBeNull();
    expect(bearerToken('Bearer test-cron-secret')).toBeNull();
    expect(bearerToken(null)).toBeNull();
  });
});

describe('route allowlist', () => {
  it('admits exactly the publish flow', () => {
    expect(isTokenRoute('GET', '/api/me')).toBe(true);
    expect(isTokenRoute('POST', '/api/mods/upload')).toBe(true);
    expect(isTokenRoute('POST', SCAN)).toBe(true);
    expect(isTokenRoute('GET', `${SCAN}-status`)).toBe(true);
  });

  it.each([
    ['POST', '/api/me/tokens'],
    ['GET', '/api/me/tokens'],
    ['DELETE', '/api/me/tokens/0b8f5f5e-3c1a-4f7e-9a0b-6d2c8e1f4a77'],
    ['PATCH', '/api/me/privacy'],
    ['GET', '/api/mods/upload'],
    ['DELETE', '/api/mods/my-mod'],
    ['PATCH', '/api/mods/my-mod/edit'],
    ['POST', '/api/mods/versions/not-a-uuid/scan'],
    ['POST', '/api/mods/upload/../../me/tokens'],
    ['POST', '/api/moderation/reports'],
    ['POST', '/api/auth/change-password'],
  ])('refuses %s %s', (method, path) => {
    expect(isTokenRoute(method, path)).toBe(false);
  });
});

// ─── middleware ───────────────────────────────────────────────────────────

const lookup = vi.fn();
vi.mock('../src/api-token-auth.js', () => ({ resolveTokenUser: lookup }));
vi.mock('@rsmm/db', () => ({
  getDb: () => ({
    select: () => ({
      from: () => ({ where: () => ({ limit: () => Promise.resolve([]) }) }),
    }),
  }),
  schema: new Proxy({}, { get: () => new Proxy({}, { get: () => 'col' }) }),
}));

const { app } = await import('../src/app.js');

const USER = { id: 'user-1', name: 'Modder', email: 'm@example.com', emailVerified: true };

describe('session middleware with a token', () => {
  it('authenticates a live token on a publish route', async () => {
    lookup.mockReset();
    lookup.mockResolvedValue({ user: USER, tokenId: 'tok-1' });
    const { token } = generateToken();
    const res = await app.request('/api/me', { headers: { authorization: `Bearer ${token}` } });
    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ id: 'user-1', name: 'Modder' });
    expect(lookup).toHaveBeenCalledWith(token);
  });

  it('never looks a token up off the allowlist, so it cannot mint tokens', async () => {
    lookup.mockReset();
    lookup.mockResolvedValue({ user: USER, tokenId: 'tok-1' });
    const { token } = generateToken();
    const res = await app.request('/api/me/tokens', {
      method: 'POST',
      headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json' },
      body: JSON.stringify({ name: 'escalate', expiresInDays: 365 }),
    });
    expect(res.status).toBe(401);
    expect(lookup).not.toHaveBeenCalled();
  });

  it('stays anonymous when the token is unknown, revoked or expired', async () => {
    lookup.mockReset();
    lookup.mockResolvedValue(null);
    const { token } = generateToken();
    const res = await app.request('/api/me', { headers: { authorization: `Bearer ${token}` } });
    expect(res.status).toBe(401);
  });
});
