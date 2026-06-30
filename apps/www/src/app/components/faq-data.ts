// Shared FAQ content — consumed by the <FAQ> accordion and by the homepage
// FAQPage JSON-LD (so Google can surface it as a rich result + read it as
// real on-page content).
export const faqs = [
  {
    q: 'What is Ravenswatch Mod Manager?',
    a: 'A small desktop app that makes Ravenswatch modding simple. Browse, install, and manage mods without touching your game folders.',
  },
  {
    q: 'How do I install mods?',
    a: 'Download and open Ravenswatch Mod Manager. We will auto-detect Ravenswatch (or you can set the folder in Settings). Browse mods and click Download. The app installs the mod in the right place — no manual steps.',
  },
  {
    q: 'Is it safe to use mods?',
    a: 'Mods are third-party files. The app copies cooked assets to your game directory and does not patch your executable. Use good judgment and scan files if you are unsure.',
  },
  {
    q: 'How do I uninstall mods?',
    a: 'Open My Mods and remove what you do not want, or use Clear All Mods in Settings. Every install is fully rollback-safe.',
  },
  {
    q: 'Which platforms are supported?',
    a: 'Windows and Linux. Prebuilt binaries are published on the GitHub releases page.',
  },
  {
    q: 'I found a bug — how do I report it?',
    a: 'Report bugs by creating an issue on our GitHub repository. Include steps to reproduce, what you expected, and what happened.',
  },
  {
    q: 'Where can I find more detailed documentation?',
    a: 'Check out the documentation site for detailed guides, tutorials, and technical reference materials.',
  },
  {
    q: 'Can other players see my installed mods?',
    a: 'No, mods are client-side. Other players see default game content.',
  },
  {
    q: 'Does modding edit my game files permanently?',
    a: 'No. The app backs up the original file before replacing it, and tracks every change. Removing a mod — or using Clear All Mods — restores the game to exactly how it shipped. It never patches Ravenswatch.exe.',
  },
  {
    q: 'Will mods break when Ravenswatch updates?',
    a: 'A game patch can change the underlying files, so after an update you should re-apply your mods. If a particular mod has not been updated for the new game version yet, remove it and check its mod page for a newer release.',
  },
  {
    q: 'Do mods work on Steam Deck and Linux?',
    a: 'Yes. We ship native Linux builds and the asset-replacement approach works the same under Proton, so Steam Deck and desktop Linux are fully supported. Point the app at your install folder and install mods as you would on Windows.',
  },
  {
    q: 'Can I use mods in multiplayer?',
    a: 'Cosmetic and client-side mods only affect your own game and are safe in co-op. Mods that change shared gameplay data are best used in single-player or when everyone in the lobby runs the same setup, since the host is authoritative over the match.',
  },
  {
    q: 'How do I make my own mod?',
    a: 'The app ships an SDK so mods are declarative data, not code: you describe a re-skin, a custom item, a balance tweak, or an audio swap in a manifest and the tooling produces the assets. See the Modding Guide and the documentation site for the full workflow.',
  },
  {
    q: 'How do I share a mod I made?',
    a: 'Sign in, open Publish, upload your packed mod archive, and fill in the details. It then appears in the registry for other players to install in one click. You can ship new versions and edit metadata later from My Mods.',
  },
  {
    q: 'Does the Mod Manager cost anything?',
    a: 'No. Ravenswatch Mod Manager is free and open source. Browsing, installing, and publishing mods are all free.',
  },
  {
    q: 'Do I need the launcher running while I play?',
    a: 'No. The app installs mod files into your game directory, then you launch and play normally. It does not need to stay open during your session.',
  },
  {
    q: 'Where does the app install mod files?',
    a: 'Into your Ravenswatch install folder (the cooked-asset location the game loads from). The app resolves the correct paths for you and keeps a backup of every original it replaces.',
  },
  {
    q: 'A mod is broken or contains content it should not — what do I do?',
    a: 'Report it through the project issue tracker or the contact page. Uploads are covered by our Content Policy, which forbids malware and redistributed copyrighted game assets; infringing or harmful content is removed.',
  },
] as const;
