import { zValidator } from '@hono/zod-validator';
import { getDb, schema } from '@rsmm/db';
import { modImagePresignSchema } from '@rsmm/schemas';
import { and, desc, eq, isNull, or, sql } from 'drizzle-orm';
import { Hono } from 'hono';
import { z } from 'zod';
import { s3Configured } from '../env';
import { unreadCount } from '../notify';
import { presignAvatar } from '../storage';
import type { AppEnv } from '../types';

export const meRouter = new Hono<AppEnv>();

// All routes here require an authenticated session — the session
// middleware in app.ts populates `c.get('user')` from the cookie.
meRouter.use('*', async (c, next) => {
  if (!c.get('user')) return c.json({ error: 'unauthorized' }, 401);
  await next();
});

meRouter.post('/avatar', zValidator('json', modImagePresignSchema), async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  if (!s3Configured()) return c.json({ error: 'object storage not configured' }, 503);
  const body = c.req.valid('json');
  const signed = await presignAvatar({
    userId: user.id,
    contentType: body.contentType,
    sizeBytes: body.sizeBytes,
  });
  return c.json({
    uploadUrl: signed.uploadUrl,
    publicUrl: signed.publicUrl,
    expiresIn: signed.expiresIn,
  });
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
    // Mods the user owns OR is a co-author of (mod_authors membership).
    .where(
      or(
        eq(schema.mods.ownerId, user.id),
        sql`exists (select 1 from ${schema.modAuthors} where ${schema.modAuthors.modId} = ${schema.mods.id} and ${schema.modAuthors.userId} = ${user.id})`,
      ),
    )
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

// ─────────── Notifications ───────────

meRouter.get('/notifications', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const db = getDb();
  const rows = await db
    .select()
    .from(schema.notifications)
    .where(eq(schema.notifications.userId, user.id))
    .orderBy(desc(schema.notifications.createdAt))
    .limit(50);
  const unread = await unreadCount(user.id);
  return c.json({
    unread,
    items: rows.map((n) => ({
      id: n.id,
      type: n.type,
      title: n.title,
      body: n.body,
      link: n.link,
      read: n.readAt != null,
      createdAt: n.createdAt.toISOString(),
    })),
  });
});

// Mark notifications read. Body `{ id }` marks one; empty body marks all.
const markReadSchema = z.object({ id: z.string().uuid().optional() });
meRouter.post('/notifications/read', zValidator('json', markReadSchema), async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const { id } = c.req.valid('json');
  const db = getDb();
  const now = new Date();
  if (id) {
    await db
      .update(schema.notifications)
      .set({ readAt: now })
      .where(and(eq(schema.notifications.id, id), eq(schema.notifications.userId, user.id)));
  } else {
    await db
      .update(schema.notifications)
      .set({ readAt: now })
      .where(and(eq(schema.notifications.userId, user.id), isNull(schema.notifications.readAt)));
  }
  return c.json({ ok: true });
});

// ─────────── Followed mods ───────────

meRouter.get('/follows', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const db = getDb();
  const rows = await db
    .select({
      slug: schema.mods.slug,
      name: schema.mods.name,
      imageUrl: schema.mods.imageUrl,
      followedAt: schema.modFollows.createdAt,
    })
    .from(schema.modFollows)
    .innerJoin(schema.mods, eq(schema.modFollows.modId, schema.mods.id))
    .where(and(eq(schema.modFollows.userId, user.id), eq(schema.mods.takedownStatus, 'active')))
    .orderBy(desc(schema.modFollows.createdAt));
  return c.json({
    items: rows.map((r) => ({ ...r, followedAt: r.followedAt.toISOString() })),
  });
});
