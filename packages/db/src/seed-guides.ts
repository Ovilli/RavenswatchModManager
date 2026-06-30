import { config as loadEnv } from 'dotenv';
import { asc, eq } from 'drizzle-orm';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { getDb } from './client';
import { users } from './schema/auth';
import { guides } from './schema/mods';

const here = fileURLToPath(new URL('.', import.meta.url));
const repoRoot = resolve(here, '..', '..', '..');
loadEnv({ path: resolve(repoRoot, '.env.local') });
loadEnv({ path: resolve(repoRoot, '.env') });
loadEnv({ path: '.env.local' });
loadEnv();

interface SeedGuide {
  slug: string;
  title: string;
  summary: string;
  body: string;
}

// First-party, evergreen guides. Substantial original content so the /guides
// section is never empty for AdSense review and so each one is an indexable
// Article. Idempotent: re-running updates the body in place.
const SEED_GUIDES: SeedGuide[] = [
  {
    slug: 'getting-started-install-your-first-mod',
    title: 'Getting Started: Install Your First Ravenswatch Mod',
    summary:
      'A complete walkthrough for new players — from downloading the manager to launching the game with your first mod installed.',
    body: `# Getting Started: Install Your First Ravenswatch Mod

If you have never modded a game before, this guide is for you. Ravenswatch Mod Manager (RSMM) is built so you never have to open a game folder or edit a file by hand. In about five minutes you will have your first mod running.

## 1. Download the manager

Head to the [download page](/download) and grab the build for your operating system. RSMM ships for **Windows** and **Linux**. The download is small and there is no installer wizard to fight through — on Windows you get an installer, on Linux an AppImage or \`.deb\`.

## 2. Let it find your game

The first time you open RSMM it tries to auto-detect your Ravenswatch installation. If you bought the game on Steam in the default location, it will simply appear. If you installed somewhere custom, open **Settings** and point it at the folder that contains \`Ravenswatch.exe\`.

> Tip: you do **not** need to run the game as administrator, and you do not need to disable any anti-cheat — Ravenswatch is a co-op roguelike with no competitive ranked mode.

## 3. Browse and install

Open the **Registry** (in the app or here on the website) and look through what the community has published. Each mod page tells you who made it, what it changes, and how many people have downloaded it. When you find one you like, click **Download**. RSMM does three things for you:

1. Backs up every original file it is about to replace.
2. Copies the mod's files into the exact place Ravenswatch expects them.
3. Records what it changed so it can undo everything later.

## 4. Launch and play

Start Ravenswatch normally. Your mod is already active — texture swaps, balance tweaks, and new content load the moment the game does. There is nothing else to toggle.

## 5. Removing a mod

Changed your mind? Open **My Mods**, remove the ones you do not want, or hit **Clear All Mods** in Settings. Because every install was backed up, removing a mod restores the original game perfectly. Nothing is left behind.

That's the whole loop: browse, install, play, remove. Once you are comfortable, take a look at our guide on [staying safe with mods](/guides/staying-safe-with-mods) and, when you are ready, [making your own](/guides/make-your-first-mod).`,
  },
  {
    slug: 'staying-safe-with-mods',
    title: 'How Ravenswatch Mod Manager Keeps Your Game Safe',
    summary:
      'What actually happens to your game files when you install a mod, why it is reversible, and how to judge whether a mod is trustworthy.',
    body: `# How Ravenswatch Mod Manager Keeps Your Game Safe

A reasonable worry before installing any mod is: *what is this going to do to my game, and can I undo it?* This guide explains exactly what happens under the hood so you can mod with confidence.

## Install-time file replacement, not runtime hacking

Ravenswatch loads its art, audio, text, and data from "cooked" asset files inside the game folder. RSMM installs a mod by **replacing those asset files** — and before it touches anything, it copies the original to a backup right next to it. It does **not** patch or inject into \`Ravenswatch.exe\`, and it does not run alongside the game as a background process for texture and data mods.

Because of that design, two things are always true:

- **Every change is reversible.** Remove the mod (or the whole manager) and a single restore step puts every original file back, byte for byte.
- **Your saves are untouched.** Mods change game content, not your progress.

## How to judge a mod

Mods are made by other players, so a little judgment goes a long way:

- **Check the author and download count.** Popular mods from active authors have been vetted by more people.
- **Read what it changes.** A good mod page is specific: "repaints the HUD", "rebalances the Wolf hero", "adds a new magical item". Vague descriptions deserve more caution.
- **Scan if you are unsure.** Downloaded files can always be run through a virus scanner. The registry also flags mature/NSFW content so you can opt out.

## What RSMM will never do

- It will never modify files outside your Ravenswatch folder.
- It will never silently update a mod without you choosing to.
- It will never leave your game in a broken state you cannot recover — restore always works.

## If something looks wrong

Run **Doctor** from the app (or \`rsmm doctor\` on the command line). It checks that your install is detected, writable, and unchanged, and reports anything that needs attention. If a mod misbehaves, remove it and restore — you lose nothing.

Modding should be fun and low-stakes. With backups on every install and a one-click restore, it is.`,
  },
  {
    slug: 'make-your-first-mod',
    title: "A Beginner's Guide to Making Your First Ravenswatch Mod",
    summary:
      'You do not need to be a programmer to make a mod. Here is how the data-driven SDK lets you reskin, rebalance, and add content with declarative files.',
    body: `# A Beginner's Guide to Making Your First Ravenswatch Mod

The best mods often start as a small itch: *I wish this texture were warmer*, or *this hero should hit a little harder*. The good news is that making a mod for Ravenswatch does not require writing a program. RSMM's philosophy is **mods ship data, not code** — you describe what you want in simple files and the toolkit does the rest.

## The shape of a mod

Every mod is a folder with a \`manifest.toml\` at its root. That manifest declares what the mod contains:

- \`[[content]]\` entries — new or replacement assets like textures, models, audio, or text.
- \`[[patch]]\` entries — targeted edits to existing game data, such as a stat value.

That's it. There is no build step you have to babysit and no scripting language to learn for the common cases.

## Start by reskinning

The friendliest first project is a **texture swap**. Pick something small — a UI border, an item glow, a single enemy. Export your new image as a PNG, drop it in your mod folder, point a \`[[content]]\` entry at it, and run \`rsmm apply\`. The manager cooks your PNG into the format the game reads and installs it. Launch the game and admire your work.

## Then try a balance tweak

Once a reskin feels easy, try changing a number. Hero talent magnitudes, enemy aggression, drop rates — many of these are plain values you can override with a \`[[patch]]\`. Change one thing at a time and test it. Small, focused mods are easier to debug and more pleasant for other players to use.

## Growing from there

When you are comfortable, the SDK opens up: custom magical items, new enemies, model swaps, even Lua-scripted gameplay through an optional loader. Each capability is declarative — you author data and the SDK emits what the game needs.

## Publishing

When your mod is ready, share it. Publish it to the registry so other players can install it in one click, and consider writing a short guide here explaining what it does and how to use it. Clear, well-documented mods get downloaded the most.

For the full reference — every content kind, the cipher internals, and the Lua API — see the [documentation site](https://docs.rsmm.me). But you do not need any of that to make something fun today. Start small, test often, and have fun.`,
  },
  {
    slug: 'troubleshooting-mods-not-showing-up',
    title: 'Troubleshooting: My Mods Are Not Showing Up In Game',
    summary:
      'A short checklist for the most common reasons a freshly installed mod does not appear, and how to fix each one.',
    body: `# Troubleshooting: My Mods Are Not Showing Up In Game

You installed a mod, launched Ravenswatch, and… nothing changed. Don't worry — this is almost always one of a handful of simple issues. Work down this list.

## 1. Was the game running during install?

Ravenswatch reads its asset files at launch. If the game was already open when you installed the mod, it loaded the originals. **Fully quit the game and start it again.** This fixes the majority of "my mod isn't showing" reports.

## 2. Is the right game folder selected?

If RSMM is pointed at the wrong installation (for example, a second copy on another drive), it will happily install into a folder the game you are launching never reads. Open **Settings** and confirm the path contains the \`Ravenswatch.exe\` you actually play.

## 3. Did the install actually finish?

Open **My Mods**. The mod should be listed as installed. If it isn't, the download may have failed — try installing it again. If the install errored, run **Doctor**; a common cause is a **read-only or locked game folder**, which Doctor will call out directly.

## 4. Is the mod for your version of the game?

Game updates occasionally change asset layouts. A mod built for an older version may no longer line up. The registry marks out-of-date mods — look for an update, or check the mod page for a compatibility note.

## 5. Conflicts with another mod

Two mods that replace the *same* file will collide — only one wins. Open the **Conflicts** view to see overlaps, and disable one of the conflicting mods.

## Still stuck?

Remove the mod and **restore** (this is always safe), then reinstall it on a clean install. If it still won't appear, the mod page's comments or the project's GitHub issues are the best place to ask — include your OS, the mod name and version, and what you have already tried.

Nine times out of ten, it's reason #1. Quit fully, relaunch, and your mod should be there.`,
  },
];

async function main() {
  const db = getDb();

  // Owner: the first configured admin, else the oldest user in the DB.
  const adminIds = (process.env.ADMIN_USER_IDS || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  let ownerId = adminIds[0];
  if (!ownerId) {
    const first = await db.select({ id: users.id }).from(users).orderBy(asc(users.createdAt)).limit(1);
    ownerId = first[0]?.id;
  }
  if (!ownerId) {
    console.error('No user found to own the seeded guides. Sign up an account first (or set ADMIN_USER_IDS).');
    process.exit(1);
  }

  console.log(`seeding ${SEED_GUIDES.length} first-party guides (owner ${ownerId})…`);
  for (const g of SEED_GUIDES) {
    await db
      .insert(guides)
      .values({
        slug: g.slug,
        ownerId,
        title: g.title,
        summary: g.summary,
        body: g.body,
        status: 'approved',
      })
      .onConflictDoUpdate({
        target: guides.slug,
        set: { title: g.title, summary: g.summary, body: g.body, status: 'approved', updatedAt: new Date() },
      });
  }
  console.log('guide seed complete');
  process.exit(0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
