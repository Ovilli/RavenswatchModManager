import { Hono } from 'hono';
import { beforeEach, describe, expect, it, vi } from 'vitest';

process.env.DATABASE_URL ??= 'postgres://user:pass@localhost:5432/db';
process.env.BETTER_AUTH_SECRET ??= 'x'.repeat(32);

const state = vi.hoisted(() => ({
  tags: ['qol', 'private-only'] as string[],
  updates: [] as Record<string, unknown>[],
  conflicts: [] as Record<string, unknown>[],
  exists: true,
}));
const mod = () => ({ id: 'sample-id', slug: 'sample', ownerId: 'owner', tags: state.tags });

vi.mock('@rsmm/db', () => {
  const db = {
    query: { mods: { findFirst: async () => (state.exists ? mod() : undefined) } },
    select: () => ({ from: () => ({ where: () => ({ for: async () => [mod()] }) }) }),
    update: () => ({
      set: (values: Record<string, unknown>) => {
        state.updates.push(values);
        return { where: () => ({ returning: async () => (state.exists ? [mod()] : []) }) };
      },
    }),
    insert: () => ({
      values: () => ({
        onConflictDoUpdate: ({ set }: { set: Record<string, unknown> }) => {
          state.conflicts.push(set);
          return { returning: async () => [mod()] };
        },
      }),
    }),
    transaction: async (run: (tx: unknown) => Promise<unknown>) => run(db),
  };
  return {
    getDb: () => db,
    schema: new Proxy({}, { get: () => new Proxy({}, { get: () => 'col' }) }),
  };
});
vi.mock('../src/admin.js', () => ({ isAdmin: (id: string) => id === 'admin' }));
vi.mock('../src/env.js', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../src/env.js')>()),
  s3Configured: () => true,
  virusTotalConfigured: () => false,
}));
vi.mock('../src/storage.js', () => ({
  presignModUpload: async () => ({
    uploadUrl: 'https://example.com/upload',
    publicUrl: 'https://example.com/mod.zip',
    expiresIn: 900,
  }),
}));
vi.mock('../src/rate-limit.js', () => ({
  createRateLimiter: () => async (_c: unknown, next: () => Promise<void>) => next(),
}));
vi.mock('../src/mod-access.js', () => ({
  canManageMod: async (_mod: unknown, userId: string) => ['owner', 'coauthor'].includes(userId),
}));

const { modsRouter } = await import('../src/routes/mods.js');
const { moderationRouter } = await import('../src/routes/moderation.js');

