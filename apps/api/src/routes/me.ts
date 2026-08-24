import { zValidator } from '@hono/zod-validator';
import { getDb, schema } from '@rsmm/db';
import {
  PRIVACY_DEFAULTS,
  type PrivacySettings,
  modImagePresignSchema,
  privacySettingsSchema,
  privacySettingsUpdateSchema,
} from '@rsmm/schemas';
import { and, desc, eq, isNull, or, sql } from 'drizzle-orm';
import { Hono } from 'hono';
import { z } from 'zod';
import { isAdmin } from '../admin.js';
import { s3Configured } from '../env.js';
import { unreadCount } from '../notify.js';
import { presignAvatar } from '../storage.js';
import type { AppEnv } from '../types.js';

export const meRouter = new Hono<AppEnv>();

// See routes/mods.ts: outer-row ref for correlated subqueries must be raw —
// drizzle renders `${schema.mods.id}` unqualified in single-table selects and
// it resolves to the inner table's `id`.
const outerModId = sql.raw('"mods"."id"');

// All routes here require an authenticated session — the session
// middleware in app.ts populates `c.get('user')` from the cookie.
meRouter.use('*', async (c, next) => {
  if (!c.get('user')) return c.json({ error: 'unauthorized' }, 401);
  await next();
});

// Lightweight identity + capability probe. The web nav uses `isAdmin` to decide
// whether to render the moderation link; the moderation routes themselves are
// still server-gated, so this only controls UI affordances.
meRouter.get('/', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  return c.json({ id: user.id, isAdmin: isAdmin(user.id) });
});

// ─────────── Privacy preferences ───────────
//
// Read/written here rather than through Better Auth's user update so the
// allowed shape is one zod schema (`privacySettingsSchema`) shared with the
// client, and so a request can never smuggle `banned` or `emailVerified` in
// alongside a privacy toggle.

// Two shapes for the same five fields: `query.findFirst` takes a column *mask*,
// `.returning()` takes column *refs*. Keeping both here means adding a
// preference touches one place.
const PRIVACY_COLUMNS = {
  telemetryLevel: true,
  crashReportLevel: true,
  publicProfile: true,
  publicDownloadCounts: true,
  emailAnnouncements: true,
} as const;

const PRIVACY_RETURNING = {
  telemetryLevel: schema.users.telemetryLevel,
  crashReportLevel: schema.users.crashReportLevel,
  publicProfile: schema.users.publicProfile,
  publicDownloadCounts: schema.users.publicDownloadCounts,
  emailAnnouncements: schema.users.emailAnnouncements,
} as const;

/**
 * Coerce a stored row to the schema's shape. The two level columns are plain
 * varchars, so a value written before an enum change (or by hand) must not be
 * handed back as-is — fall back to the default, which is the more private of
 * the two plausible readings.
 */
function toSettings(row: Record<string, unknown> | undefined): PrivacySettings {
  const parsed = privacySettingsSchema.safeParse(row);
  return parsed.success ? parsed.data : PRIVACY_DEFAULTS;
}

meRouter.get('/privacy', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const row = await getDb().query.users.findFirst({
    where: eq(schema.users.id, user.id),
    columns: PRIVACY_COLUMNS,
  });
  return c.json(toSettings(row));
});

meRouter.patch('/privacy', zValidator('json', privacySettingsUpdateSchema), async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const patch = c.req.valid('json');
  const [row] = await getDb()
    .update(schema.users)
    .set({ ...patch, updatedAt: new Date() })
    .where(eq(schema.users.id, user.id))
    .returning(PRIVACY_RETURNING);
  return c.json(toSettings(row));
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
    // Mods the user owns OR is a co-author of (mod_authors membership).
    .where(
      or(
        eq(schema.mods.ownerId, user.id),
        sql`exists (select 1 from ${schema.modAuthors} where ${schema.modAuthors.modId} = ${outerModId} and ${schema.modAuthors.userId} = ${user.id})`,
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
      // Enriched card fields (additive — original three stay first-class for
      // older clients).
      summary: schema.mods.summary,
      category: schema.mods.category,
      authorName: schema.mods.authorName,
      rating: schema.mods.rating,
      nsfw: schema.mods.nsfw,
      updatedAt: schema.mods.updatedAt,
      latestVersion: sql<string | null>`(
        select ${schema.modVersions.version}
        from ${schema.modVersions}
        where ${schema.modVersions.modId} = ${schema.mods.id}
          and ${schema.modVersions.scanStatus} in ('clean', 'skipped')
        order by ${schema.modVersions.createdAt} desc
        limit 1
      )`,
      downloads: sql<number>`coalesce((
        select sum(${schema.modDownloads.count})::int
        from ${schema.modDownloads}
        where ${schema.modDownloads.modId} = ${schema.mods.id}
      ), 0)`,
    })
    .from(schema.modFollows)
    .innerJoin(schema.mods, eq(schema.modFollows.modId, schema.mods.id))
    .where(and(eq(schema.modFollows.userId, user.id), eq(schema.mods.takedownStatus, 'active')))
    .orderBy(desc(schema.modFollows.createdAt));
  return c.json({
    items: rows.map((r) => ({
      ...r,
      rating: r.rating != null ? Number(r.rating) : null,
      followedAt: r.followedAt.toISOString(),
      updatedAt: r.updatedAt.toISOString(),
    })),
  });
});
