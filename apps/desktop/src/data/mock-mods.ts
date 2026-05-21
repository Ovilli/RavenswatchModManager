/**
 * @deprecated Replace with real API calls via `@rsmm/api-client`.
 *
 * Migration guide:
 * 1. Add React Query hooks in `lib/api.ts` using `api.mods.list()` and `api.mods.get(slug)`
 * 2. Replace `getMod()` in `store/index.ts` with a React Query cache lookup
 * 3. Remove `MOCK_MODS` usage from `browse.tsx` and `mod.$slug.tsx` route files
 * 4. Extend API schemas if fields like `category`, `tags`, `writes` are needed,
 *    or combine API data with local manifest info from the Python CLI sidecar
 *
 * See packages/api-client/src/index.ts for the available API methods.
 */
export type ModCategory =
  | 'gameplay'
  | 'balance'
  | 'cosmetic'
  | 'qol'
  | 'audio'
  | 'difficulty'
  | 'speedrun'
  | 'utility';

export type ModStatus = 'installed' | 'available';

export interface MockMod {
  id: string;
  slug: string;
  name: string;
  author: string;
  version: string;
  latestVersion: string;       // > version means outdated
  category: ModCategory;
  summary: string;
  description: string;
  changelog: string;
  rating: number;              // 0-5
  downloads: number;
  sizeKb: number;
  tags: string[];
  dependencies: string[];
  /** Cooked file paths this mod writes. Two mods that share a path conflict. */
  writes: string[];
  /** Compatible Ravenswatch build numbers (informational). */
  gameBuild: string;
  /** Store-page hero image. Resolved relative to the mod's asset bundle. */
  image?: string;
  /** Long-form store-page copy in Markdown. Rendered on the mod detail page. */
  markdown: string;
}

type RawMod = Omit<MockMod, 'markdown'> & { markdown?: string };

