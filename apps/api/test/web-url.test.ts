import { describe, expect, it, vi } from 'vitest';

/**
 * The origin every user-facing link the API hands out is built from.
 *
 * The localhost default is right in dev and actively wrong in production, and
 * it fails silently: the API answers 200 and hands the user
 * http://localhost:3000/l/<id>, a link that works on nobody's machine but the
 * developer's. That shipped in 5.2.0 — WEB_URL was simply never set on the
 * deploy — so production now treats a missing or localhost value as the
 * misconfiguration it is.
 */
async function loadEnv(vars: Record<string, string | undefined>) {
  vi.resetModules();
  const saved = { ...process.env };
  process.env.DATABASE_URL ??= 'postgres://user:pass@localhost:5432/db';
  process.env.BETTER_AUTH_SECRET ??= 'x'.repeat(32);
  for (const [k, v] of Object.entries(vars)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  try {
    return (await import('../src/env.js')).env;
  } finally {
    process.env = saved;
  }
}

describe('env.webUrl', () => {
  it('keeps the localhost default in development', async () => {
    const env = await loadEnv({ NODE_ENV: 'development', WEB_URL: undefined });
    expect(env.webUrl).toBe('http://localhost:3000');
  });

  it('honours an explicit WEB_URL', async () => {
    const env = await loadEnv({ NODE_ENV: 'production', WEB_URL: 'https://staging.example' });
    expect(env.webUrl).toBe('https://staging.example');
  });

  it('refuses to hand out a localhost link in production', async () => {
    const missing = await loadEnv({ NODE_ENV: 'production', WEB_URL: undefined });
    expect(missing.webUrl).toBe('https://rsmm.me');
    // A developer's shell leaking into the deploy is the same failure as the
    // var never being set at all.
    const leaked = await loadEnv({ NODE_ENV: 'production', WEB_URL: 'http://localhost:3000' });
    expect(leaked.webUrl).toBe('https://rsmm.me');
    const loopback = await loadEnv({ NODE_ENV: 'production', WEB_URL: 'http://127.0.0.1:3000' });
    expect(loopback.webUrl).toBe('https://rsmm.me');
  });
});
