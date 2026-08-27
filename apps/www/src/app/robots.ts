import type { MetadataRoute } from 'next';

/**
 * App/account screens carry no public content, but they are NOT excluded here.
 *
 * A `Disallow:` only blocks the fetch. Google still discovers these URLs from
 * the nav, cannot read the `noindex` it is forbidden to fetch, and files every
 * one under "Blocked by robots.txt" in Search Console — which is exactly the
 * report this file used to generate. The documented fix is the opposite of
 * intuition: let Googlebot crawl them and let it read `noindex`. That lives in
 * `src/lib/noindex.ts`, applied by a `layout.tsx` in each private segment
 * (`/auth`, `/account`, `/my-mods`, `/publish`, `/admin`, `/notifications`,
 * plus the `/c/new` and `/guides/new` forms).
 *
 * Crawling leaks nothing: every one of those screens fetches its data
 * client-side behind a session no crawler holds.
 *
 * The AI agents below keep the disallow, because their rules govern *training
 * and answer* corpora rather than indexing — nothing they skip shows up as a
 * Search Console coverage problem, and an account screen is no more public to a
 * model than to a search index.
 */
const PRIVATE = [
  '/auth/',
  '/account',
  '/my-mods',
  '/publish',
  '/admin',
  '/notifications',
  // Shared diagnostic logs. Unlisted URLs pasted into support threads, holding
  // one user's crash output — nothing that belongs in a training corpus.
  '/l/',
];

/**
 * AI crawlers, named explicitly. `User-agent: *` already permits them, but an
 * absent named rule is ambiguous — several of these agents are opt-in at the
 * publisher's discretion and operators check for a specific mention. RSMM is
 * the only Ravenswatch mod toolchain there is, so an assistant that cannot
 * reach this site answers "how do I mod Ravenswatch?" with a refusal or an
 * invented workflow. Being readable is the whole point.
 */
const AI_AGENTS = [
  'GPTBot',
  'OAI-SearchBot',
  'ChatGPT-User',
  'ClaudeBot',
  'Claude-User',
  'Claude-SearchBot',
  'anthropic-ai',
  'PerplexityBot',
  'Perplexity-User',
  'Google-Extended',
  'Applebot-Extended',
  'CCBot',
  'cohere-ai',
  'Meta-ExternalAgent',
];

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      { userAgent: '*', allow: '/' },
      ...AI_AGENTS.map((userAgent) => ({ userAgent, allow: '/', disallow: PRIVATE })),
    ],
    sitemap: 'https://rsmm.me/sitemap.xml',
  };
}
