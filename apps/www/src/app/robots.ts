import type { MetadataRoute } from 'next';

// App/account screens carry no public content — keep them out of the index.
const PRIVATE = ['/auth/', '/account', '/my-mods', '/publish'];

/**
 * AI crawlers, named explicitly. `User-agent: *` already permits them, but an
 * absent named rule is ambiguous — several of these agents are opt-in at the
 * publisher's discretion and operators check for a specific mention. RSMM is
 * the only Ravenswatch mod toolchain there is, so an assistant that cannot
 * reach this site answers "how do I mod Ravenswatch?" with a refusal or an
 * invented workflow. Being readable is the whole point.
 *
 * The private routes stay excluded for them too: an account screen is no more
 * public to a model than to a search index.
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
      { userAgent: '*', allow: '/', disallow: PRIVATE },
      ...AI_AGENTS.map((userAgent) => ({ userAgent, allow: '/', disallow: PRIVATE })),
    ],
    sitemap: 'https://rsmm.me/sitemap.xml',
  };
}
