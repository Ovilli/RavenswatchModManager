import { Hono } from 'hono';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AppEnv } from '../src/types.js';

process.env.DATABASE_URL ??= 'postgres://user:pass@localhost:5432/db';
process.env.BETTER_AUTH_SECRET ??= 'x'.repeat(32);

const state = vi.hoisted(() => ({
  inserts: [] as Record<string, unknown>[],
  notified: [] as { userId: string; type: string; email?: string | null }[],
  coAuthors: [{ userId: 'coauthor' }] as { userId: string }[],
  modStatus: 'hidden',
  rows: [] as unknown[],
}));
const mod = { id: 'mod-1', slug: 'sample', name: 'Sample', ownerId: 'owner' };
const row = {
  id: 'm1',
  kind: 'status',
  body: 'Uses the game logo.',
  fromStatus: 'active',
  toStatus: 'hidden',
  fromModerator: true,
  createdAt: new Date('2026-11-21T00:00:00Z'),
  authorId: 'admin',
  authorName: 'Admin',
  authorImage: null,
};

vi.mock('@rsmm/db', async (importOriginal) => {
  const original = await importOriginal<typeof import('@rsmm/db')>();
  const chain = (result: unknown) => {
    const p = Promise.resolve(result) as Promise<unknown> & Record<string, unknown>;
    for (const k of ['where', 'leftJoin', 'orderBy', 'limit', 'returning'])
      p[k] = () => chain(result);
    return p;
  };
  return {
    ...original,
    getDb: () => ({
      query: {
        mods: {
          findFirst: async () => ({
            ...mod,
            takedownStatus: state.modStatus,
            takedownReason: 'Old reason',
            updatedAt: new Date('2026-11-20T00:00:00Z'),
          }),
        },
        users: { findFirst: async () => ({ email: 'owner@example.com' }) },
      },
      select: () => ({
        from: (table: unknown) =>
          chain(table === original.schema.modAuthors ? state.coAuthors : state.rows),
      }),
      insert: () => ({
        values: (v: Record<string, unknown>) => {
          state.inserts.push(v);
          return chain([{ id: 'new', ...v, ...mod, takedownStatus: v.toStatus }]);
        },
      }),
      update: () => ({
        set: (v: Record<string, unknown>) => chain([{ ...mod, ...v }]),
      }),
    }),
  };
});
vi.mock('../src/admin.js', () => ({ isAdmin: (id?: string | null) => id === 'admin' }));
vi.mock('../src/mod-access.js', () => ({
  canManageMod: async (_m: unknown, id: string) => id === 'owner' || id === 'coauthor',
}));
vi.mock('../src/notify.js', () => ({
  notify: async (n: { userId: string; type: string; email?: string | null }) => {
    state.notified.push(n);
  },
}));
vi.mock('../src/rate-limit.js', () => ({
  createRateLimiter: () => async (_c: unknown, next: () => Promise<void>) => next(),
}));
const { modModerationRouter } = await import('../src/routes/mod-moderation.js');
const { moderationRouter } = await import('../src/routes/moderation.js');

function call(userId: string | null, path: string, method = 'GET', body?: unknown) {
  const app = new Hono<AppEnv>();
  app.use('*', async (c, next) => {
    c.set('user', userId ? { id: userId, name: userId, email: `${userId}@example.com` } : null);
    await next();
  });
  app.route('/api/mods', modModerationRouter);
  app.route('/api/moderation', moderationRouter);
  return app.request(path, {
    method,
    headers: { 'content-type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

beforeEach(() => {
  state.inserts.length = 0;
  state.notified.length = 0;
  state.modStatus = 'hidden';
  state.rows = [row];
});

describe('mod moderation thread', () => {
  it('is only readable by the team and moderators', async () => {
    expect((await call(null, '/api/mods/sample/moderation')).status).toBe(401);
    expect((await call('stranger', '/api/mods/sample/moderation')).status).toBe(404);
    for (const id of ['owner', 'coauthor', 'admin']) {
      const res = await call(id, '/api/mods/sample/moderation');
      expect(res.status).toBe(200);
      const json = (await res.json()) as { viewerIsModerator: boolean; items: unknown[] };
      expect(json.viewerIsModerator).toBe(id === 'admin');
      expect(json.items).toEqual([{ ...row, createdAt: '2026-11-21T00:00:00.000Z' }]);
    }
  });

  it('shows a takedown that predates the thread as its opening entry', async () => {
    state.rows = [];
    const res = await call('owner', '/api/mods/sample/moderation');
    const json = (await res.json()) as { items: Record<string, unknown>[] };
    expect(json.items).toEqual([
      expect.objectContaining({
        kind: 'status',
        toStatus: 'hidden',
        body: 'Old reason',
        fromModerator: true,
        createdAt: '2026-11-20T00:00:00.000Z',
      }),
    ]);
  });

  it('a moderator message notifies the whole team, emailing only the owner', async () => {
    const res = await call('admin', '/api/mods/sample/moderation', 'POST', { body: 'Hi' });
    expect(res.status).toBe(200);
    expect(state.inserts).toEqual([
      expect.objectContaining({ kind: 'message', body: 'Hi', fromModerator: true }),
    ]);
    expect(state.notified.map((n) => [n.userId, n.email ?? null]).sort()).toEqual([
      ['coauthor', null],
      ['owner', 'owner@example.com'],
    ]);
  });

  it('a team message notifies nobody', async () => {
    const res = await call('owner', '/api/mods/sample/moderation', 'POST', { body: 'Fixed it' });
    expect(res.status).toBe(200);
    expect(state.inserts).toEqual([expect.objectContaining({ fromModerator: false })]);
    expect(state.notified).toEqual([]);
  });

  it('rejects strangers and empty messages', async () => {
    expect(
      (await call('stranger', '/api/mods/sample/moderation', 'POST', { body: 'x' })).status,
    ).toBe(404);
    expect(
      (await call('owner', '/api/mods/sample/moderation', 'POST', { body: '  ' })).status,
    ).toBe(400);
  });

  it('a takedown records the status change in the thread', async () => {
    state.modStatus = 'active';
    const res = await call('admin', '/api/moderation/mods/sample/takedown', 'POST', {
      takedownStatus: 'hidden',
      reason: 'Uses the game logo.',
    });
    expect(res.status).toBe(200);
    expect(state.inserts).toEqual([
      expect.objectContaining({
        kind: 'status',
        fromStatus: 'active',
        toStatus: 'hidden',
        body: 'Uses the game logo.',
        authorId: 'admin',
        fromModerator: true,
      }),
    ]);
  });

  it('a restore records the change and tells the owner', async () => {
    const res = await call('admin', '/api/moderation/mods/sample/takedown', 'POST', {
      takedownStatus: 'active',
    });
    expect(res.status).toBe(200);
    expect(state.inserts).toEqual([
      expect.objectContaining({
        kind: 'status',
        fromStatus: 'hidden',
        toStatus: 'active',
        body: null,
      }),
    ]);
    expect(state.notified).toEqual([expect.objectContaining({ userId: 'owner' })]);
  });
});
