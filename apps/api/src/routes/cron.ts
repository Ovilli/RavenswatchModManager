import { getDb, schema } from '@rsmm/db';
import { lt } from 'drizzle-orm';
import { Hono } from 'hono';
import { cronConfigured, env } from '../env.js';
import { errString, log } from '../logger.js';
import { drainBatch } from '../scan-service.js';
import type { AppEnv } from '../types.js';

export const cronRouter = new Hono<AppEnv>();

/**
 * Telemetry retention. The privacy policy states that usage and crash reports
 * are deleted after 12 months, so something has to actually delete them —
 * a stated retention period with no job behind it is a false statement, not a
 * policy. Runs on the same daily tick as the scan drain because Vercel's Hobby
 * plan allows exactly one cron.
 */
const RETENTION_DAYS = 365;

async function purgeExpiredTelemetry(): Promise<{ runs: number; crashes: number }> {
  const cutoff = new Date(Date.now() - RETENTION_DAYS * 24 * 60 * 60 * 1000);
  const db = getDb();
  const runs = await db
    .delete(schema.telemetryRuns)
    .where(lt(schema.telemetryRuns.createdAt, cutoff))
    .returning({ id: schema.telemetryRuns.id });
  const crashes = await db
    .delete(schema.crashReports)
    .where(lt(schema.crashReports.createdAt, cutoff))
    .returning({ id: schema.crashReports.id });
  return { runs: runs.length, crashes: crashes.length };
}

// How many queue items one cron invocation drains. Each drainOnce holds the
// VirusTotal budget for the length of a scan and bails on a 429, so a small
// batch clears a backlog over successive ticks without blowing the free-tier
// 4-lookups/min limit. Steady-state upload volume is low, so 1 keeps up.
const CRON_DRAIN_MAX = 3;

/**
 * Scheduled scan-queue heartbeat. On serverless the in-process setInterval
 * worker (scan-worker.ts) is torn down between requests, so the only things
 * that advanced the queue were a publish or an owner status-poll — a freshly
 * uploaded version whose VirusTotal analysis wasn't finished at upload time
 * would sit 'pending' forever (hidden by the fail-closed serve gate) once the
 * owner stopped watching. This endpoint gives the queue a drain independent of
 * that. Wired to a daily Vercel Cron backstop (Hobby caps crons at once/day;
 * see apps/api/vercel.json) — the fast path is the opportunistic kick on the
 * public browse endpoint (routes/mods.ts), which drains on organic traffic.
 *
 * Auth: Vercel Cron sends `Authorization: Bearer <CRON_SECRET>`. We reject
 * anything else so the endpoint can't be used to trigger scans at will.
 */
cronRouter.get('/scan-drain', async (c) => {
  if (!cronConfigured()) return c.json({ error: 'cron not configured' }, 503);

  const auth = c.req.header('authorization') ?? '';
  const expected = `Bearer ${env.cronSecret}`;
  // Constant-time-ish compare: bail on length mismatch, then char-fold.
  const ok =
    auth.length === expected.length &&
    auth.split('').reduce((acc, ch, i) => acc | (ch.charCodeAt(0) ^ expected.charCodeAt(i)), 0) ===
      0;
  if (!ok) return c.json({ error: 'unauthorized' }, 401);

  // Retention runs first and independently: a scan-drain failure must not be
  // the reason expired telemetry survives another day.
  let purged = { runs: 0, crashes: 0 };
  try {
    purged = await purgeExpiredTelemetry();
    if (purged.runs || purged.crashes) log.info('cron telemetry purge', purged);
  } catch (err) {
    log.error('cron telemetry purge failed', { err: errString(err) });
  }

  try {
    const results = await drainBatch(CRON_DRAIN_MAX);
    if (results.length) log.info('cron scan-drain', { drained: results });
    return c.json({ ok: true, drained: results.length, results, purged });
  } catch (err) {
    log.error('cron scan-drain failed', { err: errString(err) });
    return c.json({ error: 'drain failed', purged }, 500);
  }
});
