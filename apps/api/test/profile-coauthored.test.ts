import { Hono } from 'hono';
import { describe, expect, it, vi } from 'vitest';

process.env.DATABASE_URL ??= 'postgres://user:pass@localhost:5432/db';
process.env.BETTER_AUTH_SECRET ??= 'x'.repeat(32);

const row = (slug: string, ownerId: string, downloads: number, ownerPublicCounts = true) => ({
  id: slug,
  slug,
  name: slug,
  summary: null,
  license: null,
  updatedAt: new Date('2026-11-01T00:00:00Z'),
  category: null,
  authorName: null,
  imageUrl: null,
  rating: null,
  tags: [],
  featured: false,
  ownerId,
  ownerPublicCounts,
  latestVersion: '1.0.0',
  downloads,
});
const rows = [row('own', 'pam', 10), row('team', 'ovilli', 7), row('hidden', 'shy', 5, false)];

vi.mock('@rsmm/db', () => ({
  getDb: () => ({
    query: {
      users: {
        findFirst: async () => ({
          id: 'pam',
          name: 'Pam',
          handle: null,
          image: null,
          publicProfile: true,
          publicDownloadCounts: true,
        }),
      },
    },
    select: () => ({ from: () => ({ where: () => ({ orderBy: async () => rows }) }) }),
  }),
  schema: new Proxy({}, { get: () => new Proxy({}, { get: () => 'col' }) }),
}));
vi.mock('../src/admin.js', () => ({ isAdmin: () => false }));

const { usersRouter } = await import('../src/routes/users.js');

async function profile(viewer: string | null) {
  const app = new Hono();
  app.use('*', async (c, next) => {
    c.set('user' as never, (viewer ? { id: viewer } : null) as never);
    await next();
  });
  app.route('/api/users', usersRouter);
  return (await (await app.request('/api/users/pam')).json()) as {
    mods: { slug: string; role: string; downloads: number | null }[];
    totalDownloads: number | null;
  };
}

describe('a profile lists the mods its user co-authors', () => {
  it('marks each mod owner or co-author', async () => {
    const body = await profile(null);
    expect(body.mods.map((m) => [m.slug, m.role])).toEqual([
      ['own', 'owner'],
      ['team', 'coauthor'],
      ['hidden', 'coauthor'],
    ]);
  });

  it("follows each co-authored mod's OWNER for download privacy", async () => {
    const body = await profile(null);
    expect(body.mods.find((m) => m.slug === 'team')?.downloads).toBe(7);
    expect(body.mods.find((m) => m.slug === 'hidden')?.downloads).toBeNull();
    // that mod's own owner still sees its figure on someone else's profile
    const shy = await profile('shy');
    expect(shy.mods.find((m) => m.slug === 'hidden')?.downloads).toBe(5);
  });

  it('totals only the mods the user owns', async () => {
    expect((await profile(null)).totalDownloads).toBe(10);
  });
});