const RAW_MODS: RawMod[] = [
  {
    id: 'aurora-paths',
    slug: 'aurora-paths',
    name: 'Aurora Paths',
    author: 'mira_of_thorns',
    version: '1.2.0',
    latestVersion: '1.2.0',
    category: 'cosmetic',
    summary: 'Repaints forest map borders with aurora gradients.',
    description: 'Replaces the muted forest-zone tile borders with a soft aurora gradient, sampled from the Northern Lights palette used in the Ravenswatch concept art. No gameplay change.',
    changelog: '1.2.0 — fix flicker on entering camp\n1.1.0 — add snowfall variant\n1.0.0 — initial',
    rating: 4.6,
    downloads: 12480,
    sizeKb: 312,
    tags: ['visual', 'biome', 'lights'],
    dependencies: [],
    writes: ['Maps/Forest/Borders.tex'],
    gameBuild: '1.2.x',
  },
  {
    id: 'hyper-aggro',
    slug: 'hyper-aggro',
    name: 'Hyper Aggro',
    author: 'thornveil',
    version: '0.4.1',
    latestVersion: '0.4.1',
    category: 'difficulty',
    summary: 'Enemies always sprint towards the hero. No hiding.',
    description: 'Reduces all enemy patience timers to zero. They will always commit to the chase. Companions are unaffected.',
    changelog: '0.4.1 — fix bosses freezing on phase transition\n0.4.0 — initial public',
    rating: 4.1,
    downloads: 5311,
    sizeKb: 92,
    tags: ['ai', 'hard'],
    dependencies: [],
    writes: ['Encounters/AI_Patience.ot'],
    gameBuild: '1.2.x',
  },
  {
    id: 'twin-fang',
    slug: 'twin-fang',
    name: 'Twin Fang',
    author: 'forge_o_clock',
    version: '2.0.0',
    latestVersion: '2.0.0',
    category: 'gameplay',
    summary: 'Beowulf dual-wields. New stance, new combo tree.',
    description: 'Adds a second axe to Beowulf and a stance toggle. Combo finishers chain into bleeds. Custom animation set.',
    changelog: '2.0.0 — animation pass\n1.0.0 — initial',
    rating: 4.8,
    downloads: 31200,
    sizeKb: 4820,
    tags: ['hero', 'combat', 'beowulf'],
    dependencies: [],
    writes: ['Heroes/Beowulf/Combos.lua', 'Heroes/Beowulf/Stance.lua'],
    gameBuild: '1.2.x',
  },
  {
    id: 'gilt-runes',
    slug: 'gilt-runes',
    name: 'Gilt Runes',
    author: 'inksmith',
    version: '1.5.3',
    latestVersion: '1.6.0', // OUT OF DATE
    category: 'cosmetic',
    summary: 'Gilded outlines for magical objects. Pickups glow warmer.',
    description: 'Replaces the cool-blue magical-object outlines with a candlelight gilt. Adjusts pickup glows to match. Pure cosmetic.',
    changelog: '1.6.0 — match Crow magical reveal animation\n1.5.3 — bug fix\n1.5.0 — initial',
    rating: 4.4,
    downloads: 18800,
    sizeKb: 540,
    tags: ['visual', 'items'],
    dependencies: [],
    writes: ['UI/Outlines.shader'],
    gameBuild: '1.1.x → 1.2.x',
  },
  {
    id: 'silent-camp',
    slug: 'silent-camp',
    name: 'Silent Camp',
    author: 'reed_hush',
    version: '0.9.0',
    latestVersion: '0.9.0',
    category: 'audio',
    summary: 'Mutes ambient camp chatter for focused runs.',
    description: 'Silences NPC ambient lines at camp. Music + combat audio unchanged. Useful for streamers running long sessions.',
    changelog: '0.9.0 — initial',
    rating: 4.2,
    downloads: 2210,
    sizeKb: 18,
    tags: ['audio', 'streamer'],
    dependencies: [],
    writes: ['Audio/CampChatter.bank'],
    gameBuild: '1.2.x',
  },
  {
    id: 'pinned-seed',
    slug: 'pinned-seed',
    name: 'Pinned Seed',
    author: 'rsmm-examples',
    version: '0.3.0',
    latestVersion: '0.3.0',
    category: 'speedrun',
    summary: 'Force a deterministic RNG seed for the entire run.',
    description: 'Speedrun helper. Sets the run seed from a hex string. All drops, room layouts, and encounters become deterministic.',
    changelog: '0.3.0 — UI panel in pause menu',
    rating: 4.7,
    downloads: 9400,
    sizeKb: 64,
    tags: ['speedrun', 'rng'],
    dependencies: [],
    writes: ['Run/Seed.ot'],
    gameBuild: '1.2.x',
  },
  {
    id: 'lantern-hud',
    slug: 'lantern-hud',
    name: 'Lantern HUD',
    author: 'mira_of_thorns',
    version: '1.1.0',
    latestVersion: '1.1.0',
    category: 'qol',
    summary: 'Rewrites the HUD in warm gilt tones. Larger health bar.',
    description: 'Repaints the top-left HUD: health bar gilt, mana bar amber, combo counter set in italics. Larger numeric readouts.',
    changelog: '1.1.0 — readability pass\n1.0.0 — initial',
    rating: 4.5,
    downloads: 21400,
    sizeKb: 410,
    tags: ['hud', 'visual'],
    dependencies: [],
    writes: ['UI/HUD.tex', 'UI/Fonts/HUD.fnt'],
    gameBuild: '1.2.x',
  },
  {
    id: 'wolfheart-buff',
    slug: 'wolfheart-buff',
    name: 'Wolfheart Buff',
    author: 'pack_runner',
    version: '0.7.2',
    latestVersion: '0.7.2',
    category: 'balance',
    summary: 'Buffs the Wolf hero kit. +12% damage at low HP.',
    description: 'Balance pass for the Wolf hero. Adds a low-HP damage tier. Designed for solo Chaos runs.',
    changelog: '0.7.2 — fix tooltip number\n0.7.0 — initial',
    rating: 3.9,
    downloads: 1840,
    sizeKb: 24,
    tags: ['balance', 'wolf'],
    dependencies: [],
    writes: ['Heroes/Wolf/Stats.ot'],
    gameBuild: '1.2.x',
  },
  {
    id: 'wolf-iron-fang',
    slug: 'wolf-iron-fang',
    name: 'Iron Fang Wolf',
    author: 'siege_smith',
    version: '0.2.0',
    latestVersion: '0.2.0',
    category: 'balance',
    summary: 'Reworks Wolf to a tank. +HP, -speed.',
    description: 'Alternative Wolf rework. Heavy armour mod — adds 25% HP, removes dash invul frames.',
    changelog: '0.2.0 — initial',
    rating: 3.2,
    downloads: 420,
    sizeKb: 28,
    tags: ['balance', 'wolf', 'tank'],
    dependencies: [],
    // Conflicts with wolfheart-buff: both write Heroes/Wolf/Stats.ot
    writes: ['Heroes/Wolf/Stats.ot'],
    gameBuild: '1.2.x',
  },
  {
    id: 'merchant-shuffle',
    slug: 'merchant-shuffle',
    name: 'Merchant Shuffle',
    author: 'coinpurse',
    version: '1.0.4',
    latestVersion: '1.0.4',
    category: 'gameplay',
    summary: 'Reshuffles merchant inventory mid-run on each visit.',
    description: 'Merchant inventory rerolls between visits. Higher variance, encourages risk runs.',
    changelog: '1.0.4 — respects pity timer',
    rating: 4.3,
    downloads: 7700,
    sizeKb: 56,
    tags: ['economy'],
    dependencies: [],
    writes: ['Merchants/Inventory.lua'],
    gameBuild: '1.2.x',
  },
  {
    id: 'long-night',
    slug: 'long-night',
    name: 'Long Night',
    author: 'reed_hush',
    version: '0.6.0',
    latestVersion: '0.6.0',
    category: 'difficulty',
    summary: 'Doubles night-phase length. Bosses spawn earlier.',
    description: 'Stretches every nightfall. Useful for theatrical runs and for testing late-game balance.',
    changelog: '0.6.0 — initial',
    rating: 3.8,
    downloads: 980,
    sizeKb: 38,
    tags: ['pacing', 'hard'],
    dependencies: [],
    writes: ['Encounters/NightPhase.ot'],
    gameBuild: '1.2.x',
  },
  {
    id: 'mods-tab',
    slug: 'mods-tab',
    name: 'Mods Tab',
    author: 'rsmm',
    version: '1.0.0',
    latestVersion: '1.0.0',
    category: 'utility',
    summary: 'Adds an in-game Mods page to the Social book.',
    description: 'Adds a Social-book tab listing every active mod. Useful for verifying a co-op loadout matches.',
    changelog: '1.0.0 — initial',
    rating: 4.9,
    downloads: 41200,
    sizeKb: 8,
    tags: ['utility', 'in-game'],
    dependencies: [],
    writes: ['UI/SocialBook/ModsTab.lua'],
    gameBuild: '1.2.x',
  },
  {
    id: 'crow-dash',
    slug: 'crow-dash',
    name: 'Crow Dash Tweaks',
    author: 'forge_o_clock',
    version: '0.4.0',
    latestVersion: '0.4.0',
    category: 'balance',
    summary: 'Smooths Crow dash recovery. -2 frames.',
    description: 'Trims two frames off Crow’s dash recovery. Tested against speedrun routes.',
    changelog: '0.4.0 — initial',
    rating: 4.0,
    downloads: 1500,
    sizeKb: 12,
    tags: ['balance', 'crow', 'speedrun'],
    dependencies: [],
    writes: ['Heroes/Crow/Dash.ot'],
    gameBuild: '1.2.x',
  },
  {
    id: 'parchment-codex',
    slug: 'parchment-codex',
    name: 'Parchment Codex',
    author: 'inksmith',
    version: '2.1.0',
    latestVersion: '2.1.0',
    category: 'qol',
    summary: 'Rebinds the codex UI to a parchment book layout.',
    description: 'Rewrites the codex screen as a two-page parchment spread with hand-set type.',
    changelog: '2.1.0 — page-turn animation\n2.0.0 — layout rewrite',
    rating: 4.8,
    downloads: 22100,
    sizeKb: 980,
    tags: ['ui', 'visual'],
    dependencies: [],
    writes: ['UI/Codex.lua', 'UI/Codex.tex'],
    gameBuild: '1.2.x',
  },
  {
    id: 'rune-rain',
    slug: 'rune-rain',
    name: 'Rune Rain',
    author: 'thornveil',
    version: '0.3.0',
    latestVersion: '0.3.0',
    category: 'cosmetic',
    summary: 'Falling rune particles during night phases.',
    description: 'Adds a slow falling rune particle effect during night. Pure cosmetic, no FPS hit on tested rigs.',
    changelog: '0.3.0 — initial',
    rating: 3.7,
    downloads: 640,
    sizeKb: 220,
    tags: ['particles', 'visual'],
    dependencies: [],
    writes: ['Particles/RuneRain.fx'],
    gameBuild: '1.2.x',
  },
  {
    id: 'co-op-hud',
    slug: 'co-op-hud',
    name: 'Co-op HUD',
    author: 'pack_runner',
    version: '1.0.0',
    latestVersion: '1.0.0',
    category: 'qol',
    summary: 'Adds party member health bars in co-op.',
    description: 'Pinned ally bars top-right in co-op. Hidden in solo.',
    changelog: '1.0.0 — initial',
    rating: 4.4,
    downloads: 11200,
    sizeKb: 72,
    tags: ['co-op', 'hud'],
    dependencies: ['lantern-hud'],
    writes: ['UI/PartyBars.lua'],
    gameBuild: '1.2.x',
  },
  {
    id: 'iron-economy',
    slug: 'iron-economy',
    name: 'Iron Economy',
    author: 'coinpurse',
    version: '0.5.0',
    latestVersion: '0.5.0',
    category: 'balance',
    summary: 'Halves all gold drops. Tighter run economy.',
    description: 'Halves gold drops from kills and chests. Camp upgrades unaffected. For people who think the economy is too loose.',
    changelog: '0.5.0 — initial',
    rating: 3.5,
    downloads: 380,
    sizeKb: 18,
    tags: ['economy', 'hard'],
    dependencies: [],
    writes: ['Economy/Drops.ot'],
    gameBuild: '1.2.x',
  },
  {
    id: 'cinder-borders',
    slug: 'cinder-borders',
    name: 'Cinder Borders',
    author: 'mira_of_thorns',
    version: '0.8.0',
    latestVersion: '0.8.0',
    category: 'cosmetic',
    summary: 'Replaces UI window borders with charred wood frames.',
    description: 'Repaints UI window borders with photographed charred-wood textures. Subtle.',
    changelog: '0.8.0 — initial',
    rating: 4.1,
    downloads: 3120,
    sizeKb: 320,
    tags: ['ui', 'visual'],
    dependencies: [],
    writes: ['UI/Frames.tex'],
    gameBuild: '1.2.x',
  },
  {
    id: 'witchfire-fx',
    slug: 'witchfire-fx',
    name: 'Witchfire FX',
    author: 'thornveil',
    version: '1.0.0',
    latestVersion: '1.0.0',
    category: 'cosmetic',
    summary: 'Recolors fire spells to violet witchfire.',
    description: 'Reskins all fire VFX with a violet palette. Damage values unchanged.',
    changelog: '1.0.0 — initial',
    rating: 4.0,
    downloads: 4400,
    sizeKb: 180,
    tags: ['vfx', 'visual'],
    dependencies: [],
    writes: ['VFX/Fire.fx'],
    gameBuild: '1.2.x',
  },
  {
    id: 'speed-runner',
    slug: 'speed-runner',
    name: 'Speedrunner Splits',
    author: 'forge_o_clock',
    version: '1.2.1',
    latestVersion: '1.2.1',
    category: 'speedrun',
    summary: 'In-run split overlay with PB compare.',
    description: 'Floating splits overlay. Records boss kill times and end-of-act times. Compares against your PB.',
    changelog: '1.2.1 — fix PB save on crash',
    rating: 4.6,
    downloads: 6700,
    sizeKb: 92,
    tags: ['speedrun', 'overlay'],
    dependencies: [],
    writes: ['UI/Splits.lua'],
    gameBuild: '1.2.x',
  },
];

