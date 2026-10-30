import { zValidator } from '@hono/zod-validator';
import { getDb, schema } from '@rsmm/db';
import { modTakedownSchema, reportResolveSchema, userBanSchema } from '@rsmm/schemas';
import { desc, eq, sql } from 'drizzle-orm';
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

// ─────────── Business overview ───────────
//
// One admin-only snapshot behind `GET /api/moderation/stats`, powering the
// overview at the top of the web console. Everything here is an aggregate over
// tables the console already governs — it exposes no individual's telemetry,
// and the two client-health blocks read rows that are anonymous by default
// (see users.telemetry_level).
//
// Written as a handful of grouped queries rather than one per tile: each tile
// would be a round-trip, and the console refreshes on every visit.

/** Whole days back from now, as a Date, for `created_at >= ?` windows. */
function daysAgo(n: number): Date {
  return new Date(Date.now() - n * 24 * 60 * 60 * 1000);
}

// The Stats tab's period. Every series and every `range` total covers the last
// `days` days; the fixed d1/d7/d30 figures stay for the cards that name them.
const statsQuerySchema = z.object({
  days: z.coerce
    .number()
    .int()
    .refine((n) => [7, 30, 90, 365].includes(n))
    .default(30),
});

moderationRouter.get('/stats', zValidator('query', statsQuerySchema), async (c) => {
  const { days } = c.req.valid('query');
  const db = getDb();
  const d1 = daysAgo(1);
  const d7 = daysAgo(7);
  const d30 = daysAgo(30);

  // `count(*) filter (where …)` keeps each block to a single scan instead of
  // one query per window.
  const usersQ = db
    .select({
      total: sql<number>`count(*)::int`,
      new1d: sql<number>`count(*) filter (where ${schema.users.createdAt} >= ${d1})::int`,
      new7d: sql<number>`count(*) filter (where ${schema.users.createdAt} >= ${d7})::int`,
      new30d: sql<number>`count(*) filter (where ${schema.users.createdAt} >= ${d30})::int`,
      banned: sql<number>`count(*) filter (where ${schema.users.banned})::int`,
      verified: sql<number>`count(*) filter (where ${schema.users.emailVerified})::int`,
      // Consent mix — how much of the install base is actually reporting.
      telemetryOff: sql<number>`count(*) filter (where ${schema.users.telemetryLevel} = 'off')::int`,
      telemetryAnon: sql<number>`count(*) filter (where ${schema.users.telemetryLevel} = 'anonymous')::int`,
      telemetryLinked: sql<number>`count(*) filter (where ${schema.users.telemetryLevel} = 'linked')::int`,
      announcementOptIn: sql<number>`count(*) filter (where ${schema.users.emailAnnouncements})::int`,
    })
    .from(schema.users);

  // "Active" = holds a session that has not expired. Better Auth prunes on
  // sign-out, so this tracks people who are currently signed in somewhere
  // rather than everyone who ever visited.
  const activeQ = db
    .select({ active: sql<number>`count(distinct ${schema.sessions.userId})::int` })
    .from(schema.sessions)
    .where(sql`${schema.sessions.expiresAt} > now()`);

  const creatorsQ = db
    .select({ creators: sql<number>`count(distinct ${schema.mods.ownerId})::int` })
    .from(schema.mods)
    .where(sql`${schema.mods.ownerId} is not null`);

  const modsQ = db
    .select({
      total: sql<number>`count(*)::int`,
      active: sql<number>`count(*) filter (where ${schema.mods.takedownStatus} = 'active')::int`,
      hidden: sql<number>`count(*) filter (where ${schema.mods.takedownStatus} = 'hidden')::int`,
      removed: sql<number>`count(*) filter (where ${schema.mods.takedownStatus} = 'removed')::int`,
      featured: sql<number>`count(*) filter (where ${schema.mods.featured})::int`,
      nsfw: sql<number>`count(*) filter (where ${schema.mods.nsfw})::int`,
      new7d: sql<number>`count(*) filter (where ${schema.mods.createdAt} >= ${d7})::int`,
      new30d: sql<number>`count(*) filter (where ${schema.mods.createdAt} >= ${d30})::int`,
      // Thin listings drag on search quality and are noindexed on the website —
      // worth watching as a number, not just per-mod.
      noSummary: sql<number>`count(*) filter (where coalesce(trim(${schema.mods.summary}), '') = '')::int`,
    })
    .from(schema.mods);

  const versionsQ = db
    .select({
      total: sql<number>`count(*)::int`,
      new7d: sql<number>`count(*) filter (where ${schema.modVersions.createdAt} >= ${d7})::int`,
      awaitingScan: sql<number>`count(*) filter (where ${schema.modVersions.scanStatus} in ('queued', 'pending'))::int`,
      flagged: sql<number>`count(*) filter (where ${schema.modVersions.scanStatus} = 'flagged')::int`,
      scanErrors: sql<number>`count(*) filter (where ${schema.modVersions.scanStatus} = 'error')::int`,
    })
    .from(schema.modVersions);

  // modDownloads is a day-bucket table, so windows filter on `day`, not a
  // timestamp, and the totals are sums rather than counts.
  const downloadsQ = db
    .select({
      total: sql<number>`coalesce(sum(${schema.modDownloads.count}), 0)::int`,
      d1: sql<number>`coalesce(sum(${schema.modDownloads.count}) filter (where ${schema.modDownloads.day} >= current_date - 1), 0)::int`,
      d7: sql<number>`coalesce(sum(${schema.modDownloads.count}) filter (where ${schema.modDownloads.day} >= current_date - 7), 0)::int`,
      d30: sql<number>`coalesce(sum(${schema.modDownloads.count}) filter (where ${schema.modDownloads.day} >= current_date - 30), 0)::int`,
    })
    .from(schema.modDownloads);

  const engagementQ = db
    .select({
      reviews: sql<number>`count(*)::int`,
      avgRating: sql<number | null>`round(avg(${schema.modReviews.rating})::numeric, 2)`,
      new7d: sql<number>`count(*) filter (where ${schema.modReviews.createdAt} >= ${d7})::int`,
    })
    .from(schema.modReviews);

  const reportsQ = db
    .select({
      open: sql<number>`count(*) filter (where ${schema.modReports.status} = 'open')::int`,
      reviewing: sql<number>`count(*) filter (where ${schema.modReports.status} = 'reviewing')::int`,
      new7d: sql<number>`count(*) filter (where ${schema.modReports.createdAt} >= ${d7})::int`,
    })
    .from(schema.modReports);

  const guidesQ = db
    .select({
      total: sql<number>`count(*)::int`,
      approved: sql<number>`count(*) filter (where ${schema.guides.status} = 'approved')::int`,
      pending: sql<number>`count(*) filter (where ${schema.guides.status} = 'pending')::int`,
    })
    .from(schema.guides);

  const collectionsQ = db.select({ total: sql<number>`count(*)::int` }).from(schema.collections);

  const followsQ = db.select({ total: sql<number>`count(*)::int` }).from(schema.modFollows);

  // Client health. Anonymous rows count here exactly like linked ones — that is
  // the point of the 'anonymous' level.
  const runsQ = db
    .select({
      runs7d: sql<number>`count(*) filter (where ${schema.telemetryRuns.createdAt} >= ${d7})::int`,
      ok7d: sql<number>`count(*) filter (where ${schema.telemetryRuns.createdAt} >= ${d7} and ${schema.telemetryRuns.ok})::int`,
      runs30d: sql<number>`count(*) filter (where ${schema.telemetryRuns.createdAt} >= ${d30})::int`,
    })
    .from(schema.telemetryRuns);

  const crashesQ = db
    .select({
      d7: sql<number>`count(*) filter (where ${schema.crashReports.createdAt} >= ${d7})::int`,
      d30: sql<number>`count(*) filter (where ${schema.crashReports.createdAt} >= ${d30})::int`,
    })
    .from(schema.crashReports);

  // Distinct installs that opened the app in each window — the honest user
  // count (see installPings). `total` is every install still inside retention.
  const installsQ = db
    .select({
      total: sql<number>`count(distinct ${schema.installPings.installId})::int`,
      d1: sql<number>`count(distinct ${schema.installPings.installId}) filter (where ${schema.installPings.day} >= current_date - 1)::int`,
      d7: sql<number>`count(distinct ${schema.installPings.installId}) filter (where ${schema.installPings.day} >= current_date - 7)::int`,
      d30: sql<number>`count(distinct ${schema.installPings.installId}) filter (where ${schema.installPings.day} >= current_date - 30)::int`,
    })
    .from(schema.installPings);

  const topModsQ = db
    .select({
      slug: schema.mods.slug,
      name: schema.mods.name,
      downloads: sql<number>`coalesce(sum(${schema.modDownloads.count}), 0)::int`,
    })
    .from(schema.mods)
    .leftJoin(schema.modDownloads, eq(schema.modDownloads.modId, schema.mods.id))
    .groupBy(schema.mods.id, schema.mods.slug, schema.mods.name)
    .orderBy(sql`coalesce(sum(${schema.modDownloads.count}), 0) desc`)
    .limit(10);

  const osSplitQ = db
    .select({
      os: schema.telemetryRuns.os,
      n: sql<number>`count(*)::int`,
    })
    .from(schema.telemetryRuns)
    .where(sql`${schema.telemetryRuns.createdAt} >= ${d30}`)
    .groupBy(schema.telemetryRuns.os)
    .orderBy(sql`count(*) desc`);

  const versionSplitQ = db
    .select({
      version: schema.telemetryRuns.rsmmVersion,
      n: sql<number>`count(*)::int`,
    })
    .from(schema.telemetryRuns)
    .where(sql`${schema.telemetryRuns.createdAt} >= ${d30}`)
    .groupBy(schema.telemetryRuns.rsmmVersion)
    .orderBy(sql`count(*) desc`)
    .limit(8);

  // Daily series for the charts, dense over the chosen period: generate_series
  // supplies the days with no rows so a quiet week is not silently compressed.
  // Each is `count`/`sum` per day of one table; `days` is validated above, so
  // interpolating it is safe.
  const span = sql.raw(String(days - 1));
  const dailySeries = (from: ReturnType<typeof sql>) =>
    db.execute(sql`
      select to_char(d.day, 'YYYY-MM-DD') as day, coalesce(t.n, 0)::int as n
      from generate_series(current_date - ${span}, current_date, interval '1 day') as d(day)
      left join (${from}) t on t.day = d.day
      order by d.day
    `);
  const signupSeriesQ = dailySeries(
    sql`select created_at::date as day, count(*) as n from "user" group by 1`,
  );
  const downloadSeriesQ = dailySeries(
    sql`select day, sum(count) as n from mod_downloads group by 1`,
  );
  const uploadSeriesQ = dailySeries(
    sql`select created_at::date as day, count(*) as n from mod_versions group by 1`,
  );
  const applySeriesQ = dailySeries(
    sql`select created_at::date as day, count(*) as n from telemetry_runs group by 1`,
  );
  const activeInstallSeriesQ = dailySeries(
    sql`select day, count(*) as n from install_pings group by 1`,
  );
  // An install's first ping is the day it was installed (or first updated to a
  // build that pings).
  const newInstallSeriesQ = dailySeries(
    sql`select first_day as day, count(*) as n from (select min(day) as first_day from install_pings group by install_id) f group by 1`,
  );
  const crashSeriesQ = dailySeries(
    sql`select created_at::date as day, count(*) as n from crash_reports group by 1`,
  );

  const [
    users,
    active,
    creators,
    mods,
    versions,
    downloads,
    engagement,
    reports,
    guides,
    collections,
    follows,
    runs,
    crashes,
    topMods,
    osSplit,
    versionSplit,
    signupSeries,
    downloadSeries,
    uploadSeries,
    applySeries,
    crashSeries,
    installs,
    activeInstallSeries,
    newInstallSeries,
  ] = await Promise.all([
    usersQ,
    activeQ,
    creatorsQ,
    modsQ,
    versionsQ,
    downloadsQ,
    engagementQ,
    reportsQ,
    guidesQ,
    collectionsQ,
    followsQ,
    runsQ,
    crashesQ,
    topModsQ,
    osSplitQ,
    versionSplitQ,
    signupSeriesQ,
    downloadSeriesQ,
    uploadSeriesQ,
    applySeriesQ,
    crashSeriesQ,
    installsQ,
    activeInstallSeriesQ,
    newInstallSeriesQ,
  ]);

  // db.execute returns a driver result whose row container differs between the
  // node-postgres and neon-http drivers; normalise before shipping it.
  const rowsOf = (r: unknown): { day: string; n: number }[] =>
    Array.isArray(r)
      ? (r as { day: string; n: number }[])
      : (((r as { rows?: unknown }).rows as { day: string; n: number }[]) ?? []);

  const u = users[0];
  const runRow = runs[0];
  return c.json({
    generatedAt: new Date().toISOString(),
    users: {
      total: u?.total ?? 0,
      new1d: u?.new1d ?? 0,
      new7d: u?.new7d ?? 0,
      new30d: u?.new30d ?? 0,
      banned: u?.banned ?? 0,
      verified: u?.verified ?? 0,
      active: active[0]?.active ?? 0,
      creators: creators[0]?.creators ?? 0,
    },
    consent: {
      telemetryOff: u?.telemetryOff ?? 0,
      telemetryAnonymous: u?.telemetryAnon ?? 0,
      telemetryLinked: u?.telemetryLinked ?? 0,
      announcementOptIn: u?.announcementOptIn ?? 0,
    },
    mods: mods[0] ?? null,
    versions: versions[0] ?? null,
    downloads: downloads[0] ?? null,
    installs: installs[0] ?? null,
    reviews: {
      total: engagement[0]?.reviews ?? 0,
      new7d: engagement[0]?.new7d ?? 0,
      avgRating: engagement[0]?.avgRating != null ? Number(engagement[0].avgRating) : null,
    },
    reports: reports[0] ?? null,
    guides: guides[0] ?? null,
    collections: collections[0]?.total ?? 0,
    follows: follows[0]?.total ?? 0,
    client: {
      runs7d: runRow?.runs7d ?? 0,
      runs30d: runRow?.runs30d ?? 0,
      // Apply success rate over the last 7 days — the single number that says
      // whether a release broke installs.
      successRate7d: runRow?.runs7d
        ? Math.round(((runRow.ok7d ?? 0) / runRow.runs7d) * 1000) / 10
        : null,
      crashes7d: crashes[0]?.d7 ?? 0,
      crashes30d: crashes[0]?.d30 ?? 0,
      osSplit,
      versionSplit,
    },
    topMods,
    days,
    series: {
      signups: rowsOf(signupSeries),
      downloads: rowsOf(downloadSeries),
      uploads: rowsOf(uploadSeries),
      applies: rowsOf(applySeries),
      crashes: rowsOf(crashSeries),
      activeInstalls: rowsOf(activeInstallSeries),
      newInstalls: rowsOf(newInstallSeries),
    },
  });
});

