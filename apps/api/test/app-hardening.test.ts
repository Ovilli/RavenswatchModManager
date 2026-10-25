import { describe, expect, it, vi } from 'vitest';

/**
 * Middleware-level guarantees that are easy to delete by accident and silent
 * when they break: the response hardening headers, the request body cap, and
 * the cron endpoint's constant-time secret check. No database or game binary
 * needed — the DB module is stubbed, matching scan-gate.test.ts's approach of
 * testing a security invariant in isolation.
 */
process.env.DATABASE_URL ??= 'postgres://user:pass@localhost:5432/db';
process.env.BETTER_AUTH_SECRET ??= 'x'.repeat(32);
process.env.CRON_SECRET = 'test-cron-secret';

// Minimal stand-in for the query builder: every chain the middleware under
// test can reach ends in a resolved empty result set. Returning a real promise
// (rather than a hand-made thenable) keeps `.then().catch()` working as the
// session middleware expects.
vi.mock('@rsmm/db', () => ({
  getDb: () => ({
    select: () => ({
      from: () => ({ where: () => ({ limit: () => Promise.resolve([]) }) }),
    }),
    update: () => ({ set: () => ({ where: () => Promise.resolve([]) }) }),
  }),
  schema: new Proxy({}, { get: () => new Proxy({}, { get: () => 'col' }) }),
}));

const { app, isCdnCacheablePath } = await import('../src/app.js');

describe('response hardening headers', () => {
  it('are present on every response', async () => {
    const res = await app.request('/api/health');
    expect(res.status).toBe(200);
    expect(res.headers.get('x-content-type-options')).toBe('nosniff');
    expect(res.headers.get('x-frame-options')).toBe('DENY');
    expect(res.headers.get('referrer-policy')).toBe('strict-origin-when-cross-origin');
    expect(res.headers.get('strict-transport-security')).toContain('max-age=31536000');
    expect(res.headers.get('cross-origin-resource-policy')).toBe('same-site');
    expect(res.headers.get('permissions-policy')).toContain('camera=()');
  });

  it('include a CSP that denies framing and every default fetch', async () => {
    const csp = (await app.request('/api/health')).headers.get('content-security-policy') ?? '';
    expect(csp).toContain("default-src 'none'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("base-uri 'none'");
    expect(csp).toContain("form-action 'none'");
  });
});

describe('request body cap', () => {
  it('rejects a body over 1 MB with 413 instead of parsing it', async () => {
    const res = await app.request('/api/telemetry/run', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ pad: 'x'.repeat(2 * 1024 * 1024) }),
    });
    expect(res.status).toBe(413);
    expect(await res.json()).toEqual({ error: 'request body too large' });
  });

  it('lets an ordinary small body through to its handler', async () => {
    // Reaches validation (422) rather than the body limit — proves the cap is
    // not simply rejecting everything.
    const res = await app.request('/api/telemetry/run', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ nonsense: true }),
    });
    expect(res.status).not.toBe(413);
  });
});

describe('cron secret check', () => {
  it('rejects a wrong secret of the same length', async () => {
    const wrong = 'Bearer test-cron-secreX';
    expect(wrong).toHaveLength('Bearer test-cron-secret'.length);
    const res = await app.request('/api/cron/scan-drain', {
      headers: { authorization: wrong },
    });
    expect(res.status).toBe(401);
  });

  it('rejects a wrong secret of a different length', async () => {
    const res = await app.request('/api/cron/scan-drain', {
      headers: { authorization: 'Bearer test-cron-secret-with-more-text' },
    });
    expect(res.status).toBe(401);
  });

  it('rejects a missing authorization header', async () => {
    expect((await app.request('/api/cron/scan-drain')).status).toBe(401);
  });
});

describe('CDN cache for viewer-independent reads', () => {
  const CDN = 'vercel-cdn-cache-control';

  it('marks a public read cacheable without varying on Cookie', async () => {
    // Vercel's CDN will not cache a response that varies on Cookie, so the
    // header must never reappear on a cacheable route.
    const res = await app.request('/api/auth-config');
    expect(res.status).toBe(200);
    expect(res.headers.get(CDN)).toContain('max-age=60');
    expect(res.headers.get('vary') ?? '').not.toMatch(/cookie/i);
  });

  it('caches the same body for a signed-in request (route is viewer-independent)', async () => {
    const res = await app.request('/api/auth-config', {
      headers: { cookie: 'better-auth.session_token=x' },
    });
    expect(res.headers.get(CDN)).toContain('max-age=60');
  });

  it('leaves routes off the allowlist uncached', async () => {
    expect((await app.request('/api/health')).headers.get(CDN)).toBeNull();
    expect((await app.request('/api/session')).headers.get(CDN)).toBeNull();
  });

  it('allowlists only viewer-independent reads', () => {
    for (const p of [
      '/api/mods',
      '/api/collections',
      '/api/guides',
      '/api/legal/impressum',
      '/api/auth-config',
    ]) {
      expect(isCdnCacheablePath(p), p).toBe(true);
    }
    // Detail pages read the viewer (owner/admin view, canManage, isFollowing).
    for (const p of [
      '/api/mods/camera-control',
      '/api/mods/camera-control/reviews',
      '/api/users/abc',
      '/api/collections/x',
      '/api/collections/x/reviews',
      '/api/guides/x',
      '/api/guides/x/reviews',
      '/api/mods/x/1.0.0/download',
      '/api/mods/x/authors',
      '/api/collections/mine',
      '/api/guides/mine',
      '/api/me',
      '/api/logs/abc',
      '/api/session',
    ]) {
      expect(isCdnCacheablePath(p), p).toBe(false);
    }
  });

  it('answers preflights with a max-age so browsers stop repeating them', async () => {
    const res = await app.request('/api/mods', {
      method: 'OPTIONS',
      headers: {
        origin: 'http://localhost:3000',
        'access-control-request-method': 'GET',
      },
    });
    expect(res.headers.get('access-control-max-age')).toBe('86400');
  });
});

describe('review-email unsubscribe link', () => {
  it('rejects a forged token and accepts the real one', async () => {
    const { unsubscribeToken } = await import('../src/notify.js');
    const bad = await app.request('/api/unsubscribe?u=user-1&t=forged');
    expect(bad.status).toBe(400);
    const other = await app.request(`/api/unsubscribe?u=user-2&t=${unsubscribeToken('user-1')}`);
    expect(other.status).toBe(400);
    const ok = await app.request(`/api/unsubscribe?u=user-1&t=${unsubscribeToken('user-1')}`, {
      method: 'POST',
    });
    expect(ok.status).toBe(200);
  });
});
