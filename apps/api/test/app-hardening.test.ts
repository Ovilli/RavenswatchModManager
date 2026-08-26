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
  }),
  schema: new Proxy({}, { get: () => new Proxy({}, { get: () => 'col' }) }),
}));

const { app } = await import('../src/app.js');

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
