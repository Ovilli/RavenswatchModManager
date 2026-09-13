import { zValidator } from '@hono/zod-validator';
import { getDb, schema } from '@rsmm/db';
import {
  PRIVACY_DEFAULTS,
  type PrivacySettings,
  apiTokenCreateSchema,
  modImagePresignSchema,
  privacySettingsSchema,
  privacySettingsUpdateSchema,
} from '@rsmm/schemas';
import { and, desc, eq, isNull, or, sql } from 'drizzle-orm';
import { Hono } from 'hono';
import { z } from 'zod';
import { isAdmin } from '../admin.js';
import { MAX_ACTIVE_TOKENS, generateToken } from '../api-tokens.js';
import { env, s3Configured, smtpConfigured } from '../env.js';
import { errString } from '../logger.js';
import { apiTokenCreatedTemplate, sendMail } from '../mailer.js';
import { unreadCount } from '../notify.js';
import { createRateLimiter } from '../rate-limit.js';
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
  // `name` lets `rsmm publish` say whose account a token belongs to before it
  // uploads anything. It is the caller's own name — nothing another user sees.
  return c.json({ id: user.id, name: user.name, isAdmin: isAdmin(user.id) });
});

// ─────────── Personal API tokens ───────────
//
// Minted, listed and revoked from a signed-in SESSION only. The session
// middleware never lets a token reach these paths (they are not in
// api-tokens.ts TOKEN_ROUTES), and each handler checks again, so a leaked token
// can neither mint a successor nor revoke the owner's fix.

const tokenWriteLimiter = createRateLimiter({
  name: 'api-token-write',
  windowMs: 3_600_000,
  maxHits: 20,
  keyFrom: (c) => c.get('user')?.id ?? 'anon',
});

type TokenRow = typeof schema.apiTokens.$inferSelect;

function tokenSummary(row: TokenRow) {
  return {
    id: row.id,
    name: row.name,
    prefix: row.prefix,
    createdAt: row.createdAt.toISOString(),
    expiresAt: row.expiresAt.toISOString(),
    lastUsedAt: row.lastUsedAt?.toISOString() ?? null,
    revokedAt: row.revokedAt?.toISOString() ?? null,
  };
}

meRouter.use('/tokens', async (c, next) => {
  if (c.get('authMethod') !== 'session') return c.json({ error: 'session required' }, 403);
  await next();
});
meRouter.use('/tokens/*', async (c, next) => {
  if (c.get('authMethod') !== 'session') return c.json({ error: 'session required' }, 403);
  await next();
});

meRouter.get('/tokens', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const rows = await getDb()
    .select()
    .from(schema.apiTokens)
    .where(eq(schema.apiTokens.userId, user.id))
    .orderBy(desc(schema.apiTokens.createdAt));
  return c.json({ tokens: rows.map(tokenSummary) });
});

meRouter.post('/tokens', tokenWriteLimiter, zValidator('json', apiTokenCreateSchema), async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const body = c.req.valid('json');
  const db = getDb();
  const now = new Date();

  const active = await db
    .select({ n: sql<number>`count(*)::int` })
    .from(schema.apiTokens)
    .where(
      and(
        eq(schema.apiTokens.userId, user.id),
        isNull(schema.apiTokens.revokedAt),
        sql`${schema.apiTokens.expiresAt} > ${now}`,
      ),
    );
  if ((active[0]?.n ?? 0) >= MAX_ACTIVE_TOKENS) {
    return c.json(
      { error: `you already have ${MAX_ACTIVE_TOKENS} active tokens; revoke one first` },
      409,
    );
  }

  const { token, hash, prefix } = generateToken();
  const expiresAt = new Date(now.getTime() + body.expiresInDays * 86_400_000);
  const rows = await db
    .insert(schema.apiTokens)
    .values({ userId: user.id, name: body.name, tokenHash: hash, prefix, expiresAt })
    .returning();
  const row = rows[0];
  if (!row) return c.json({ error: 'failed to create token' }, 500);

  c.get('log').info('api token created', { userId: user.id, tokenId: row.id });
  if (smtpConfigured() && user.email) {
    const t = apiTokenCreatedTemplate({
      name: user.name,
      tokenName: row.name,
      expiresAt,
      manageUrl: `${env.webUrl.replace(/\/$/, '')}/account#api-tokens`,
    });
    sendMail({ to: user.email, subject: t.subject, text: t.text, html: t.html }).catch(
      (err: unknown) =>
        c.get('log').error('api token notice email failed', { err: errString(err) }),
    );
  }

  // The only response that ever carries the plaintext.
  c.header('Cache-Control', 'no-store');
  return c.json({ ...tokenSummary(row), token }, 201);
});

meRouter.delete(
  '/tokens/:id',
  tokenWriteLimiter,
  zValidator('param', z.object({ id: z.string().uuid() })),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    const { id } = c.req.valid('param');
    const rows = await getDb()
      .update(schema.apiTokens)
      .set({ revokedAt: new Date() })
      .where(
        and(
          eq(schema.apiTokens.id, id),
          eq(schema.apiTokens.userId, user.id),
          isNull(schema.apiTokens.revokedAt),
        ),
      )
      .returning();
    const row = rows[0];
    // Not found covers "someone else's token" too: never confirm another
    // user's token id exists.
    if (!row) return c.json({ error: 'not found' }, 404);
    c.get('log').info('api token revoked', { userId: user.id, tokenId: row.id });
    return c.json(tokenSummary(row));
  },
);

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
