import { PRIVATE_ONLY_TAG_ALIASES } from '@rsmm/schemas';
import { beforeEach, describe, expect, it, vi } from 'vitest';

process.env.DATABASE_URL ??= 'postgres://user:pass@localhost:5432/db';
process.env.BETTER_AUTH_SECRET ??= 'x'.repeat(32);

const state = vi.hoisted(() => ({ queries: [] as { text: string; params: unknown[] }[] }));

// Compile and execute the real route's queries against a read-only recording client.
vi.mock('@rsmm/db', async (importOriginal) => {
  const original = await importOriginal<typeof import('@rsmm/db')>();
  const { drizzle } = await import('drizzle-orm/node-postgres');
  const db = drizzle({
    client: {
      query: async (query: { text: string }, params: unknown[]) => {
        state.queries.push({ text: query.text, params });
        return { rows: [] };
      },
    } as never,
  });
  return { ...original, getDb: () => db };
});

const { modsRouter } = await import('../src/routes/mods.js');

beforeEach(() => {
  state.queries = [];
});

describe('private-only browse preference', () => {
  it.each(['1', 'true'])(
    'excludes private tags in results, totals, and both facets (%s)',
    async (value) => {
      const response = await modsRouter.request(
        `/?hidePrivateOnly=${value}&facets=1&limit=2&offset=4&tags=hero&category=cosmetic&minRating=4`,
      );
      expect(response.status).toBe(200);
      expect(state.queries).toHaveLength(4);
      for (const query of state.queries) {
        expect(query.text).toMatch(/not exists\s*\(\s*select 1 from unnest\(/);
        expect(query.text).toContain('lower(btrim(private_tag.name))');
        expect(query.params).toEqual(expect.arrayContaining(PRIVATE_ONLY_TAG_ALIASES));
      }
      // Exclusion is in SQL before pagination, and composes with other filters.
      const rows = state.queries[0];
      expect(rows?.text).toMatch(/not exists[\s\S]*limit \$\d+ offset \$\d+/);
      expect(rows?.params.slice(-2)).toEqual([2, 4]);
      for (const query of state.queries.slice(0, 2)) {
        expect(query.params).toEqual(expect.arrayContaining(['hero', 'cosmetic', 4]));
      }
      for (const query of state.queries.slice(2)) {
        expect(query.params).not.toContain('hero');
        expect(query.params).not.toContain('cosmetic');
      }
    },
  );

  it.each(['', '&hidePrivateOnly=0', '&hidePrivateOnly=false'])(
    'keeps existing browse behavior when disabled (%s)',
    async (query) => {
      expect((await modsRouter.request(`/?facets=1${query}`)).status).toBe(200);
      expect(state.queries).toHaveLength(4);
      for (const query of state.queries) {
        expect(query.text).not.toContain('private_tag');
        expect(query.params).not.toContain('private-only');
      }
    },
  );

  it('rejects malformed preferences before querying the database', async () => {
    expect((await modsRouter.request('/?hidePrivateOnly=yes')).status).toBe(400);
    expect(state.queries).toHaveLength(0);
  });
});
