import { randomBytes } from 'node:crypto';
import { zValidator } from '@hono/zod-validator';
import { getDb, schema } from '@rsmm/db';
import { LOG_SHARE_TTL_DAYS, logShareCreateSchema } from '@rsmm/schemas';
import { and, eq, sql } from 'drizzle-orm';
import { Hono } from 'hono';
import { env } from '../env.js';
import { errString, log } from '../logger.js';
import { createRateLimiter } from '../rate-limit.js';
import type { AppEnv } from '../types.js';

export const logsRouter = new Hono<AppEnv>();

/** 72 bits of URL-safe randomness. The viewer is unlisted, not access
 *  controlled, so the id IS the capability — it has to be unguessable. */
function newLogId(): string {
  return randomBytes(9).toString('base64url');
}

const clientKey = (c: import('hono').Context): string => {
  const user = c.get('user');
  if (user?.id) return `u:${user.id}`;
  return `ip:${c.req.header('x-real-ip') ?? c.req.header('x-forwarded-for')?.split(',').pop()?.trim() ?? 'unknown'}`;
};

/**
 * Writes are capped hard. This endpoint stores up to 150 KB of arbitrary text
 * for anyone who can reach it, which is exactly the shape of a free pastebin;
 * an hour-long window keeps it useful for a real debugging session (share the
 * crash, retry, share again) and useless as hosting. Signed-in accounts get a
 * larger budget because they are attributable and revocable.
 */
logsRouter.use(
  '/',
  createRateLimiter({
    name: 'log-share',
    windowMs: 3_600_000,
    maxHits: 20,
    keyFrom: clientKey,
  }),
);

/**
 * Anonymous callers get a much smaller hourly budget on top of the shared one.
 * Kept as a separate limiter (rather than a lower `maxHits` keyed on the same
 * bucket) so a signed-in user behind the same NAT is never throttled by an
 * anonymous neighbour's spending.
 */
const anonLimiter = createRateLimiter({
  name: 'log-share-anon',
  windowMs: 3_600_000,
  maxHits: 5,
  keyFrom: clientKey,
});
logsRouter.use('/', async (c, next) => {
  if (c.get('user')) return next();
  return anonLimiter(c, next);
});

logsRouter.post('/', zValidator('json', logShareCreateSchema), async (c) => {
  const user = c.get('user');
  const body = c.req.valid('json');

  const id = newLogId();
  const expiresAt = new Date(Date.now() + LOG_SHARE_TTL_DAYS * 24 * 60 * 60 * 1000);
  const bytes = Buffer.byteLength(body.content, 'utf8');
  const lineCount = body.content.split('\n').length;

  await getDb()
    .insert(schema.sharedLogs)
    .values({
      id,
      userId: user?.id ?? null,
      source: body.source,
      rsmmVersion: body.rsmmVersion,
      os: body.os,
      content: body.content,
      meta: body.meta ?? null,
      bytes,
      lineCount,
      expiresAt,
    });

  return c.json({
    id,
    // Built from WEB_URL so a preview/self-hosted deploy hands out its own
    // origin rather than a link into production.
    url: `${env.webUrl.replace(/\/$/, '')}/l/${id}`,
    expiresAt: expiresAt.toISOString(),
  });
});

logsRouter.get('/:id', async (c) => {
  const id = c.req.param('id');
  // The slug is base64url; anything else can't exist, so don't spend a query.
  if (!/^[A-Za-z0-9_-]{1,32}$/.test(id)) return c.json({ error: 'not found' }, 404);

  const row = await getDb().query.sharedLogs.findFirst({
    where: eq(schema.sharedLogs.id, id),
  });
  if (!row) return c.json({ error: 'not found' }, 404);
  // Expired rows survive until the daily retention cron sweeps them, so the
  // read path has to enforce the TTL itself or a share outlives its promise.
  if (row.expiresAt.getTime() <= Date.now()) return c.json({ error: 'expired' }, 410);

  // Best effort: a view counter is not worth failing a read over.
  getDb()
    .update(schema.sharedLogs)
    .set({ views: sql`${schema.sharedLogs.views} + 1` })
    .where(eq(schema.sharedLogs.id, id))
    .catch((err) => {
      (c.get('log') ?? log).error('log view bump failed', { err: errString(err) });
    });

  return c.json({
    id: row.id,
    source: row.source,
    rsmmVersion: row.rsmmVersion,
    os: row.os,
    content: row.content,
    meta: (row.meta ?? null) as Record<string, unknown> | null,
    lineCount: row.lineCount,
    bytes: row.bytes,
    createdAt: row.createdAt.toISOString(),
    expiresAt: row.expiresAt.toISOString(),
  });
});

/** Let the uploader retract a share. Only the owning account can — an
 *  anonymous share has no owner to prove, and the id alone must not authorise
 *  deletion or anyone the link was given to could destroy the evidence. */
logsRouter.delete('/:id', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const id = c.req.param('id');
  const deleted = await getDb()
    .delete(schema.sharedLogs)
    .where(and(eq(schema.sharedLogs.id, id), eq(schema.sharedLogs.userId, user.id)))
    .returning({ id: schema.sharedLogs.id });
  if (deleted.length === 0) return c.json({ error: 'not found' }, 404);
  return c.json({ ok: true as const });
});
