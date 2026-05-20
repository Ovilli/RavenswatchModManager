import { zValidator } from '@hono/zod-validator';
import { getDb, schema } from '@rsmm/db';
import { crashReportSchema, telemetryRunSchema } from '@rsmm/schemas';
import { Hono } from 'hono';
import type { AppEnv } from '../types';

export const telemetryRouter = new Hono<AppEnv>();

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
