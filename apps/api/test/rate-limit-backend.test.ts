import { describe, expect, it, vi } from 'vitest';
import { createRateLimiter, resolveUpstashCredentials } from '../src/rate-limit.js';

/**
 * Which credentials switch the limiter onto its shared backend.
 *
 * Without Upstash, `createRateLimiter` falls back to an in-memory window that
 * is per process, so on a scaled deploy the real limit is `maxHits x
 * instances`. Survivable for reads; not for /api/logs, which stores
 * user-supplied text and relies on its hourly cap to stay a support tool.
 *
 * The trap being pinned here: the Vercel Marketplace integration
 * (`upstash/upstash-kv`) injects KV_REST_API_URL / KV_REST_API_TOKEN, NOT the
 * UPSTASH_REDIS_REST_* names Upstash's own docs use. Reading only the latter
 * means provisioning the integration correctly and still quietly running
 * per-instance — which is exactly what happened on this deploy.
 *
 * The resolver takes an env record rather than reading process.env, so these
 * assertions do not depend on what is in the developer's own .env.local (which
 * `vercel env pull` now populates with the real credentials).
 */
describe('resolveUpstashCredentials', () => {
  it('finds nothing when neither pair is present', () => {
    expect(resolveUpstashCredentials({})).toEqual({ url: '', token: '' });
  });

  it('accepts the names Upstash documents', () => {
    expect(
      resolveUpstashCredentials({
        UPSTASH_REDIS_REST_URL: 'https://x.upstash.io',
        UPSTASH_REDIS_REST_TOKEN: 't',
      }),
    ).toEqual({ url: 'https://x.upstash.io', token: 't' });
  });

  it('accepts the names the Vercel Marketplace integration actually injects', () => {
    expect(
      resolveUpstashCredentials({
        KV_REST_API_URL: 'https://x.upstash.io',
        KV_REST_API_TOKEN: 't',
      }),
    ).toEqual({ url: 'https://x.upstash.io', token: 't' });
  });

  it('prefers an explicit UPSTASH_* value over the integration default', () => {
    const got = resolveUpstashCredentials({
      UPSTASH_REDIS_REST_URL: 'https://explicit.upstash.io',
      UPSTASH_REDIS_REST_TOKEN: 'explicit',
      KV_REST_API_URL: 'https://integration.upstash.io',
      KV_REST_API_TOKEN: 'integration',
    });
    expect(got).toEqual({ url: 'https://explicit.upstash.io', token: 'explicit' });
  });

  it('trims a trailing slash so the request path is not doubled', () => {
    expect(resolveUpstashCredentials({ KV_REST_API_URL: 'https://x.upstash.io/' }).url).toBe(
      'https://x.upstash.io',
    );
  });

  it('never reaches for the read-only token — the limiter INCRs', () => {
    const got = resolveUpstashCredentials({
      KV_REST_API_URL: 'https://x.upstash.io',
      KV_REST_API_READ_ONLY_TOKEN: 'ro',
    });
    // A read-only token would fail every call and disable the limiter in the
    // least obvious way possible, so it must not count as configured.
    expect(got.token).toBe('');
  });
});

describe('createRateLimiter', () => {
  it('falls back to the in-memory window and still limits', async () => {
    const limiter = createRateLimiter({
      name: `mem-${Math.random()}`,
      windowMs: 60_000,
      maxHits: 2,
      keyFrom: () => 'k',
    });
    let blocked = 0;
    const ctx = {
      req: { header: () => undefined },
      header: () => undefined,
      json: () => {
        blocked++;
        return 'blocked' as never;
      },
    };
    for (let i = 0; i < 4; i++) await limiter(ctx as never, async () => undefined);
    // 2 through, 2 refused — the counter is real even without a shared store.
    expect(blocked).toBe(2);
  });
});
