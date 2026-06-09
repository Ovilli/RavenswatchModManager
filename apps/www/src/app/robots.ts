import type { MetadataRoute } from 'next';

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: '/',
      // App/account screens carry no public content — keep them out of the index.
      disallow: ['/auth/', '/account', '/my-mods', '/publish'],
    },
    sitemap: 'https://rsmm.me/sitemap.xml',
  };
}
