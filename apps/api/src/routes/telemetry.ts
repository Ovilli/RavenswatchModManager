import { zValidator } from '@hono/zod-validator';
import { getDb, schema } from '@rsmm/db';
import {
  TELEMETRY_LEVEL_DEFAULT,
  type TelemetryLevel,
  crashReportSchema,
  telemetryLevelSchema,
  telemetryRunSchema,
} from '@rsmm/schemas';
import { eq } from 'drizzle-orm';
import { Hono } from 'hono';
import { createRateLimiter } from '../rate-limit.js';
import type { AppEnv } from '../types.js';

export const telemetryRouter = new Hono<AppEnv>();

/**
 * Resolve what a submission is allowed to carry, from the *account*, not the
 * client. The desktop app has its own local switch and normally never sends
 * when it is off — but the preference has to bite here too, or a stale build, a
 * second device, or a hand-rolled POST would quietly store more than the person
 * agreed to.
 *
 * An unauthenticated submission has no account to consult and is already
 * anonymous by construction (`userId` is null), so it is stored as-is.
 */
async function resolveLevel(
  userId: string | undefined,
  stream: 'telemetryLevel' | 'crashReportLevel',
): Promise<TelemetryLevel> {
  if (!userId) return 'anonymous';
  const row = await getDb().query.users.findFirst({
    where: eq(schema.users.id, userId),
    columns: { telemetryLevel: true, crashReportLevel: true },
  });
  // A user row that vanished mid-request, or a column holding something the
  // enum does not know, falls back to the default rather than to 'linked'.
  const parsed = telemetryLevelSchema.safeParse(row?.[stream]);
  return parsed.success ? parsed.data : TELEMETRY_LEVEL_DEFAULT;
}

// Telemetry endpoints accept anonymous writes (so launchers that never
// signed in still report crashes), which makes them a soft target for
// row-spam. Key on user id when present, otherwise the forwarded IP —
// matches the rate limiter we use on auth so behaviour is consistent.
const telemetryKey = (c: import('hono').Context): string => {
  const user = c.get('user');
  if (user?.id) return `u:${user.id}`;
  return `ip:${c.req.header('x-real-ip') ?? c.req.header('x-forwarded-for')?.split(',').pop()?.trim() ?? 'unknown'}`;
};

telemetryRouter.use(
  '/run',
  createRateLimiter({
    name: 'telemetry-run',
    windowMs: 60_000,
    maxHits: 60,
    keyFrom: telemetryKey,
  }),
);
telemetryRouter.use(
  '/crash',
  createRateLimiter({
    name: 'telemetry-crash',
    windowMs: 60_000,
    maxHits: 10,
    keyFrom: telemetryKey,
  }),
);

telemetryRouter.post('/run', zValidator('json', telemetryRunSchema), async (c) => {
  const user = c.get('user');
  const body = c.req.valid('json');
  const level = await resolveLevel(user?.id, 'telemetryLevel');
  // 'off' answers ok so a client that is behind on the preference does not
  // retry or surface an error to the user — the row simply is not written.
  if (level === 'off') return c.json({ ok: true as const });
  await getDb()
    .insert(schema.telemetryRuns)
    .values({
      userId: level === 'linked' ? (user?.id ?? null) : null,
      rsmmVersion: body.rsmmVersion,
      os: body.os,
      gameBuild: body.gameBuild,
      ok: body.ok,
      durationMs: body.durationMs,
      payload: body.payload ?? null,
    });
  return c.json({ ok: true as const });
});

telemetryRouter.post('/crash', zValidator('json', crashReportSchema), async (c) => {
  const user = c.get('user');
  const body = c.req.valid('json');
  const level = await resolveLevel(user?.id, 'crashReportLevel');
  if (level === 'off') return c.json({ ok: true as const });
  await getDb()
    .insert(schema.crashReports)
    .values({
      userId: level === 'linked' ? (user?.id ?? null) : null,
      rsmmVersion: body.rsmmVersion,
      os: body.os,
      errorClass: body.errorClass,
      message: body.message,
      stacktrace: body.stacktrace,
      context: body.context ?? null,
    });
  return c.json({ ok: true as const });
});
