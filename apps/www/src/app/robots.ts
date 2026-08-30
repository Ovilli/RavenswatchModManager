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
];

/**
 * Shared diagnostic logs: unlisted URLs holding one user's crash output.
 *
 * Kept out of every training and search corpus, and NOT kept from the agents a
 * person points at a specific URL. Those are different things, and lumping them
 * together broke the feature this path exists for.
 *
 * A share link is made to be handed to whoever is helping you, and that is
 * increasingly an assistant. Blocking `Claude-User` / `ChatGPT-User` from `/l/`
 * bought no privacy — the helper already has the URL, having been given it —
 * and cost a real support thread two rounds of a user hand-pasting 78 KB of log
 * into a chat window because the link they were told to send could not be read.
 */
const SHARED_LOGS = '/l/';

/**
 * AI crawlers, named explicitly. `User-agent: *` already permits them, but an
 * absent named rule is ambiguous — several of these agents are opt-in at the
 * publisher's discretion and operators check for a specific mention. RSMM is
 * the only Ravenswatch mod toolchain there is, so an assistant that cannot
 * reach this site answers "how do I mod Ravenswatch?" with a refusal or an
 * invented workflow. Being readable is the whole point.
 *
 * Split in two, because the operators split them: a CORPUS agent crawls on its
 * own schedule to build a training or search index, while an ON_DEMAND agent
 * fetches one URL because a person in a conversation asked for that URL. Only
 * the first is a corpus, and only the first should lose the shared logs.
 */
const CORPUS_AGENTS = [
  'GPTBot',
  'OAI-SearchBot',
  'ClaudeBot',
  'Claude-SearchBot',
  'anthropic-ai',
  'PerplexityBot',
  'Google-Extended',
  'Applebot-Extended',
  'CCBot',
  'cohere-ai',
  'Meta-ExternalAgent',
];

/** Fetches one URL a user named, in the moment, for that user. Not a corpus. */
const ON_DEMAND_AGENTS = ['ChatGPT-User', 'Claude-User', 'Perplexity-User'];

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      { userAgent: '*', allow: '/' },
      ...CORPUS_AGENTS.map((userAgent) => ({
        userAgent,
        allow: '/',
        disallow: [...PRIVATE, SHARED_LOGS],
      })),
      ...ON_DEMAND_AGENTS.map((userAgent) => ({ userAgent, allow: '/', disallow: PRIVATE })),
    ],
    sitemap: 'https://rsmm.me/sitemap.xml',
  };
}
