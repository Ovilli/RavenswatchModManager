import { Hono } from 'hono';
import { describe, expect, it, vi } from 'vitest';
import type { AppEnv } from '../src/types.js';

process.env.DATABASE_URL ??= 'postgres://user:pass@localhost:5432/db';
process.env.BETTER_AUTH_SECRET ??= 'x'.repeat(32);

const state = vi.hoisted(() => ({ where: [] as unknown[] }));
const hidden = {
  slug: 'hidden-mod',
  name: 'Hidden mod',
  author: 'someone',
  ownerId: 'owner',
  takedownStatus: 'hidden',
  takedownReason: 'Uses the game logo.',
  updatedAt: new Date('2026-11-21T00:00:00Z'),
};

vi.mock('@rsmm/db', async (importOriginal) => {
  const original = await importOriginal<typeof import('@rsmm/db')>();
  const chain = (result: unknown) => {
    const promise = Promise.resolve(result) as Promise<unknown> & Record<string, unknown>;
    promise.where = (cond: unknown) => {
      state.where.push(cond);
      return chain(result);
    };
    for (const key of ['orderBy', 'limit']) promise[key] = () => chain(result);
    return promise;
  };
  return { ...original, getDb: () => ({ select: () => ({ from: () => chain([hidden]) }) }) };
});
vi.mock('../src/admin.js', () => ({ isAdmin: (id?: string | null) => id === 'admin' }));
const { moderationRouter } = await import('../src/routes/moderation.js');

function get(userId: string | null) {
  const app = new Hono<AppEnv>();
  app.use('*', async (c, next) => {
    c.set('user', userId ? { id: userId, name: userId, email: `${userId}@example.com` } : null);
    await next();
  });
  app.route('/api/moderation', moderationRouter);
  return app.request('/api/moderation/mods/takedowns');
}

describe('GET /api/moderation/mods/takedowns', () => {
  it('is admin-only', async () => {
    expect((await get(null)).status).toBe(401);
    expect((await get('someone')).status).toBe(403);
  });

  it('lists taken-down mods with their reason', async () => {
    state.where.length = 0;
    const res = await get('admin');
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({
      items: [{ ...hidden, updatedAt: '2026-11-21T00:00:00.000Z' }],
    });
    expect(state.where).toHaveLength(1);
  });
});
