import { describe, expect, it, vi } from 'vitest';

/**
 * Contract of the shared-log endpoints, tested without a database.
 *
 * The invariants worth pinning here are the ones a refactor can silently
 * break: the id has to be unguessable (it is the only thing protecting an
 * unlisted log), an expired row must not be served just because the daily
 * purge has not run yet, and deletion must require the owning account rather
 * than mere possession of the link.
 */
process.env.DATABASE_URL ??= 'postgres://user:pass@localhost:5432/db';
process.env.BETTER_AUTH_SECRET ??= 'x'.repeat(32);
process.env.WEB_URL = 'https://example.test';

const inserted: Record<string, unknown>[] = [];
let storedRow: Record<string, unknown> | null = null;

vi.mock('@rsmm/db', () => ({
  getDb: () => ({
    // Reached by the session middleware in app.ts.
    select: () => ({ from: () => ({ where: () => ({ limit: () => Promise.resolve([]) }) }) }),
    insert: () => ({
      values: (v: Record<string, unknown>) => {
        inserted.push(v);
        return Promise.resolve();
      },
    }),
    update: () => ({ set: () => ({ where: () => Promise.resolve() }) }),
    delete: () => ({ where: () => ({ returning: () => Promise.resolve([]) }) }),
    query: { sharedLogs: { findFirst: () => Promise.resolve(storedRow) } },
  }),
  schema: new Proxy({}, { get: () => new Proxy({}, { get: () => 'col' }) }),
}));

const { app } = await import('../src/app.js');

const body = (over: Record<string, unknown> = {}) => ({
  content: 'boot\ncrash',
  source: 'loader',
  rsmmVersion: '5.1.3',
  os: 'windows',
  ...over,
});

const post = (payload: unknown) =>
  app.request('/api/logs', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });

describe('POST /api/logs', () => {
  it('stores the text and answers a link on the configured web origin', async () => {
    const res = await post(body());
    expect(res.status).toBe(200);
    const json = (await res.json()) as { id: string; url: string; expiresAt: string };
    // 72 bits of base64url. A sequential or short id would make every
    // unlisted log enumerable.
    expect(json.id).toMatch(/^[A-Za-z0-9_-]{12}$/);
    expect(json.url).toBe(`https://example.test/l/${json.id}`);
    expect(new Date(json.expiresAt).getTime()).toBeGreaterThan(Date.now());
    // Derived server-side, never trusted from the client.
    expect(inserted.at(-1)).toMatchObject({ lineCount: 2, bytes: 10, userId: null });
  });

  it('rejects text over the stored-size cap instead of truncating it', async () => {
    const res = await post(body({ content: 'x'.repeat(150_001) }));
    expect(res.status).toBe(400);
  });

  it('rate-limits anonymous uploads — this endpoint is otherwise free hosting', async () => {
    // Proves the limiter is actually MOUNTED on the route, which a wrong
    // middleware path would silently skip. Runs last: the in-memory window is
    // module-global, so it spends the budget the earlier cases share.
    let sawLimit = false;
    for (let i = 0; i < 12 && !sawLimit; i++) {
      sawLimit = (await post(body())).status === 429;
    }
    expect(sawLimit).toBe(true);
  });
});

describe('GET /api/logs/:id', () => {
  it('404s a malformed id without touching the database', async () => {
    storedRow = null;
    expect((await app.request('/api/logs/not!a!slug')).status).toBe(404);
  });

  it('serves a live share', async () => {
    storedRow = {
      id: 'abcdefghijkl',
      source: 'loader',
      rsmmVersion: '5.1.3',
      os: 'windows',
      content: 'boot',
      meta: null,
      lineCount: 1,
      bytes: 4,
      createdAt: new Date(),
      expiresAt: new Date(Date.now() + 60_000),
    };
    const res = await app.request('/api/logs/abcdefghijkl');
    expect(res.status).toBe(200);
    expect((await res.json()) as { content: string }).toMatchObject({ content: 'boot' });
  });

  it('410s a row whose TTL passed, without waiting for the purge cron', async () => {
    storedRow = {
      id: 'abcdefghijkl',
      source: 'loader',
      rsmmVersion: '5.1.3',
      os: 'windows',
      content: 'boot',
      meta: null,
      lineCount: 1,
      bytes: 4,
      createdAt: new Date(Date.now() - 120_000),
      expiresAt: new Date(Date.now() - 60_000),
    };
    expect((await app.request('/api/logs/abcdefghijkl')).status).toBe(410);
  });
});

describe('DELETE /api/logs/:id', () => {
  it('requires an account — holding the link must not authorise deletion', async () => {
    const res = await app.request('/api/logs/abcdefghijkl', { method: 'DELETE' });
    expect(res.status).toBe(401);
  });
});