// Mod versions and their malware scan, newest first: everything not yet
// cleared (queued, pending, flagged, error) regardless of age, plus the last 30
// days of finished scans. The website links each to its VirusTotal report by
// sha256 — the file hash is the VT file id.
moderationRouter.get('/versions', async (c) => {
  const db = getDb();
  const rows = await db
    .select({
      id: schema.modVersions.id,
      modSlug: schema.mods.slug,
      modName: schema.mods.name,
      version: schema.modVersions.version,
      sha256: schema.modVersions.sha256,
      sizeBytes: schema.modVersions.sizeBytes,
      scanStatus: schema.modVersions.scanStatus,
      scanStats: schema.modVersions.scanStats,
      createdAt: schema.modVersions.createdAt,
      scanQueuedAt: schema.modVersions.scanQueuedAt,
      scannedAt: schema.modVersions.scannedAt,
    })
    .from(schema.modVersions)
    .innerJoin(schema.mods, eq(schema.mods.id, schema.modVersions.modId))
    .where(
      sql`${schema.modVersions.scanStatus} not in ('clean', 'skipped') or ${schema.modVersions.createdAt} >= ${daysAgo(30)}`,
    )
    .orderBy(desc(schema.modVersions.createdAt))
    .limit(100);
  return c.json({
    items: rows.map((r) => ({
      ...r,
      createdAt: r.createdAt.toISOString(),
      scanQueuedAt: r.scanQueuedAt?.toISOString() ?? null,
      scannedAt: r.scannedAt?.toISOString() ?? null,
    })),
  });
});
