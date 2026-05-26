import { config as loadEnv } from 'dotenv';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { getDb } from './client';
import { mods, modVersions } from './schema/mods';

const here = fileURLToPath(new URL('.', import.meta.url));
const repoRoot = resolve(here, '..', '..', '..');
loadEnv({ path: resolve(repoRoot, '.env.local') });
loadEnv({ path: resolve(repoRoot, '.env') });
loadEnv({ path: '.env.local' });
loadEnv();

type Category =
  | 'gameplay'
  | 'balance'
  | 'cosmetic'
  | 'qol'
  | 'audio'
  | 'difficulty'
  | 'speedrun'
  | 'utility';

interface SeedMod {
  slug: string;
  name: string;
  author: string;
  summary: string;
  description: string;
  category: Category;
  rating: number;
  tags: string[];
  version: string;
  license?: string;
  nsfw?: boolean;
}

const SEED_MODS: SeedMod[] = [
  { slug: 'aurora-paths', name: 'Aurora Paths', author: 'mira_of_thorns', summary: 'Repaints forest map borders with aurora gradients.', description: 'Replaces the muted forest-zone tile borders with a soft aurora gradient, sampled from the Northern Lights palette used in the Ravenswatch concept art. No gameplay change.', category: 'cosmetic', rating: 4.6, tags: ['visual', 'biome', 'lights'], version: '1.2.0' },
  { slug: 'hyper-aggro', name: 'Hyper Aggro', author: 'thornveil', summary: 'Enemies always sprint towards the hero. No hiding.', description: 'Reduces all enemy patience timers to zero. They will always commit to the chase. Companions are unaffected.', category: 'difficulty', rating: 4.1, tags: ['ai', 'hard'], version: '0.4.1' },
  { slug: 'twin-fang', name: 'Twin Fang', author: 'forge_o_clock', summary: 'Beowulf dual-wields. New stance, new combo tree.', description: 'Adds a second axe to Beowulf and a stance toggle. Combo finishers chain into bleeds. Custom animation set.', category: 'gameplay', rating: 4.8, tags: ['hero', 'combat', 'beowulf'], version: '2.0.0' },
  { slug: 'gilt-runes', name: 'Gilt Runes', author: 'inksmith', summary: 'Gilded outlines for magical objects. Pickups glow warmer.', description: 'Replaces the cool-blue magical-object outlines with a candlelight gilt. Adjusts pickup glows to match. Pure cosmetic.', category: 'cosmetic', rating: 4.4, tags: ['visual', 'items'], version: '1.6.0' },
  { slug: 'silent-camp', name: 'Silent Camp', author: 'reed_hush', summary: 'Mutes ambient camp chatter for focused runs.', description: 'Silences NPC ambient lines at camp. Music + combat audio unchanged. Useful for streamers running long sessions.', category: 'audio', rating: 4.2, tags: ['audio', 'streamer'], version: '0.9.0' },
  { slug: 'pinned-seed', name: 'Pinned Seed', author: 'rsmm-examples', summary: 'Force a deterministic RNG seed for the entire run.', description: 'Speedrun helper. Sets the run seed from a hex string. All drops, room layouts, and encounters become deterministic.', category: 'speedrun', rating: 4.7, tags: ['speedrun', 'rng'], version: '0.3.0' },
  { slug: 'lantern-hud', name: 'Lantern HUD', author: 'mira_of_thorns', summary: 'Rewrites the HUD in warm gilt tones. Larger health bar.', description: 'Repaints the top-left HUD: health bar gilt, mana bar amber, combo counter set in italics. Larger numeric readouts.', category: 'qol', rating: 4.5, tags: ['hud', 'visual'], version: '1.1.0' },
  { slug: 'wolfheart-buff', name: 'Wolfheart Buff', author: 'pack_runner', summary: 'Buffs the Wolf hero kit. +12% damage at low HP.', description: 'Balance pass for the Wolf hero. Adds a low-HP damage tier. Designed for solo Chaos runs.', category: 'balance', rating: 3.9, tags: ['balance', 'wolf'], version: '0.7.2' },
  { slug: 'succubus-temptation', name: 'Succubus Temptation', author: 'nightfall', summary: 'Succubus enemy variant with suggestive defeat animations.', description: 'Adds a new Succubus enemy type with custom animations. Contains mature thematic content. NSFW.', category: 'gameplay', rating: 3.5, tags: ['enemy', 'nsfw', 'animation'], version: '1.0.0' },
  { slug: 'bathhouse-scenes', name: 'Bathhouse Scenes', author: 'nightfall', summary: 'Replaces campfire scenes with bathhouse variants.', description: 'Campfire conversation scenes replaced with bathhouse-themed variants. Mature content.', category: 'cosmetic', rating: 2.8, tags: ['visual', 'nsfw', 'camp'], version: '0.5.0' },
  { slug: 'wolf-iron-fang', name: 'Iron Fang Wolf', author: 'siege_smith', summary: 'Reworks Wolf to a tank. +HP, -speed.', description: 'Alternative Wolf rework. Heavy armour mod — adds 25% HP, removes dash invul frames.', category: 'balance', rating: 3.2, tags: ['balance', 'wolf', 'tank'], version: '0.2.0' },
  { slug: 'merchant-shuffle', name: 'Merchant Shuffle', author: 'coinpurse', summary: 'Reshuffles merchant inventory mid-run on each visit.', description: 'Merchant inventory rerolls between visits. Higher variance, encourages risk runs.', category: 'gameplay', rating: 4.3, tags: ['economy'], version: '1.0.4' },
  { slug: 'long-night', name: 'Long Night', author: 'reed_hush', summary: 'Doubles night-phase length. Bosses spawn earlier.', description: 'Stretches every nightfall. Useful for theatrical runs and for testing late-game balance.', category: 'difficulty', rating: 3.8, tags: ['pacing', 'hard'], version: '0.6.0' },
  { slug: 'mods-tab', name: 'Mods Tab', author: 'rsmm', summary: 'Adds an in-game Mods page to the Social book.', description: 'Adds a Social-book tab listing every active mod. Useful for verifying a co-op loadout matches.', category: 'utility', rating: 4.9, tags: ['utility', 'in-game'], version: '1.0.0' },
  { slug: 'crow-dash', name: 'Crow Dash Tweaks', author: 'forge_o_clock', summary: 'Smooths Crow dash recovery. -2 frames.', description: 'Trims two frames off Crow’s dash recovery. Tested against speedrun routes.', category: 'balance', rating: 4.0, tags: ['balance', 'crow', 'speedrun'], version: '0.4.0' },
  { slug: 'parchment-codex', name: 'Parchment Codex', author: 'inksmith', summary: 'Rebinds the codex UI to a parchment book layout.', description: 'Rewrites the codex screen as a two-page parchment spread with hand-set type.', category: 'qol', rating: 4.8, tags: ['ui', 'visual'], version: '2.1.0' },
  { slug: 'rune-rain', name: 'Rune Rain', author: 'thornveil', summary: 'Falling rune particles during night phases.', description: 'Adds a slow falling rune particle effect during night. Pure cosmetic, no FPS hit on tested rigs.', category: 'cosmetic', rating: 3.7, tags: ['particles', 'visual'], version: '0.3.0' },
  { slug: 'co-op-hud', name: 'Co-op HUD', author: 'pack_runner', summary: 'Adds party member health bars in co-op.', description: 'Pinned ally bars top-right in co-op. Hidden in solo.', category: 'qol', rating: 4.4, tags: ['co-op', 'hud'], version: '1.0.0' },
  { slug: 'iron-economy', name: 'Iron Economy', author: 'coinpurse', summary: 'Halves all gold drops. Tighter run economy.', description: 'Halves gold drops from kills and chests. Camp upgrades unaffected. For people who think the economy is too loose.', category: 'balance', rating: 3.5, tags: ['economy', 'hard'], version: '0.5.0' },
  { slug: 'cinder-borders', name: 'Cinder Borders', author: 'mira_of_thorns', summary: 'Replaces UI window borders with charred wood frames.', description: 'Repaints UI window borders with photographed charred-wood textures. Subtle.', category: 'cosmetic', rating: 4.1, tags: ['ui', 'visual'], version: '0.8.0' },
  { slug: 'witchfire-fx', name: 'Witchfire FX', author: 'thornveil', summary: 'Recolors fire spells to violet witchfire.', description: 'Reskins all fire VFX with a violet palette. Damage values unchanged.', category: 'cosmetic', rating: 4.0, tags: ['vfx', 'visual'], version: '1.0.0' },
  { slug: 'speed-runner', name: 'Speedrunner Splits', author: 'forge_o_clock', summary: 'In-run split overlay with PB compare.', description: 'Floating splits overlay. Records boss kill times and end-of-act times. Compares against your PB.', category: 'speedrun', rating: 4.6, tags: ['speedrun', 'overlay'], version: '1.2.1' },
];

