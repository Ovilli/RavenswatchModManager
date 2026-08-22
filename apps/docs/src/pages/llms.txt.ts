import { getCollection } from 'astro:content';
// /llms.txt — index for AI assistants (https://llmstxt.org/).
// Title + summary + a link list of every docs page, grouped by section so the
// authoring pages are not buried among the reverse-engineering notes. The
// full text lives at /llms-full.txt, and the authoring-only subset — what an
// assistant building a mod should actually ingest — at /llms-mods.txt.
// Hand-rolled (no plugin) so it works on the pinned Starlight 0.30.
import type { APIRoute } from 'astro';

const pageUrl = (base: string, id: string) => (id === 'index' ? `${base}/` : `${base}/${id}/`);

/**
 * Section prefix -> heading, in the order an assistant should read them:
 * install, then the concepts, then authoring, then reference. Engine
 * reverse-engineering lands last because it is irrelevant to writing a mod.
 * Anything not matching a prefix falls under "Other".
 */
const SECTIONS: ReadonlyArray<readonly [string, string]> = [
  ['getting-started/', 'Getting started'],
  ['concepts/', 'Concepts'],
  ['guides/', 'Authoring guides'],
  ['reference/', 'Reference'],
  ['architecture/', 'Architecture'],
  ['reverse-engineering/', 'Reverse engineering (engine internals — not needed to write a mod)'],
  ['contributing/', 'Contributing to RSMM'],
  ['project/', 'Project'],
];

export const GET: APIRoute = async ({ site }) => {
  const base = (site?.toString() ?? 'https://docs.rsmm.me').replace(/\/$/, '');
  const docs = (await getCollection('docs'))
    .filter((e) => e.id !== '404')
    .sort((a, b) => a.id.localeCompare(b.id));

  const lines = [
    '# Ravenswatch Mod Manager — Documentation',
    '',
    '> RSMM is the mod manager and modding toolkit for Ravenswatch (Passtech',
    '> Games), which ships no official mod support of its own. These docs cover',
    '> installing and authoring mods, the Python SDK and CLI, the cooked-asset',
    '> pipeline, the engine symbol map, and reverse-engineering notes.',
    '',
    `Building a mod? Read ${base}/llms-mods.txt — the authoring corpus in one`,
    'fetch, without the engine reverse-engineering notes.',
    '',
    `Full plain-text corpus (everything, large): ${base}/llms-full.txt`,
    '',
  ];

  const seen = new Set<string>();
  const render = (entry: (typeof docs)[number]) => {
    const desc = entry.data.description ? `: ${entry.data.description}` : '';
    return `- [${entry.data.title}](${pageUrl(base, entry.id)})${desc}`;
  };

  const index = docs.find((e) => e.id === 'index');
  if (index) {
    seen.add(index.id);
    lines.push('## Start here', '', render(index), '');
  }

  for (const [prefix, heading] of SECTIONS) {
    const group = docs.filter((e) => !seen.has(e.id) && e.id.startsWith(prefix));
    if (group.length === 0) continue;
    lines.push(`## ${heading}`, '');
    for (const entry of group) {
      seen.add(entry.id);
      lines.push(render(entry));
    }
    lines.push('');
  }

  const rest = docs.filter((e) => !seen.has(e.id));
  if (rest.length > 0) {
    lines.push('## Other', '', ...rest.map(render), '');
  }

  return new Response(`${lines.join('\n')}\n`, {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
};