const MARKDOWN_OVERRIDES: Record<string, string> = {
  'aurora-paths': `# Aurora Paths

A **cosmetic** repaint of every forest-zone tile border, sampled from
the *Northern Lights* palette used in the official Ravenswatch
concept art.

## What you get

- Soft aurora gradient on forest borders
- Optional snowfall variant (toggle in \`config.toml\`)
- Camp-entry flicker fixed in 1.2.0

## Compatibility

Works with every other border or HUD mod. Writes only to
\`Maps/Forest/Borders.tex\`.

> Built for runs that lean into the game's quieter, painterly moments.

See the [Aurora palette reference](https://example.com/aurora) for screenshots.`,
  'hyper-aggro': `# Hyper Aggro

Tired of enemies *pausing politely* between commits? This mod zeroes
every patience timer in \`Encounters/AI_Patience.ot\` — the moment they
see you, they're moving.

## Highlights

- **Zero patience.** Enemies never break off the chase.
- **Companions untouched.** Allies behave normally.
- **Boss-safe.** Phase transitions tested clean in 0.4.1.

## Recommended pairings

- \`long-night\` for theatrical endurance runs
- \`wolfheart-buff\` to survive the new pressure`,
  'twin-fang': `# Twin Fang

> *Two axes. One verdict.*

Adds a **second axe** to Beowulf with a full stance toggle and a new
combo tree. Finishers chain into bleeds. Custom animation set.

## Why

The base Beowulf kit doesn't lean hard enough into the *berserker*
fantasy. Twin Fang restores it.

## Install notes

1. Install via RSMM.
2. Bind a stance toggle in **Settings → Controls**.
3. Bleed FX requires the bundled \`Heroes/Beowulf/Stance.lua\`.`,
};

function defaultMarkdown(m: RawMod): string {
  return `# ${m.name}

*by ${m.author} · v${m.latestVersion}*

${m.description}

## Tags

${m.tags.map((t) => `- ${t}`).join('\n')}

## Game build

\`${m.gameBuild}\``;
}

export const MOCK_MODS: MockMod[] = RAW_MODS.map((m) => ({
  ...m,
  image: m.image ?? `https://picsum.photos/seed/${m.slug}/960/540`,
  markdown: m.markdown ?? MARKDOWN_OVERRIDES[m.id] ?? defaultMarkdown(m),
}));