const PLACEHOLDER_SHA = 'a'.repeat(64);

async function main() {
  const db = getDb();
  console.log(`seeding ${SEED_MODS.length} mods…`);

  for (const m of SEED_MODS) {
    const [row] = await db
      .insert(mods)
      .values({
        slug: m.slug,
        name: m.name,
        summary: m.summary,
        description: m.description,
        license: m.license ?? 'MIT',
        tags: m.tags,
        category: m.category,
        authorName: m.author,
        imageUrl: `https://picsum.photos/seed/${m.slug}/960/540`,
        rating: m.rating.toString(),
        nsfw: m.nsfw ?? false,
      })
      .onConflictDoUpdate({
        target: mods.slug,
        set: {
          name: m.name,
          summary: m.summary,
          description: m.description,
          tags: m.tags,
          category: m.category,
          authorName: m.author,
          imageUrl: `https://picsum.photos/seed/${m.slug}/960/540`,
          rating: m.rating.toString(),
          nsfw: m.nsfw ?? false,
          updatedAt: new Date(),
        },
      })
      .returning();

    if (!row) continue;
    await db
      .insert(modVersions)
      .values({
        modId: row.id,
        version: m.version,
        sha256: PLACEHOLDER_SHA,
        sizeBytes: 1024,
        assetUrl: `https://example.invalid/${m.slug}-${m.version}.zip`,
        manifestJson: {
          id: m.slug,
          name: m.name,
          version: m.version,
          author: m.author,
          summary: m.summary,
          description: m.description,
          tags: m.tags,
        },
      })
      .onConflictDoNothing();
  }

  console.log('seed complete');
  process.exit(0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
