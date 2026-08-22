import { Card, CardContent, CardHeader, CardTitle } from '@rsmm/ui';
import type { Metadata } from 'next';
import Link from 'next/link';

const ORIGIN = 'https://rsmm.me';

export const metadata: Metadata = {
  title: 'Ravenswatch Modding Guide — Install, Create & Troubleshoot Mods',
  description:
    'A complete, beginner-friendly guide to modding Ravenswatch: how mods work, installing them safely in one click, finding mods, creating your own, multiplayer behaviour, Steam Deck / Linux, and fixing common problems.',
  alternates: { canonical: '/modding' },
  openGraph: {
    type: 'article',
    title: 'Ravenswatch Modding Guide',
    description:
      'How to install, create, and troubleshoot Ravenswatch mods with the Ravenswatch Mod Manager.',
    url: '/modding',
  },
};

// A long-form, original reference page. This is evergreen content that does not
// depend on the size of the community registry — it explains the whole modding
// workflow in one place and links out to the registry, guides, and docs.

interface Section {
  id: string;
  title: string;
}

const TOC: Section[] = [
  { id: 'what-is-modding', title: 'What is Ravenswatch modding?' },
  { id: 'how-it-works', title: 'How the mod manager works' },
  { id: 'install', title: 'Installing a mod' },
  { id: 'finding', title: 'Finding good mods' },
  { id: 'creating', title: 'Creating your own mod' },
  { id: 'safety', title: 'Is modding safe?' },
  { id: 'multiplayer', title: 'Mods and multiplayer' },
  { id: 'linux', title: 'Steam Deck, Proton & Linux' },
  { id: 'troubleshooting', title: 'Troubleshooting' },
  { id: 'next', title: 'Where to go next' },
];

function H({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2 id={id} className="scroll-mt-24 text-2xl font-semibold text-foreground">
      {children}
    </h2>
  );
}

