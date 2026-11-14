import { Hono } from 'hono';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AppEnv } from '../src/types.js';

process.env.DATABASE_URL ??= 'postgres://user:pass@localhost:5432/db';
process.env.BETTER_AUTH_SECRET ??= 'x'.repeat(32);

const state = vi.hoisted(() => ({
  userId: null as string | null,
  exists: true,
  isPublic: true,
  writes: [] as { operation: string; values?: Record<string, unknown> }[],
}));
const now = new Date('2026-11-14T00:00:00Z');
const mod = {
  id: '00000000-0000-4000-8000-000000000001',
  slug: 'sample',
  ownerId: 'owner',
  name: 'Sample mod',
  authorName: 'Original author',
  takedownStatus: 'active',
  tags: [],
  versions: [],
  updatedAt: now,
};
const collection = () => ({
  ...mod,
  name: 'Sample collection',
  isPublic: state.isPublic,
  createdAt: now,
});

vi.mock('@rsmm/db', async (importOriginal) => {
  const original = await importOriginal<typeof import('@rsmm/db')>();
  const chain = (result: unknown) => {
    const promise = Promise.resolve(result) as Promise<unknown> & Record<string, unknown>;
    for (const key of [
      'where',
      'innerJoin',
      'orderBy',
      'groupBy',
      'limit',
      'returning',
      'onConflictDoNothing',
    ]) {
      promise[key] = () => chain(result);
    }
    return promise;
  };
  return {
    ...original,
    getDb: () => ({
      query: {
        mods: { findFirst: async () => (state.exists ? mod : undefined) },
        collections: { findFirst: async () => (state.exists ? collection() : undefined) },
        users: { findFirst: async () => ({ publicDownloadCounts: true }) },
      },
      select: () => ({
        from: (table: unknown) =>
          chain(
            table === original.schema.collections
              ? state.exists
                ? [collection()]
                : []
              : table === original.schema.modAuthors && state.userId === 'coauthor'
                ? [{ userId: 'coauthor' }]
                : [],
          ),
      }),
      update: () => ({
        set: (values: Record<string, unknown>) => {
          state.writes.push({ operation: 'update', values });
          return chain([{ ...mod, ...values }]);
        },
      }),
      insert: () => ({
        values: (values: Record<string, unknown>) => {
          state.writes.push({ operation: 'insert', values });
          return chain([]);
        },
      }),
      delete: () => {
        state.writes.push({ operation: 'delete' });
        return chain([]);
      },
    }),
  };
});
vi.mock('../src/admin.js', () => ({ isAdmin: (id?: string | null) => id === 'admin' }));
vi.mock('../src/env.js', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../src/env.js')>()),
  s3Configured: () => true,
}));
const presign = vi.fn(async () => ({
  uploadUrl: 'https://example.com/upload',
  publicUrl: 'https://example.com/photo.png',
  expiresIn: 900,
}));
vi.mock('../src/storage.js', () => ({ presignModImage: presign, presignCollectionImage: presign }));
vi.mock('../src/rate-limit.js', () => ({
  createRateLimiter: () => async (_c: unknown, next: () => Promise<void>) => next(),
}));
const { modsRouter } = await import('../src/routes/mods.js');
const { collectionsRouter } = await import('../src/routes/collections.js');