function request(userId: string | null, path: string, body: unknown, method = 'PATCH') {
  const app = new Hono();
  app.use('*', async (c, next) => {
    c.set('user' as never, (userId ? { id: userId } : null) as never);
    c.set('log' as never, { error: vi.fn() } as never);
    await next();
  });
  app.route('/api/mods', modsRouter);
  app.route('/api/moderation', moderationRouter);
  return app.request(path, {
    method,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  state.tags = ['qol', 'private-only'];
  state.updates = [];
  state.conflicts = [];
  state.exists = true;
});

describe('Private games only permission boundary', () => {
  it('lets owners and coauthors add the label, but not strangers or anonymous users', async () => {
    state.tags = ['qol'];
    for (const [user, status] of [
      [null, 401],
      ['stranger', 403],
      ['owner', 200],
      ['coauthor', 200],
    ] as const) {
      expect(
        (await request(user, '/api/mods/sample/edit', { tags: ['qol', 'private-only'] })).status,
      ).toBe(status);
    }
    expect(state.updates).toHaveLength(2);
  });

  it('rejects owner and coauthor removal, including legacy labels, without writing other edits', async () => {
    for (const tag of [
      'private-only',
      'Private only',
      'Private games only',
      'private-games-only',
      ' CHEAT ',
      'Cheats',
    ]) {
      state.tags = ['qol', tag];
      for (const user of ['owner', 'coauthor']) {
        const response = await request(user, '/api/mods/sample/edit', {
          tags: [],
          summary: 'Changed',
        });
        expect(response.status).toBe(403);
        expect(await response.json()).toEqual({
          error: 'Only RSMM admins can remove the Private games only label.',
        });
      }
    }
    expect(state.updates).toHaveLength(0);
  });

  it('allows unrelated listing edits without rewriting the protected tag', async () => {
    expect((await request('owner', '/api/mods/sample/edit', { summary: 'Changed' })).status).toBe(
      200,
    );
    expect(state.updates[0]).not.toHaveProperty('tags');
    expect(
      (await request('owner', '/api/mods/sample/edit', { tags: ['cosmetic', 'private-only'] }))
        .status,
    ).toBe(200);
  });

  it('allows only RSMM admins to use the removal endpoint, even when not the owner', async () => {
    for (const [user, status] of [
      [null, 401],
      ['owner', 403],
      ['coauthor', 403],
      ['stranger', 403],
      ['admin', 200],
    ] as const) {
      expect(
        (await request(user, '/api/moderation/mods/sample/private-only', { privateOnly: false }))
          .status,
      ).toBe(status);
    }
    expect(state.updates).toHaveLength(1);
  });

  it('validates admin changes and reports missing mods', async () => {
    expect(
      (await request('admin', '/api/moderation/mods/sample/private-only', { privateOnly: 'false' }))
        .status,
    ).toBe(400);
    expect(state.updates).toHaveLength(0);
    state.exists = false;
    expect(
      (await request('admin', '/api/moderation/mods/sample/private-only', { privateOnly: false }))
        .status,
    ).toBe(404);
  });

  it('keeps omitted upload tags unchanged and guards explicit replacements at write time', async () => {
    for (const tags of [undefined, ['qol']]) {
      const response = await request(
        'owner',
        '/api/mods/upload',
        {
          slug: 'sample',
          version: '1.0.0',
          sha256: 'a'.repeat(64),
          sizeBytes: 100,
          manifest: { id: 'sample', name: 'Sample', version: '1.0.0', tags },
        },
        'POST',
      );
      expect(response.status).toBe(200);
      const update = state.conflicts.at(-2);
      if (tags === undefined) expect(update).not.toHaveProperty('tags');
      else expect(update?.tags).toHaveProperty('queryChunks');
    }
  });

  it('lets a co-author upload a version without taking the mod, and refuses a stranger', async () => {
    const upload = (userId: string) =>
      request(
        userId,
        '/api/mods/upload',
        {
          slug: 'sample',
          version: '1.0.1',
          sha256: 'b'.repeat(64),
          sizeBytes: 100,
          manifest: { id: 'sample', name: 'Sample', version: '1.0.1' },
        },
        'POST',
      );
    expect((await upload('coauthor')).status).toBe(200);
    // the mod row's update never names an owner: a co-author's upload must not
    // hand the mod to them (the old upsert set ownerId to the uploader)
    for (const set of state.conflicts) expect(set).not.toHaveProperty('ownerId');
    const refused = await upload('stranger');
    expect(refused.status).toBe(403);
    expect(((await refused.json()) as { error: string }).error).toMatch(/co-author/);
  });

  it('preserves the label on a new version and lets a release declare it without replacing other tags', async () => {
    for (const tags of [undefined, ['qol'], ['Private games only']]) {
      const response = await request(
        'coauthor',
        '/api/mods/sample/versions',
        {
          version: '1.0.0',
          sha256: 'a'.repeat(64),
          sizeBytes: 100,
          manifest: { id: 'sample', name: 'Sample', version: '1.0.0', tags },
        },
        'POST',
      );
      expect(response.status).toBe(200);
      const update = state.updates.at(-1);
      if (tags?.includes('Private games only')) expect(update?.tags).toHaveProperty('queryChunks');
      else expect(update).not.toHaveProperty('tags');
    }
  });
});
