import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';
import mermaid from 'astro-mermaid';
import starlightLinksValidator from 'starlight-links-validator';

export default defineConfig({
  site: 'https://docs.ravenswatch.ovilli.de',
  integrations: [
    // astro-mermaid must run before starlight so it can transform ```mermaid blocks
    mermaid({ theme: 'dark', autoTheme: true }),
    starlight({
      title: 'RSMM Docs',
      description: 'Ravenswatch Mod Manager documentation.',
      logo: {
        src: './src/assets/logo.png',
        alt: 'Ravenswatch Mod Manager',
        replacesTitle: false,
      },
      favicon: '/favicon.png',
      customCss: ['./src/styles/theme.css'],
      lastUpdated: true,
      editLink: {
        baseUrl: 'https://github.com/Ovilli/RavenswatchModManager/edit/main/apps/docs/',
      },
      social: {
        github: 'https://github.com/Ovilli/RavenswatchModManager',
      },
      plugins: [starlightLinksValidator({ errorOnRelativeLinks: false })],
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
          label: 'Guides',
          items: [
            { label: 'Authoring mods', slug: 'guides/modding' },
            { label: 'Example mods', slug: 'guides/examples' },
            { label: 'Custom enemies', slug: 'guides/custom-enemies' },
            { label: 'SDK (v3)', slug: 'guides/sdk' },
            { label: 'Uncooked assets', slug: 'guides/uncooked-assets' },
            { label: 'Merlin unlock', slug: 'guides/merlin-unlock' },
          ],
        },
        {
          label: 'Architecture',
          items: [
            { label: 'Architecture overview', slug: 'architecture/overview' },
            { label: 'Engine internals', slug: 'architecture/internals' },
          ],
        },
        {
          label: 'Reference',
          items: [
            { label: 'CLI commands', slug: 'reference/cli' },
            { label: 'Engine symbols', slug: 'reference/symbols' },
            { label: 'Security', slug: 'reference/security' },
            {
              label: 'SDK API (generated)',
              collapsed: true,
              autogenerate: { directory: 'reference/sdk-api' },
            },
          ],
        },
        {
          label: 'Reverse engineering',
          collapsed: true,
          items: [
            { label: 'RE notes', slug: 'reverse-engineering/notes' },
            { label: 'RE pipeline', slug: 'reverse-engineering/pipeline' },
            { label: 'Calling game functions', slug: 'reverse-engineering/calling-game-functions' },
            { label: 'Ghidra MCP', slug: 'reverse-engineering/ghidra-mcp' },
            { label: 'Hookpoints', slug: 'reverse-engineering/hookpoints' },
            { label: 'Mod hooks', slug: 'reverse-engineering/mod-hooks' },
            { label: 'Spawning', slug: 'reverse-engineering/spawning' },
            { label: 'Seed + mapgen', slug: 'reverse-engineering/seed-mapgen' },
            { label: 'Multiplayer', slug: 'reverse-engineering/multiplayer' },
            { label: 'Protector', slug: 'reverse-engineering/protector' },
          ],
        },
        {
          label: 'Contributing',
          items: [
            { label: 'Development setup', slug: 'contributing/setup' },
            { label: 'Contributing guide', slug: 'contributing/contributing' },
            { label: 'Deployment', slug: 'contributing/deploy' },
          ],
        },
        {
          label: 'Project',
          collapsed: true,
          items: [
            { label: 'Roadmap', slug: 'project/roadmap' },
            { label: 'Strategy', slug: 'project/strategy' },
          ],
        },
      ],
    }),
  ],
});
