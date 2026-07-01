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
