import type { MetadataRoute } from 'next';

// Web app manifest — makes the site installable (Android "Add to home
// screen", desktop PWA). Next auto-emits <link rel="manifest"> for this route.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'Ravenswatch Mod Manager',
    short_name: 'RSMM',
    description: 'Mod manager for Ravenswatch — browser, Windows, Linux.',
    start_url: '/',
    display: 'standalone',
    background_color: '#0a0a0a',
    theme_color: '#0a0a0a',
    icons: [{ src: '/logo.png', sizes: 'any', type: 'image/png' }],
  };
}
