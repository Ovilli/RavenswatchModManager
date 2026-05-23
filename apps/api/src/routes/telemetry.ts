import { zValidator } from '@hono/zod-validator';
import { getDb, schema } from '@rsmm/db';
import { crashReportSchema, telemetryRunSchema } from '@rsmm/schemas';
import { Hono } from 'hono';
import { createRateLimiter } from '../rate-limit';
import type { AppEnv } from '../types';

export const telemetryRouter = new Hono<AppEnv>();

// Telemetry endpoints accept anonymous writes (so launchers that never
// signed in still report crashes), which makes them a soft target for
// row-spam. Key on user id when present, otherwise the forwarded IP —
// matches the rate limiter we use on auth so behaviour is consistent.
const telemetryKey = (c: import('hono').Context): string => {
  const user = c.get('user');
  if (user?.id) return `u:${user.id}`;
  return `ip:${c.req.header('x-forwarded-for')?.split(',')[0]?.trim() ?? 'unknown'}`;
};

telemetryRouter.use(
  '/run',
  createRateLimiter({ windowMs: 60_000, maxHits: 60, keyFrom: telemetryKey }),
);
telemetryRouter.use(
  '/crash',
  createRateLimiter({ windowMs: 60_000, maxHits: 10, keyFrom: telemetryKey }),
);

telemetryRouter.post('/run', zValidator('json', telemetryRunSchema), async (c) => {
  const user = c.get('user');
  const body = c.req.valid('json');
  await getDb()
    .insert(schema.telemetryRuns)
    .values({
      userId: user?.id ?? null,
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
  await getDb()
    .insert(schema.crashReports)
    .values({
      userId: user?.id ?? null,
      rsmmVersion: body.rsmmVersion,
      os: body.os,
      errorClass: body.errorClass,
      message: body.message,
      stacktrace: body.stacktrace,
      context: body.context ?? null,
    });
  return c.json({ ok: true as const });
});
