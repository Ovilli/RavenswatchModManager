import { Hono } from 'hono';
import { beforeEach, describe, expect, it, vi } from 'vitest';

process.env.DATABASE_URL ??= 'postgres://user:pass@localhost:5432/db';
process.env.BETTER_AUTH_SECRET ??= 'x'.repeat(32);

const state = vi.hoisted(() => ({ updates: [] as Record<string, unknown>[] }));
const mod = { id: 'sample-id', slug: 'sample', ownerId: 'owner', authorName: 'Original' };

vi.mock('@rsmm/db', () => ({
  getDb: () => ({
    query: { mods: { findFirst: async () => mod } },
    update: () => ({
      set: (values: Record<string, unknown>) => {
        state.updates.push(values);
        return { where: () => ({ returning: async () => [{ ...mod, ...values }] }) };
      },
    }),
  }),
  schema: new Proxy({}, { get: () => new Proxy({}, { get: () => 'col' }) }),
}));
vi.mock('../src/rate-limit.js', () => ({
  createRateLimiter: () => async (_c: unknown, next: () => Promise<void>) => next(),
}));
vi.mock('../src/mod-access.js', () => ({
  canManageMod: async (_mod: unknown, userId: string) =>
    userId === 'owner' || userId === 'coauthor',
}));

const { modsRouter } = await import('../src/routes/mods.js');

function patch(userId: string | null, body: Record<string, unknown>) {
  const app = new Hono();
  app.use('*', async (c, next) => {
    c.set('user' as never, (userId ? { id: userId } : null) as never);
    await next();
  });
  app.route('/api/mods', modsRouter);
  return app.request('/api/mods/sample/edit', {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  state.updates = [];
});

describe('author credit edits', () => {
  it('requires sign-in and permission to manage the mod', async () => {
    expect((await patch(null, { author: 'Updated' })).status).toBe(401);
    expect((await patch('stranger', { author: 'Updated' })).status).toBe(403);
    expect(state.updates).toHaveLength(0);
  });

  it('lets owners and coauthors change credit without changing ownership', async () => {
    for (const userId of ['owner', 'coauthor']) {
      const response = await patch(userId, { author: ' New credit ', ownerId: 'other' });
      expect(response.status).toBe(200);
      expect(await response.json()).toMatchObject({
        mod: { authorName: 'New credit', ownerId: 'owner' },
      });
    }
    expect(state.updates).toEqual([
      { authorName: 'New credit', updatedAt: expect.any(Date) },
      { authorName: 'New credit', updatedAt: expect.any(Date) },
    ]);
  });

  it('clears explicit null but preserves credit when editing another field', async () => {
    expect((await patch('owner', { author: null })).status).toBe(200);
    expect(state.updates[0]).toMatchObject({ authorName: null });
    expect((await patch('owner', { summary: 'Changed summary' })).status).toBe(200);
    expect(state.updates[1]).not.toHaveProperty('authorName');
  });

  it('rejects invalid credit before writing', async () => {
    for (const author of ['', '   ', 'a'.repeat(129)]) {
      expect((await patch('owner', { author })).status).toBe(400);
    }
    expect(state.updates).toHaveLength(0);
  });
});
