import type { MetadataRoute } from 'next';

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: '/',
      // App/account screens carry no publisher content — keep them out of the index
      // so ads are never associated with thin/navigational pages.
      disallow: ['/auth/', '/account', '/my-mods', '/publish', '/ads/'],
    },
    sitemap: 'https://ravenswatch.ovilli.de/sitemap.xml',
  };
}
