import { createApiClient } from '@rsmm/api-client';
import { getApiUrl } from './api-url';

// The mod / collection / guide lists are CDN-cached (max-age 60 + 300 stale,
// apps/api/src/app.ts), so right after you publish, edit or delete something
// the list would still show the old state. For that window after a write from
// this browser, list requests carry a `fresh` param: a different cache key, so
// the CDN goes to the API for you while everyone else keeps the cached copy.
const FRESH_WINDOW_MS = 6 * 60_000;
const LAST_WRITE_KEY = 'rsmm:lastWrite';
const CACHED_LIST_PATH = /^\/api\/(mods|collections|guides)$/;

function lastWrite(): number {
  try {
    return Number(localStorage.getItem(LAST_WRITE_KEY)) || 0;
  } catch {
    return 0;
  }
}

/** Cache-busted URL for a CDN-cached list, or the URL unchanged. */
export function freshListUrl(url: string): string {
  if (typeof window === 'undefined') return url;
  const t = lastWrite();
  if (!t || Date.now() - t >= FRESH_WINDOW_MS) return url;
  const u = new URL(url, window.location.href);
  if (!CACHED_LIST_PATH.test(u.pathname)) return url;
  u.searchParams.set('fresh', String(t));
  return u.toString();
}

const freshAfterWriteFetch: typeof fetch = async (input, init) => {
  const method = (init?.method ?? 'GET').toUpperCase();
  const url = method === 'GET' ? freshListUrl(String(input)) : String(input);
  const res = await fetch(url, init);
  if (method !== 'GET' && res.ok && typeof window !== 'undefined') {
    try {
      localStorage.setItem(LAST_WRITE_KEY, String(Date.now()));
    } catch {}
  }
  return res;
};

export const api = createApiClient({
  baseUrl: getApiUrl(),
  fetch: freshAfterWriteFetch,
});
