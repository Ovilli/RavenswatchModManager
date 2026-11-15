/**
 * The loader's installed-version status, read once and shared.
 *
 * The version footer (every screen) and Settings → Updates both asked the CLI
 * for it on mount, and each ask is a sidecar start plus a network round trip, so
 * opening Settings repeated what the footer had already fetched at launch. They
 * now share one result for ten minutes. A real update, or anything that writes to
 * the game, drops it (see `session-cache.ts`), and the result of a real update is
 * stored directly since it reports the same fields a check does.
 */
import { type UpdateLoaderResult, updateLoader } from './rsmm';
import { cachedFor, prime } from './session-cache';

const KEY = 'loader-status';
const TEN_MINUTES = 10 * 60_000;

/** Read-only probe of the planted loader; `null` when it cannot be determined. */
export function loaderStatus(fresh = false): Promise<UpdateLoaderResult | null> {
  return cachedFor(KEY, TEN_MINUTES, () => updateLoader({ checkOnly: true }), fresh);
}

/** Record the outcome of a real update so the next reader needs no check. */
export function noteLoaderResult(result: UpdateLoaderResult | null): void {
  if (!result) return;
  prime(KEY, result);
  latest = result;
  for (const fn of listeners) fn();
}

let latest: UpdateLoaderResult | null = null;
const listeners = new Set<() => void>();

/** The newest result noted this session, or null before any real update ran. */
export function getNotedLoaderResult(): UpdateLoaderResult | null {
  return latest;
}

/** Notified whenever a loader update or check lands, so a screen that read the
 *  status at mount (the footer, Settings) can show the new version. */
export function subscribeLoaderResult(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}
