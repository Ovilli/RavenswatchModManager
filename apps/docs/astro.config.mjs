import starlight from '@astrojs/starlight';
import { defineConfig, passthroughImageService } from 'astro/config';
import mermaid from 'astro-mermaid';
import starlightLinksValidator from 'starlight-links-validator';

export default defineConfig({
  site: 'https://docs.rsmm.me',
  // Serve images as-is (no Sharp dependency in CI / Vercel build).
  image: { service: passthroughImageService() },
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
      // Site-wide social-preview image (link unfurls on Discord/Twitter/etc).
      head: [
        { tag: 'meta', attrs: { property: 'og:image', content: 'https://docs.rsmm.me/og.png' } },
        { tag: 'meta', attrs: { property: 'og:type', content: 'website' } },
        { tag: 'meta', attrs: { name: 'twitter:card', content: 'summary_large_image' } },
        { tag: 'meta', attrs: { name: 'twitter:image', content: 'https://docs.rsmm.me/og.png' } },
        // AI-assistant ingestion (https://llmstxt.org/).
        { tag: 'link', attrs: { rel: 'alternate', type: 'text/plain', title: 'llms.txt', href: '/llms.txt' } },
      ],
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
          label: 'Concepts',
          items: [
            { label: 'Coming from Minecraft', slug: 'concepts/from-minecraft' },
            { label: 'The mod lifecycle', slug: 'concepts/mod-lifecycle' },
            { label: 'Content kinds (registries)', slug: 'concepts/content-kinds' },
            { label: 'Tags', slug: 'concepts/tags' },
            { label: 'The symbol map (mappings)', slug: 'concepts/mappings' },
            { label: 'Mods ship data, not code', slug: 'concepts/data-not-code' },
          ],
        },
        {
          label: 'Guides',
          items: [
            { label: 'Authoring mods', slug: 'guides/modding' },
            { label: 'Example mods', slug: 'guides/examples' },
            { label: 'Custom items', slug: 'guides/custom-items' },
            { label: 'Custom enemies', slug: 'guides/custom-enemies' },
            { label: 'Custom skills (talents)', slug: 'guides/custom-skills' },
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
            { label: 'Conventions & best practices', slug: 'reference/conventions' },
            { label: 'Engine symbols', slug: 'reference/symbols' },
            { label: 'Glossary', slug: 'reference/glossary' },
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
            { label: 'Event systems', slug: 'reverse-engineering/event-systems' },
            { label: 'Entity values', slug: 'reverse-engineering/entity-values' },
            { label: 'Stats & XP', slug: 'reverse-engineering/stats' },
            { label: 'Combat & damage', slug: 'reverse-engineering/combat-damage' },
            { label: 'Skills system', slug: 'reverse-engineering/skills-system' },
            { label: 'Pickable talents', slug: 'reverse-engineering/pickable-talents' },
            { label: 'Items (magical objects)', slug: 'reverse-engineering/items' },
            { label: 'Rewards', slug: 'reverse-engineering/rewards' },
            { label: 'Heroes', slug: 'reverse-engineering/heroes' },
            { label: 'Skins', slug: 'reverse-engineering/skins' },
            { label: 'Melodies', slug: 'reverse-engineering/melodies' },
            { label: 'Enemies', slug: 'reverse-engineering/enemies' },
            { label: 'Bosses', slug: 'reverse-engineering/bosses' },
            { label: 'Spawning', slug: 'reverse-engineering/spawning' },
            { label: 'Spawn system', slug: 'reverse-engineering/spawn-system' },
            { label: 'Game modifiers', slug: 'reverse-engineering/game-modifiers' },
            { label: 'Maps & chapters', slug: 'reverse-engineering/maps-chapters' },
            { label: 'UI & the book menu', slug: 'reverse-engineering/ui-menus' },
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
