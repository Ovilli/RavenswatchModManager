import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';

export default defineConfig({
  integrations: [
    starlight({
      title: 'RSMM Docs',
      description: 'Ravenswatch Mod Manager documentation.',
      social: {
        github: 'https://github.com/Ovilli/RavenswatchModManager',
      },
      sidebar: [
        {
          label: 'Getting started',
          items: [
            { label: 'Installation', slug: 'getting-started/install' },
            { label: 'Desktop app guide', slug: 'getting-started/desktop-app' },
            { label: 'Your first mod', slug: 'getting-started/first-mod' },
            { label: 'Troubleshooting', slug: 'getting-started/troubleshooting' },
          ],
        },
        {
          label: 'Reference',
          items: [{ label: 'CLI commands', slug: 'reference/cli' }],
        },
        {
          label: 'Contributing',
          items: [{ label: 'Development setup', slug: 'contributing/setup' }],
        },
      ],
    }),
  ],
});
