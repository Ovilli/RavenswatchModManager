'use client';

import { useState } from 'react';

const faqs = [
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
    a: 'Windows, macOS, and Linux. Prebuilt binaries are published on the GitHub releases page.',
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
];

export function FAQ() {
  const [open, setOpen] = useState<number | null>(null);

  return (
    <div className="space-y-3">
      {faqs.map((faq, i) => {
        const isOpen = open === i;
        return (
          <div key={faq.q} className="grimoire-card overflow-hidden">
            <button
              type="button"
              onClick={() => setOpen(isOpen ? null : i)}
              className="flex w-full items-center justify-between px-6 py-4 text-left text-sm font-medium text-foreground transition-colors hover:text-parchment/90"
            >
              <span>{faq.q}</span>
              <span
                className={`ml-4 shrink-0 text-gilt/60 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}
              >
                ▼
              </span>
            </button>
            {isOpen && (
              <div className="border-t border-border/40 px-6 pb-4 pt-3 text-sm text-muted-foreground">
                {faq.a}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
