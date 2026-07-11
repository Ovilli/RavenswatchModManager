import { Hono } from 'hono';
import { cronConfigured, env } from '../env.js';
import { errString, log } from '../logger.js';
import { drainBatch } from '../scan-service.js';
import type { AppEnv } from '../types.js';

export const cronRouter = new Hono<AppEnv>();

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

  try {
    const results = await drainBatch(CRON_DRAIN_MAX);
    if (results.length) log.info('cron scan-drain', { drained: results });
    return c.json({ ok: true, drained: results.length, results });
  } catch (err) {
    log.error('cron scan-drain failed', { err: errString(err) });
    return c.json({ error: 'drain failed' }, 500);
  }
});