function request(userId: string | null, path: string, method = 'GET', body?: unknown) {
  state.userId = userId;
  const app = new Hono<AppEnv>();
  app.use('*', async (c, next) => {
    c.set('user', userId ? { id: userId, name: userId, email: `${userId}@example.com` } : null);
    await next();
  });
  app.route('/api/mods', modsRouter);
  app.route('/api/collections', collectionsRouter);
  return app.request(`/api/${path}`, {
    method,
    headers: { 'content-type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

beforeEach(() => {
  state.userId = null;
  state.exists = true;
  state.isPublic = true;
  state.writes = [];
  presign.mockClear();
});

const editRoutes = [
  {
    path: 'mods/sample/edit',
    method: 'PATCH',
    body: { name: 'Edited mod', author: 'Original author', imageUrl: null, screenshots: [] },
    coauthor: true,
  },
  {
    path: 'mods/sample/image',
    method: 'POST',
    body: { contentType: 'image/png', sizeBytes: 100 },
    coauthor: true,
  },
  {
    path: 'collections/sample',
    method: 'PATCH',
    body: { name: 'Edited collection', imageUrl: null, screenshots: [], isPublic: false },
    coauthor: false,
  },
  {
    path: 'collections/sample/image',
    method: 'POST',
    body: { contentType: 'image/png', sizeBytes: 100 },
    coauthor: false,
  },
  { path: 'collections/sample/mods', method: 'POST', body: { modSlug: 'sample' }, coauthor: false },
  { path: 'collections/sample/mods/sample', method: 'DELETE', body: undefined, coauthor: false },
];

describe('admin listing edits', () => {
  for (const route of editRoutes) {
    it(`${route.method} ${route.path} allows admins and existing editors only`, async () => {
      for (const [user, status] of [
        [null, 401],
        ['stranger', 403],
        ['coauthor', route.coauthor ? 200 : 403],
        ['owner', 200],
        ['admin', 200],
      ] as const) {
        state.writes = [];
        presign.mockClear();
        const response = await request(user, route.path, route.method, route.body);
        expect(response.status, `${user}: ${await response.text()}`).toBe(status);
        if (status !== 200) {
          expect(state.writes).toHaveLength(0);
          expect(presign).not.toHaveBeenCalled();
        } else {
          expect(state.writes.length + presign.mock.calls.length).toBeGreaterThan(0);
          for (const write of state.writes)
            expect(write.values ?? {}).not.toHaveProperty('ownerId');
        }
      }
    });

    it(`${route.method} ${route.path} returns 404 for a missing listing`, async () => {
      state.exists = false;
      expect((await request('admin', route.path, route.method, route.body)).status).toBe(404);
      expect(state.writes).toHaveLength(0);
      expect(presign).not.toHaveBeenCalled();
    });
  }

  it('reports editing permission separately from mod authorship', async () => {
    for (const [user, canEdit, isAuthor] of [
      [null, false, false],
      ['stranger', false, false],
      ['owner', true, true],
      ['coauthor', true, true],
      ['admin', true, false],
    ] as const) {
      const response = await request(user, 'mods/sample');
      expect(response.status).toBe(200);
      expect(await response.json()).toMatchObject({ mod: { canEdit, isAuthor, ownerId: 'owner' } });
    }
  });

  it('reports collection editing permission for owners and admins', async () => {
    for (const user of [null, 'stranger', 'coauthor', 'owner', 'admin']) {
      const response = await request(user, 'collections/sample');
      expect(response.status).toBe(200);
      expect(await response.json()).toMatchObject({
        canEdit: user === 'owner' || user === 'admin',
        ownerId: 'owner',
      });
    }
  });

  it('lets only the owner and admins read a private collection and its reviews', async () => {
    state.isPublic = false;
    for (const path of ['collections/sample', 'collections/sample/reviews']) {
      for (const user of [null, 'stranger', 'coauthor', 'owner', 'admin']) {
        expect((await request(user, path)).status).toBe(
          user === 'owner' || user === 'admin' ? 200 : 404,
        );
      }
    }
  });

  it('does not grant admins ownership or author reply permissions', async () => {
    const reviewId = '00000000-0000-4000-8000-000000000002';
    for (const [path, method, body] of [
      ['mods/sample/delete', 'DELETE', undefined],
      ['collections/sample', 'DELETE', undefined],
      ['mods/sample/authors', 'POST', { handle: 'another-author' }],
      [`mods/sample/reviews/${reviewId}/reply`, 'PUT', { body: 'Reply' }],
      [`collections/sample/reviews/${reviewId}/reply`, 'PUT', { body: 'Reply' }],
    ] as const) {
      expect((await request('admin', path, method, body)).status).toBe(403);
    }
    expect(state.writes).toHaveLength(0);
  });

  it('ignores forged ownership and capability fields in edits', async () => {
    for (const path of ['mods/sample/edit', 'collections/sample']) {
      expect(
        (
          await request('admin', path, 'PATCH', {
            name: 'Edited',
            ownerId: 'admin',
            canEdit: true,
            isAuthor: true,
          })
        ).status,
      ).toBe(200);
    }
    expect(state.writes).toHaveLength(2);
    for (const write of state.writes)
      expect(write.values).toEqual({ name: 'Edited', updatedAt: expect.any(Date) });
  });
});
