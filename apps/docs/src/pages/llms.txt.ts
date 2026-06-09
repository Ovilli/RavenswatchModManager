import { getCollection } from 'astro:content';
// /llms.txt — index for AI assistants (https://llmstxt.org/).
// Title + summary + a flat link list of every docs page. The full text
// lives at /llms-full.txt. Hand-rolled (no plugin) so it works on the
// pinned Starlight 0.30.
import type { APIRoute } from 'astro';

const pageUrl = (base: string, id: string) => (id === 'index' ? `${base}/` : `${base}/${id}/`);

export const GET: APIRoute = async ({ site }) => {
  const base = (site?.toString() ?? 'https://docs.rsmm.me').replace(/\/$/, '');
  const docs = (await getCollection('docs'))
    .filter((e) => e.id !== '404')
    .sort((a, b) => a.id.localeCompare(b.id));

  const lines = [
    '# Ravenswatch Mod Manager — Documentation',
    '',
    '> Browser + desktop mod manager for Ravenswatch. Covers installing and',
    '> authoring mods, the Python SDK, the cooked-asset pipeline, the engine',
    '> symbol map, and reverse-engineering notes.',
    '',
    `Full plain-text corpus: ${base}/llms-full.txt`,
    '',
    '## Docs',
    '',
  ];
  for (const entry of docs) {
    const desc = entry.data.description ? `: ${entry.data.description}` : '';
    lines.push(`- [${entry.data.title}](${pageUrl(base, entry.id)})${desc}`);
  }

  return new Response(`${lines.join('\n')}\n`, {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
};
