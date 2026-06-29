import type { MetadataRoute } from 'next';

const BASE = 'https://rsmm.me';
const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'https://api.rsmm.me';

// Re-fetch the dynamic entries at most hourly so a fresh mod shows up for
// crawlers without hammering the API on every request.
export const revalidate = 3600;

interface Entry {
  slug: string;
  updatedAt?: string;
}

// Page through a list endpoint (the API caps `limit` at 100) until it runs
// dry or we hit a safety ceiling, so every mod/collection lands in the map.
async function fetchEntries(basePath: string): Promise<Entry[]> {
  const PAGE = 100;
  const MAX_PAGES = 50;
  const out: Entry[] = [];
  try {
    for (let page = 0; page < MAX_PAGES; page++) {
      const res = await fetch(`${apiUrl}${basePath}?limit=${PAGE}&offset=${page * PAGE}`, {
        next: { revalidate: 3600 },
      });
      if (!res.ok) break;
      const json = await res.json();
      const items: Entry[] = Array.isArray(json) ? json : (json.items ?? []);
      out.push(...items.filter((i) => i?.slug));
      if (items.length < PAGE) break;
    }
  } catch {
    // Partial results are still a valid (smaller) sitemap.
  }
  return out;
}

// Content-bearing public routes only — app/auth/account screens are excluded
// (they hold no publisher content and must not be tied to ad serving).
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date();
  const staticRoutes = ['', '/download', '/registry', '/c', '/privacy', '/legal'].map((path) => ({
    url: `${BASE}${path}`,
    lastModified: now,
    changeFrequency: (path === '' || path === '/registry' || path === '/c'
      ? 'daily'
      : 'monthly') as 'daily' | 'monthly',
    priority: path === '' ? 1 : 0.7,
  }));

  const [mods, collections] = await Promise.all([
    fetchEntries('/api/mods'),
    fetchEntries('/api/collections'),
  ]);

  const modRoutes = mods.map((m) => ({
    url: `${BASE}/registry/${m.slug}`,
    lastModified: m.updatedAt ? new Date(m.updatedAt) : now,
    changeFrequency: 'weekly' as const,
    priority: 0.6,
  }));

  const collectionRoutes = collections.map((c) => ({
    url: `${BASE}/c/${c.slug}`,
    lastModified: c.updatedAt ? new Date(c.updatedAt) : now,
    changeFrequency: 'weekly' as const,
    priority: 0.5,
  }));

  return [...staticRoutes, ...modRoutes, ...collectionRoutes];
}
