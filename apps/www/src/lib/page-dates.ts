/**
 * When each static route's OWN copy last changed, for the sitemap's `lastmod`.
 *
 * Hand-kept on purpose: `new Date()` changes on every request and a build-time
 * file mtime changes on every deploy, and Google learns to ignore a sitemap
 * whose lastmod always moves. Edit a page → bump its date in the same commit;
 * `sitemap.test.ts` fails when git shows a later edit to the page or its
 * segment layout than the date recorded here.
 *
 * Keys are the route path; `dir` is the route segment under `src/app`.
 */
export const PAGE_UPDATED: Record<string, { date: string; dir: string }> = {
  '': { date: '2026-09-18', dir: '.' },
  '/download': { date: '2026-09-13', dir: 'download' },
  '/registry': { date: '2026-09-13', dir: 'registry/(list)' },
  '/c': { date: '2026-09-13', dir: 'c' },
  '/guides': { date: '2026-09-13', dir: 'guides' },
  '/modding': { date: '2026-09-13', dir: 'modding' },
  '/about': { date: '2026-09-02', dir: 'about' },
  '/contact': { date: '2026-07-02', dir: 'contact' },
  '/privacy': { date: '2026-09-01', dir: 'privacy' },
  '/legal': { date: '2026-09-01', dir: 'legal' },
  '/dmca': { date: '2026-07-02', dir: 'dmca' },
};

/** The later of `a` and every parseable date in `rest`; undefined-safe. */
export function latest(a: Date, rest: (string | Date | null | undefined)[]): Date {
  let out = a;
  for (const r of rest) {
    if (!r) continue;
    const d = r instanceof Date ? r : new Date(r);
    if (!Number.isNaN(d.getTime()) && d > out) out = d;
  }
  return out;
}
