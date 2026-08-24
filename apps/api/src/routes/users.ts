import { getDb, schema } from '@rsmm/db';
import { and, desc, eq, or, sql } from 'drizzle-orm';
import { Hono } from 'hono';
import { isAdmin } from '../admin.js';
import type { AppEnv } from '../types.js';

export const usersRouter = new Hono<AppEnv>();

// See routes/mods.ts: outer-row ref for correlated subqueries must be raw —
// drizzle renders `${schema.mods.id}` unqualified in single-table selects and
// it resolves to the inner table's `id`.
const outerModId = sql.raw('"mods"."id"');

/**
 * Public profile: GET /api/users/:idOrHandle
 *
 * The URL segment is matched against `user.id` first, then `user.handle`
 * so we can route both UUID-style URLs and pretty `/u/<handle>` ones to
 * the same record. Returns a *trimmed* user object (no email, no
 * email-verified flag, no timestamps that would leak account age) plus
 * the list of mods owned by that user, formatted exactly like the
 * registry list response so the website can reuse its card components.
 *
 * Two account privacy flags gate this response (see users.publicProfile /
 * users.publicDownloadCounts):
 *   publicProfile=false        — 404, as if the profile did not exist. The
 *                                mods themselves stay listed in the registry;
 *                                only the person-shaped page disappears.
 *   publicDownloadCounts=false — every `downloads` figure comes back null
 *                                rather than zero, so the UI can hide the stat
 *                                instead of reporting a wrong number.
 * The owner and admins always see their own real figures.
 */
usersRouter.get('/:idOrHandle', async (c) => {
  const param = c.req.param('idOrHandle');
  if (!param) return c.json({ error: 'missing id' }, 400);
  const db = getDb();

  const u = await db.query.users.findFirst({
    where: or(eq(schema.users.id, param), eq(schema.users.handle, param)),
    columns: {
      id: true,
      name: true,
      handle: true,
      image: true,
      publicProfile: true,
      publicDownloadCounts: true,
    },
  });
  if (!u) return c.json({ error: 'not found' }, 404);

  const viewer = c.get('user');
  const isSelf = viewer?.id === u.id;
  const privileged = isSelf || isAdmin(viewer?.id);
  if (!u.publicProfile && !privileged) return c.json({ error: 'not found' }, 404);
  const showDownloads = u.publicDownloadCounts || privileged;

  const rows = await db
    .select({
      id: schema.mods.id,
      slug: schema.mods.slug,
      name: schema.mods.name,
      summary: schema.mods.summary,
      license: schema.mods.license,
      updatedAt: schema.mods.updatedAt,
      category: schema.mods.category,
      authorName: schema.mods.authorName,
      imageUrl: schema.mods.imageUrl,
      rating: schema.mods.rating,
      tags: schema.mods.tags,
      featured: schema.mods.featured,
      ownerId: schema.mods.ownerId,
      latestVersion: sql<string | null>`(
        select ${schema.modVersions.version}
        from ${schema.modVersions}
        where ${schema.modVersions.modId} = ${outerModId}
        order by ${schema.modVersions.createdAt} desc
        limit 1
      )`,
      downloads: sql<number>`coalesce((
        select sum(${schema.modDownloads.count})::int
        from ${schema.modDownloads}
        where ${schema.modDownloads.modId} = ${outerModId}
      ), 0)`,
    })
    .from(schema.mods)
    .where(and(eq(schema.mods.ownerId, u.id), eq(schema.mods.takedownStatus, 'active')))
    .orderBy(desc(schema.mods.updatedAt));

  return c.json({
    user: {
      id: u.id,
      name: u.name,
      handle: u.handle,
      image: u.image,
    },
    mods: rows.map((r) => ({
      id: r.id,
      slug: r.slug,
      name: r.name,
      author: r.authorName,
      summary: r.summary,
      license: r.license,
      latestVersion: r.latestVersion,
      downloads: showDownloads ? r.downloads : null,
      updatedAt: r.updatedAt.toISOString(),
      category: r.category,
      imageUrl: r.imageUrl,
      rating: r.rating != null ? Number(r.rating) : null,
      tags: r.tags ?? [],
      featured: r.featured,
      ownerId: r.ownerId,
    })),
    totalDownloads: showDownloads ? rows.reduce((s, r) => s + r.downloads, 0) : null,
  });
});