export default function ModdingGuidePage() {
  const articleLd = {
    '@context': 'https://schema.org',
    '@type': 'TechArticle',
    headline: 'Ravenswatch Modding Guide',
    description:
      'How to install, create, and troubleshoot Ravenswatch mods with the Ravenswatch Mod Manager.',
    url: `${ORIGIN}/modding`,
    mainEntityOfPage: `${ORIGIN}/modding`,
    publisher: {
      '@type': 'Organization',
      name: 'Ravenswatch Mod Manager',
      '@id': `${ORIGIN}/#org`,
    },
  };

  return (
    <main className="container mx-auto px-6 py-16 animate-page-in">
      <script
        type="application/ld+json"
        // biome-ignore lint/security/noDangerouslySetInnerHtml: static, server-built JSON-LD.
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleLd) }}
      />

      <div className="mx-auto max-w-3xl">
        <header className="space-y-3">
          <h1 className="text-4xl font-bold tracking-tight">Ravenswatch Modding Guide</h1>
          <p className="text-base text-muted-foreground">
            Everything you need to start modding Ravenswatch — how mods work, how to install them
            safely in a single click, how to make your own, and how to fix the problems people hit
            most often. No file editing, no risk to your save.
          </p>
        </header>

        {/* Table of contents */}
        <Card className="mt-8 grimoire-card">
          <CardHeader>
            <CardTitle className="text-base">On this page</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="grid gap-1.5 text-sm sm:grid-cols-2">
              {TOC.map((s) => (
                <li key={s.id}>
                  <a href={`#${s.id}`} className="text-muted-foreground hover:text-foreground">
                    {s.title}
                  </a>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <article className="mt-12 space-y-12 text-sm leading-relaxed text-muted-foreground">
          <section className="space-y-3">
            <H id="what-is-modding">What is Ravenswatch modding?</H>
            <p>
              <strong className="text-foreground">Ravenswatch</strong> is a roguelite action game by
              Passtech Games. Modding it means changing what the game loads — swapping a hero skin,
              retuning balance numbers, adding a custom magical object, replacing audio, or layering
              in scripted behaviour — without altering the original game files permanently.
            </p>
            <p>
              The <strong className="text-foreground">Ravenswatch Mod Manager</strong> (RSMM) is a
              free, open-source desktop app that handles all of this for you. You browse a registry
              of community mods, click install, and play. There is no manual unzipping, no copying
              files into hidden folders, and no editing of the game executable.
            </p>
          </section>

          <section className="space-y-3">
            <H id="how-it-works">How the mod manager works</H>
            <p>
              Under the hood, Ravenswatch loads its art, audio, and data from cooked asset files
              inside your install folder. RSMM installs a mod by{' '}
              <strong className="text-foreground">backing up the original file</strong> and copying
              the mod&apos;s version into place. Every change is tracked, so removing a mod (or
              clearing all of them) restores the game to exactly how it shipped.
            </p>
            <ul className="list-disc space-y-1 pl-5">
              <li>
                <strong className="text-foreground">Rollback-safe.</strong> Originals are backed up
                before anything is overwritten; uninstalling reverses every change.
              </li>
              <li>
                <strong className="text-foreground">No executable patching.</strong> Texture, model,
                audio, and data mods work purely by replacing assets — your{' '}
                <code>Ravenswatch.exe</code> is never modified.
              </li>
              <li>
                <strong className="text-foreground">Auto-detection.</strong> The app finds your
                Steam install automatically, or you can point it at the folder in Settings.
              </li>
            </ul>
          </section>

          <section className="space-y-3">
            <H id="install">Installing a mod</H>
            <p>The fastest path, start to finish:</p>
            <ol className="list-decimal space-y-1 pl-5">
              <li>
                <Link href="/download" className="underline hover:text-foreground">
                  Download the Mod Manager
                </Link>{' '}
                for Windows or Linux and open it.
              </li>
              <li>Let it auto-detect Ravenswatch, or set the game folder in Settings.</li>
              <li>
                Browse the{' '}
                <Link href="/registry" className="underline hover:text-foreground">
                  registry
                </Link>{' '}
                and click a mod that looks interesting.
              </li>
              <li>Hit Download / Install. The app puts the files exactly where they belong.</li>
              <li>Launch the game and play.</li>
            </ol>
            <p>
              Already browsing a mod page in your browser? The{' '}
              <em className="text-foreground">Open in app</em> button hands the mod straight to RSMM
              if you have it installed.
            </p>
          </section>

          <section className="space-y-3">
            <H id="finding">Finding good mods</H>
            <p>
              The{' '}
              <Link href="/registry" className="underline hover:text-foreground">
                registry
              </Link>{' '}
              lets you search and filter by category — gameplay, balance, cosmetic, quality-of-life,
              audio, difficulty, speedrun, and utility — and sort by popularity, recency, or rating.
              For curated sets, browse{' '}
              <Link href="/c" className="underline hover:text-foreground">
                collections
              </Link>
              , and for walkthroughs and build ideas written by players, read the{' '}
              <Link href="/guides" className="underline hover:text-foreground">
                community guides
              </Link>
              .
            </p>
          </section>

          <section className="space-y-3">
            <H id="creating">Creating your own mod</H>
            <p>
              RSMM ships a software development kit (SDK) so mods are{' '}
              <strong className="text-foreground">declarative data, not code</strong>. You describe
              what you want in a manifest and the tooling produces the cooked assets. Typical builds
              include:
            </p>
            <ul className="list-disc space-y-1 pl-5">
              <li>Re-skinning a hero or weapon with a custom texture or 3D model.</li>
              <li>Adding a custom magical object that shows up in the compendium.</li>
              <li>Re-tuning talent values or run modifiers.</li>
              <li>Replacing sound effects or music.</li>
            </ul>
            <p>
              When you are happy with a mod, you can{' '}
              <Link href="/publish" className="underline hover:text-foreground">
                publish it to the registry
              </Link>{' '}
              so other players can install it in one click. Full authoring docs, the manifest
              format, and the CLI reference live on the{' '}
              <a
                href="https://docs.rsmm.me"
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-foreground"
              >
                documentation site
              </a>
              .
            </p>
            <p>
              Working with an AI assistant? Point it at{' '}
              <a
                href="https://docs.rsmm.me/llms-mods.txt"
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-foreground"
              >
                docs.rsmm.me/llms-mods.txt
              </a>{' '}
              — the whole authoring documentation as one plain-text file. Ravenswatch has no
              official mod format, so an assistant with nothing to read will invent one that the
              game cannot load. The{' '}
              <a
                href="https://docs.rsmm.me/guides/ai-assistant/"
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-foreground"
              >
                AI assistant guide
              </a>{' '}
              covers the prompt and the rules it needs to follow.
            </p>
          </section>

          <section className="space-y-3">
            <H id="safety">Is modding safe?</H>
            <p>
              Mods are third-party files, so use good judgment — but RSMM is built to keep the risk
              low. It only copies assets into your game directory and never patches the executable,
              and every install is fully reversible. If something looks off, you can{' '}
              <strong className="text-foreground">Clear All Mods</strong> to return the game to a
              clean state instantly.
            </p>
            <p>
              Community uploads are covered by our{' '}
              <Link href="/dmca" className="underline hover:text-foreground">
                Content Policy
              </Link>
              , which forbids malware and redistributed copyrighted game assets. If you are unsure
              about a file, scan it before installing.
            </p>
          </section>

          <section className="space-y-3">
            <H id="multiplayer">Mods and multiplayer</H>
            <p>
              Cosmetic and client-side mods are local to you: other players in your session see the
              default game content, and your installed mods are not pushed to them. Mods that change
              shared gameplay data are best used in single-player or when everyone in the lobby
              agrees to run the same setup, since the host is authoritative over the match.
            </p>
          </section>

          <section className="space-y-3">
            <H id="linux">Steam Deck, Proton &amp; Linux</H>
            <p>
              RSMM ships native Linux builds and the asset-replacement workflow works the same under
              Proton, so Steam Deck and desktop Linux players are first-class. Point the app at your
              Proton/Steam install and install mods exactly as you would on Windows.
            </p>
          </section>

          <section className="space-y-3">
            <H id="troubleshooting">Troubleshooting</H>
            <div className="space-y-4">
              <div>
                <h3 className="font-semibold text-foreground">The app can&apos;t find my game</h3>
                <p>
                  Open Settings and set the Ravenswatch install folder manually. On Steam it&apos;s
                  usually under <code>steamapps/common/Ravenswatch</code>.
                </p>
              </div>
              <div>
                <h3 className="font-semibold text-foreground">
                  I installed a mod but don&apos;t see it in-game
                </h3>
                <p>
                  Make sure the mod is actually applied (not just downloaded), then fully restart
                  the game. Some mods only show up in specific menus, heroes, or run types.
                </p>
              </div>
              <div>
                <h3 className="font-semibold text-foreground">A game update broke my mods</h3>
                <p>
                  After a Ravenswatch patch, re-apply your mods. If a mod hasn&apos;t been updated
                  for the new version yet, remove it and check its page for an update.
                </p>
              </div>
              <div>
                <h3 className="font-semibold text-foreground">I want a totally clean game again</h3>
                <p>
                  Use <strong className="text-foreground">Clear All Mods</strong> in Settings. Every
                  backed-up original is restored — verifying the game files on Steam afterwards is a
                  good belt-and-braces step.
                </p>
              </div>
            </div>
          </section>

          <section className="space-y-3">
            <H id="next">Where to go next</H>
            <ul className="list-disc space-y-1 pl-5">
              <li>
                <Link href="/download" className="underline hover:text-foreground">
                  Download the Mod Manager
                </Link>
              </li>
              <li>
                <Link href="/registry" className="underline hover:text-foreground">
                  Browse the mod registry
                </Link>
              </li>
              <li>
                <Link href="/guides" className="underline hover:text-foreground">
                  Read community guides
                </Link>
              </li>
              <li>
                <a
                  href="https://docs.rsmm.me"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline hover:text-foreground"
                >
                  Full documentation &amp; SDK reference
                </a>
              </li>
            </ul>
          </section>
        </article>
      </div>
    </main>
  );
}
