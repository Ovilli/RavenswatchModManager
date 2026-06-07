import { getCollection } from 'astro:content';
// /llms-full.txt — the entire docs corpus as one plain-text file, so an AI
// assistant can ingest every page in a single fetch. Hand-rolled (no plugin)
// to work on the pinned Starlight 0.30.
import type { APIRoute } from 'astro';

const pageUrl = (base: string, id: string) => (id === 'index' ? `${base}/` : `${base}/${id}/`);

export const GET: APIRoute = async ({ site }) => {
  const base = (site?.toString() ?? 'https://docs.ravenswatch.ovilli.de').replace(/\/$/, '');
  const docs = (await getCollection('docs'))
    .filter((e) => e.id !== '404')
    .sort((a, b) => a.id.localeCompare(b.id));

  const parts = [
    '# Ravenswatch Mod Manager — Full documentation',
    '',
    `Concatenated plain text of every docs page. Source: ${base}`,
    '',
  ];
  for (const entry of docs) {
    parts.push(
      '\n---\n',
      `# ${entry.data.title}`,
      entry.data.description ? `\n> ${entry.data.description}\n` : '',
      `Source: ${pageUrl(base, entry.id)}\n`,
      entry.body ?? '',
    );
  }

  return new Response(`${parts.join('\n')}\n`, {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
};
