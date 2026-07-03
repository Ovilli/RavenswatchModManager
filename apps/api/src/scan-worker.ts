import { virusTotalConfigured } from './env.js';
import { log } from './logger.js';
import { SCAN_TICK_SECONDS, drainOnce } from './scan-service.js';

let timer: ReturnType<typeof setInterval> | null = null;
let running = false;

/**
 * Start the in-process scan worker: one queue item per tick. Single-flight —
 * a tick is skipped if the previous scan is still going (a scan can take
 * ~18s of polling). One scan per SCAN_TICK_SECONDS keeps us under the free
 * tier's 4 lookups/min. No-op if VirusTotal isn't configured or already started.
 */
export function startScanWorker(): void {
  if (timer) return;
  if (!virusTotalConfigured()) {
    log.info('scan worker not started (VirusTotal not configured)');
    return;
  }
  log.info('scan worker started', { tickSeconds: SCAN_TICK_SECONDS });
  timer = setInterval(async () => {
    if (running) return;
    running = true;
    try {
      const r = await drainOnce();
      if (r) log.info('scan worker tick', r);
    } catch (err) {
      log.error('scan worker tick failed', { err: String(err) });
    } finally {
      running = false;
    }
  }, SCAN_TICK_SECONDS * 1000);
  // Don't keep the event loop alive just for this timer.
  timer.unref?.();
}

export function stopScanWorker(): void {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}

/**
 * Run one drain immediately, detached from the current request. On serverless
 * the interval above only fires while an instance happens to stay warm, which
 * starves the queue — so the enqueue and scan-status handlers each nudge it
 * instead: every publish and every progress poll advances the queue. Safe to
 * call freely: drainOnce is single-flight per instance and a concurrent kick
 * is a no-op.
 *
 * The promise is registered with the platform's request context (Vercel's
 * waitUntil) when present so the instance isn't suspended mid-scan; elsewhere
 * it just runs detached.
 */
export function kickScanWorker(): void {
  if (!virusTotalConfigured()) return;
  const work = drainOnce()
    .then((r) => {
      if (r) log.info('scan worker kick', r);
    })
    .catch((err) => log.error('scan worker kick failed', { err: String(err) }));
  try {
    const ctx = (
      globalThis as {
        [key: symbol]:
          | { get?: () => { waitUntil?: (p: Promise<unknown>) => void } | undefined }
          | undefined;
      }
    )[Symbol.for('@vercel/request-context')];
    ctx?.get?.()?.waitUntil?.(work);
  } catch {
    // Best-effort — the detached promise still runs if the instance survives.
  }
}
