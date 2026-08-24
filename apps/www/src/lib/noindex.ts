import type { Metadata } from 'next';

/**
 * Metadata for a segment that must never enter a search index.
 *
 * These routes used to be excluded with `Disallow:` in robots.txt, which is the
 * wrong tool: a disallow only stops the crawl, so Google still discovers the URL
 * from internal links, cannot read a `noindex` it is forbidden to fetch, and
 * files the URL under "Blocked by robots.txt" (it may even index the bare URL).
 * Letting Googlebot fetch the page and read `noindex` is Google's own documented
 * fix. Nothing is leaked by the crawl: every one of these screens renders its
 * data client-side behind a session the crawler does not have.
 *
 * `follow: false` because there is nothing here worth following either.
 */
export const noindex: Metadata = {
  robots: { index: false, follow: false },
};
