import type { MetadataRoute } from 'next';

const BASE = 'https://ravenswatch.ovilli.de';

// Content-bearing public routes only — app/auth/account screens are excluded
// (they hold no publisher content and must not be tied to ad serving).
export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const routes = ['', '/download', '/registry', '/c', '/privacy', '/legal'];
  return routes.map((path) => ({
    url: `${BASE}${path}`,
    lastModified: now,
    changeFrequency: path === '' || path === '/registry' || path === '/c' ? 'daily' : 'monthly',
    priority: path === '' ? 1 : 0.7,
  }));
}
