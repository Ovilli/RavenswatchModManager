import { getApiUrl } from './api-url';

/**
 * Result of a server-side lookup for a single content entity.
 *
 * The three states exist because a page must react differently to each:
 * `missing` is a real 404 (the row is gone — send Google a 404, not a 200 with
 * an empty shell), while `error` is a transient API failure and must NOT turn a
 * live URL into a 404 during an outage. Collapsing both into `null` — which is
 * what every `[slug]/layout.tsx` used to do — produced soft-404s: a deleted mod
 * answered 200 with the generic "Mod · …" title and, because the fallback
 * metadata set no `alternates`, inherited the root layout's `canonical: '/'`,
 * telling Google every dead mod URL was the home page.
 */
export type Entity<T> = { state: 'ok'; data: T } | { state: 'missing' } | { state: 'error' };

/**
 * Fetch one entity from the API.
 *
 * Only an explicit 404/410 from the API counts as `missing` — never a parse
 * failure, a 5xx, or a network error. Deduped by Next within a request when the
 * URL and options match, so `generateMetadata` and the layout body share one
 * round-trip (that is why the revalidate window is fixed here).
 */
export async function fetchEntity<T>(path: string): Promise<Entity<T>> {
  let res: Response;
  try {
    res = await fetch(`${getApiUrl()}${path}`, { next: { revalidate: 60 } });
  } catch {
    return { state: 'error' };
  }
  if (res.status === 404 || res.status === 410) return { state: 'missing' };
  if (!res.ok) return { state: 'error' };
  try {
    return { state: 'ok', data: (await res.json()) as T };
  } catch {
    return { state: 'error' };
  }
}
