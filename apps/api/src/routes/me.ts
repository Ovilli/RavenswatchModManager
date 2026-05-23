import { getDb, schema } from '@rsmm/db';
import { desc, eq, sql } from 'drizzle-orm';
import { Hono } from 'hono';
import type { AppEnv } from '../types';

export const meRouter = new Hono<AppEnv>();

// All routes here require an authenticated session — the session
// middleware in app.ts populates `c.get('user')` from the cookie.
meRouter.use('*', async (c, next) => {
  if (!c.get('user')) return c.json({ error: 'unauthorized' }, 401);
  await next();
});

meRouter.get('/mods', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const db = getDb();

  const rows = await db
    .select({
      id: schema.mods.id,
      slug: schema.mods.slug,
      name: schema.mods.name,
      summary: schema.mods.summary,
      description: schema.mods.description,
      license: schema.mods.license,
      repoUrl: schema.mods.repoUrl,
      homepageUrl: schema.mods.homepageUrl,
      tags: schema.mods.tags,
      category: schema.mods.category,
      authorName: schema.mods.authorName,
      imageUrl: schema.mods.imageUrl,
      updatedAt: schema.mods.updatedAt,
      createdAt: schema.mods.createdAt,
      latestVersion: sql<string | null>`(
        select ${schema.modVersions.version}
        from ${schema.modVersions}
        where ${schema.modVersions.modId} = ${schema.mods.id}
        order by ${schema.modVersions.createdAt} desc
        limit 1
      )`,
      downloads: sql<number>`coalesce((
        select sum(${schema.modDownloads.count})::int
        from ${schema.modDownloads}
        where ${schema.modDownloads.modId} = ${schema.mods.id}
      ), 0)`,
    })
    .from(schema.mods)
    .where(eq(schema.mods.ownerId, user.id))
    .orderBy(desc(schema.mods.updatedAt));

  return c.json({
    items: rows.map((r) => ({
      ...r,
      updatedAt: r.updatedAt.toISOString(),
      createdAt: r.createdAt.toISOString(),
      tags: r.tags ?? [],
    })),
  });
});
