import { zValidator } from '@hono/zod-validator';
import { getDb, schema } from '@rsmm/db';
import { modTakedownSchema, reportResolveSchema, userBanSchema } from '@rsmm/schemas';
import { desc, eq } from 'drizzle-orm';
import { Hono } from 'hono';
import { z } from 'zod';
import { isAdmin } from '../admin.js';
import { notify } from '../notify.js';
import type { AppEnv } from '../types.js';

export const moderationRouter = new Hono<AppEnv>();

// Every route here is admin-only. Admins are configured via ADMIN_USER_IDS
// (see env.ts / admin.ts). Mirrors the guides moderation pattern but for mods,
// reports, and users.
moderationRouter.use('*', async (c, next) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  if (!isAdmin(user.id)) return c.json({ error: 'forbidden' }, 403);
  await next();
});

// ─────────── Reports queue ───────────

const reportsQuerySchema = z.object({
  status: z.enum(['open', 'reviewing', 'resolved', 'dismissed']).optional(),
  limit: z.coerce.number().int().min(1).max(100).default(50),
  offset: z.coerce.number().int().min(0).default(0),
});

moderationRouter.get('/reports', zValidator('query', reportsQuerySchema), async (c) => {
  const { status, limit, offset } = c.req.valid('query');
  const db = getDb();

  const rows = await db
    .select({
      id: schema.modReports.id,
      modId: schema.modReports.modId,
      modSlug: schema.mods.slug,
      modName: schema.mods.name,
      takedownStatus: schema.mods.takedownStatus,
      reporterId: schema.modReports.reporterId,
      reporterName: schema.users.name,
      reason: schema.modReports.reason,
      detail: schema.modReports.detail,
      status: schema.modReports.status,
      resolutionNote: schema.modReports.resolutionNote,
      createdAt: schema.modReports.createdAt,
      updatedAt: schema.modReports.updatedAt,
    })
    .from(schema.modReports)
    .innerJoin(schema.mods, eq(schema.modReports.modId, schema.mods.id))
    .leftJoin(schema.users, eq(schema.modReports.reporterId, schema.users.id))
    .where(status ? eq(schema.modReports.status, status) : undefined)
    .orderBy(desc(schema.modReports.createdAt))
    .limit(limit)
    .offset(offset);

  return c.json({
    items: rows.map((r) => ({
      ...r,
      createdAt: r.createdAt.toISOString(),
      updatedAt: r.updatedAt.toISOString(),
    })),
  });
});

const reportIdParamSchema = z.object({ id: z.string().uuid() });

moderationRouter.patch(
  '/reports/:id',
  zValidator('param', reportIdParamSchema),
  zValidator('json', reportResolveSchema),
  async (c) => {
    const user = c.get('user');
    const { id } = c.req.valid('param');
    const { status, resolutionNote } = c.req.valid('json');
    const db = getDb();

    const rows = await db
      .update(schema.modReports)
      .set({
        status,
        resolutionNote: resolutionNote ?? null,
        handledBy: user?.id ?? null,
        updatedAt: new Date(),
      })
      .where(eq(schema.modReports.id, id))
      .returning();
    const report = rows[0];
    if (!report) return c.json({ error: 'not found' }, 404);

    // Close the loop for the reporter once the report reaches a terminal state.
    if (report.reporterId && (status === 'resolved' || status === 'dismissed')) {
      const modRow = await db
        .select({ slug: schema.mods.slug, name: schema.mods.name })
        .from(schema.mods)
        .where(eq(schema.mods.id, report.modId))
        .limit(1);
      const reporter = await db
        .select({ email: schema.users.email })
        .from(schema.users)
        .where(eq(schema.users.id, report.reporterId))
        .limit(1);
      await notify({
        userId: report.reporterId,
        type: 'report_resolved',
        title: `Your report on "${modRow[0]?.name ?? 'a mod'}" was ${status}`,
        body: resolutionNote ?? null,
        link: modRow[0]?.slug ? `/registry/${modRow[0].slug}` : null,
        email: reporter[0]?.email ?? null,
      });
    }
    return c.json({ ok: true, report });
  },
);

// ─────────── Mod moderation ───────────

const slugParamSchema = z.object({
  slug: z
    .string()
    .min(1)
    .max(128)
    .regex(/^[a-z0-9_-]+$/),
});

moderationRouter.post(
  '/mods/:slug/takedown',
  zValidator('param', slugParamSchema),
  zValidator('json', modTakedownSchema),
  async (c) => {
    const { slug } = c.req.valid('param');
    const { takedownStatus, reason } = c.req.valid('json');
    const db = getDb();
    const rows = await db
      .update(schema.mods)
      .set({
        takedownStatus,
        takedownReason: takedownStatus === 'active' ? null : (reason ?? null),
        updatedAt: new Date(),
      })
      .where(eq(schema.mods.slug, slug))
      .returning();
    const m = rows[0];
    if (!m) return c.json({ error: 'not found' }, 404);

    // Tell the owner their mod was taken down (in-app + email).
    if (m.ownerId && takedownStatus !== 'active') {
      const owner = await db
        .select({ email: schema.users.email })
        .from(schema.users)
        .where(eq(schema.users.id, m.ownerId))
        .limit(1);
      await notify({
        userId: m.ownerId,
        type: 'mod_takedown',
        title: `Your mod "${m.name}" was taken down`,
        body: reason ? `Reason: ${reason}` : 'Your mod was removed by a moderator.',
        link: `/my-mods/${m.slug}`,
        email: owner[0]?.email ?? null,
      });
    }
    return c.json({ ok: true, mod: m });
  },
);

const featureSchema = z.object({ featured: z.boolean() });

moderationRouter.post(
  '/mods/:slug/feature',
  zValidator('param', slugParamSchema),
  zValidator('json', featureSchema),
  async (c) => {
    const { slug } = c.req.valid('param');
    const { featured } = c.req.valid('json');
    const db = getDb();
    const rows = await db
      .update(schema.mods)
      .set({
        featured,
        featuredAt: featured ? new Date() : null,
        updatedAt: new Date(),
      })
      .where(eq(schema.mods.slug, slug))
      .returning();
    if (!rows[0]) return c.json({ error: 'not found' }, 404);
    return c.json({ ok: true, mod: rows[0] });
  },
);

// ─────────── User moderation ───────────

const userIdParamSchema = z.object({ id: z.string().min(1) });

moderationRouter.post(
  '/users/:id/ban',
  zValidator('param', userIdParamSchema),
  zValidator('json', userBanSchema),
  async (c) => {
    const actor = c.get('user');
    const { id } = c.req.valid('param');
    const { banned, reason } = c.req.valid('json');
    // An admin can't ban themselves — avoids locking the console.
    if (actor?.id === id) return c.json({ error: 'cannot ban yourself' }, 400);
    const db = getDb();
    const rows = await db
      .update(schema.users)
      .set({ banned, bannedReason: banned ? (reason ?? null) : null, updatedAt: new Date() })
      .where(eq(schema.users.id, id))
      .returning({ id: schema.users.id, banned: schema.users.banned });
    if (!rows[0]) return c.json({ error: 'not found' }, 404);
    // If we just banned someone, drop their active sessions so the ban bites
    // immediately even on endpoints that don't re-check the DB.
    if (banned) {
      await db
        .delete(schema.sessions)
        .where(eq(schema.sessions.userId, id))
        .catch(() => {});
    }
    return c.json({ ok: true, user: rows[0] });
  },
);
