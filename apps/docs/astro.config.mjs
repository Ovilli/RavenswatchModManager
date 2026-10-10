import starlight from '@astrojs/starlight';
import mermaid from 'astro-mermaid';
import { defineConfig, passthroughImageService } from 'astro/config';
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
      // Source: `scripts/og-card.html` — keep the dimensions below in sync with
      // the rendered PNG. Declaring them lets an unfurler lay out the card
      // before it has fetched the image, which is what makes a shared link
      // render as a large card rather than a thumbnail.
      head: [
        { tag: 'meta', attrs: { property: 'og:image', content: 'https://docs.rsmm.me/og.png' } },
        { tag: 'meta', attrs: { property: 'og:image:type', content: 'image/png' } },
        { tag: 'meta', attrs: { property: 'og:image:width', content: '1200' } },
        { tag: 'meta', attrs: { property: 'og:image:height', content: '630' } },
        {
          tag: 'meta',
          attrs: { property: 'og:image:alt', content: 'Ravenswatch Mod Manager documentation' },
        },
        { tag: 'meta', attrs: { property: 'og:type', content: 'website' } },
        { tag: 'meta', attrs: { name: 'twitter:card', content: 'summary_large_image' } },
        { tag: 'meta', attrs: { name: 'twitter:image', content: 'https://docs.rsmm.me/og.png' } },
        {
          tag: 'meta',
          attrs: { name: 'twitter:image:alt', content: 'Ravenswatch Mod Manager documentation' },
        },
        // AI-assistant ingestion (https://llmstxt.org/). `llms-mods.txt` is
        // advertised alongside the index because it, not the full corpus, is
        // what an assistant building a mod should actually pull.
        {
          tag: 'link',
          attrs: { rel: 'alternate', type: 'text/plain', title: 'llms.txt', href: '/llms.txt' },
        },
        {
          tag: 'link',
          attrs: {
            rel: 'alternate',
            type: 'text/plain',
            title: 'llms-mods.txt',
            href: '/llms-mods.txt',
          },
        },
        {
          tag: 'link',
          attrs: {
            rel: 'alternate',
            type: 'text/plain',
            title: 'llms-full.txt',
            href: '/llms-full.txt',
          },
        },
      ],
      editLink: {
        baseUrl: 'https://github.com/Ovilli/RavenswatchModManager/edit/main/apps/docs/',
      },
      social: [
        {
          icon: 'github',
          label: 'GitHub',
          href: 'https://github.com/Ovilli/RavenswatchModManager',
        },
      ],
      // /editor/ is a standalone Astro page (the web editor), not a Starlight doc.
      plugins: [starlightLinksValidator({ errorOnRelativeLinks: false, exclude: ['/editor/'] })],
      sidebar: [
        {
          label: 'Playing with mods',
          items: [
            { label: 'Start here', slug: 'getting-started/start-here' },
            { label: 'Install the app', slug: 'getting-started/install' },
            { label: 'Using the app', slug: 'getting-started/desktop-app' },
            { label: 'FAQ', slug: 'getting-started/faq' },
            { label: 'Troubleshooting', slug: 'getting-started/troubleshooting' },
          ],
        },
        {
          label: 'Making mods',
          items: [
            { label: 'Make your first mod', slug: 'getting-started/first-mod' },
            { label: 'Set up the modding tools', slug: 'getting-started/modding-tools' },
            { label: 'Web editor (in your browser)', slug: 'guides/web-editor' },
            { label: 'First mod, by kind', slug: 'guides/first-mod-by-kind' },
            { label: 'Example mods', slug: 'guides/examples' },
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
            { label: 'Build a mod with an AI assistant', slug: 'guides/ai-assistant' },
            { label: 'Custom items', slug: 'guides/custom-items' },
            { label: 'Custom enemies', slug: 'guides/custom-enemies' },
            { label: 'Talent modding, step by step', slug: 'guides/talent-tutorial' },
            { label: 'Advanced talent modding', slug: 'guides/talent-tutorial-advanced' },
            { label: 'Custom skills (talents)', slug: 'guides/custom-skills' },
            { label: 'SDK (v3)', slug: 'guides/sdk' },
            { label: 'Uncooked assets', slug: 'guides/uncooked-assets' },
            { label: 'Hero unlock gates', slug: 'guides/merlin-unlock' },
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
            { label: 'Lua gameplay API', slug: 'reference/lua-api' },
            { label: 'Engine symbols', slug: 'reference/symbols' },
            { label: 'Glossary', slug: 'reference/glossary' },
            { label: 'Talent name lookup', slug: 'reference/talent-names' },
            { label: 'Security', slug: 'reference/security' },
            {
              label: 'SDK API (generated)',
              collapsed: true,
              items: [{ autogenerate: { directory: 'reference/sdk-api' } }],
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
            { label: 'Anatomy of an entity', slug: 'reverse-engineering/entity-anatomy' },
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
            { label: 'Level format & build path', slug: 'reverse-engineering/level-format' },
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
