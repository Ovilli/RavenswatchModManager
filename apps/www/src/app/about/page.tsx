import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@rsmm/ui';
import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'About · Ravenswatch Mod Manager',
  description:
    'What the Ravenswatch Mod Manager is, how it works, who builds it, and how it keeps your game install safe.',
  alternates: { canonical: '/about' },
};

export default function AboutPage() {
  return (
    <main className="container mx-auto px-6 py-16 animate-page-in">
      <Card className="mx-auto max-w-3xl grimoire-card">
        <CardHeader>
          <CardTitle>About Ravenswatch Mod Manager</CardTitle>
          <CardDescription>
            A free, open-source way to find, install, and manage mods for Ravenswatch.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6 text-sm leading-relaxed text-muted-foreground">
          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">What it is</h2>
            <p>
              Ravenswatch Mod Manager (RSMM) is a community project that makes modding{' '}
              <em>Ravenswatch</em> approachable for everyone — not just people comfortable editing
              game files by hand. It is two things working together: a website where the community
              publishes and discovers mods, and a desktop application that installs those mods into
              your game with a single click and cleanly removes them whenever you want.
            </p>
            <p>
              The whole project is open source. Anyone can read the code, report issues, suggest
              features, or contribute improvements on the project&apos;s GitHub repository.
            </p>
          </section>

          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">How it works</h2>
            <p>
              Ravenswatch loads its art, audio, text, and data from cooked asset files inside the
              game folder. RSMM installs a mod by backing up the original files it is about to touch
              and copying the mod&apos;s versions into place. Because every original is preserved,
              removing a mod — or removing the manager entirely — restores the game to exactly how it
              shipped. There are no permanent changes and nothing is overwritten without a backup.
            </p>
            <p>
              Mods can swap textures and 3D models, rebalance stats, translate text, add new magical
              items, and — with an optional script loader — run Lua-scripted gameplay logic. The
              manager tracks what is installed, flags out-of-date mods, and lets you toggle each one
              on or off.
            </p>
          </section>

          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">Staying safe</h2>
            <p>
              Your saves and your base game stay intact. Every file the manager replaces is backed
              up first, and a single &quot;restore&quot; action puts everything back. Uploaded mods
              are scanned, and the registry shows the author, version history, and download counts so
              you can decide what to trust. RSMM never touches files outside the game&apos;s own
              folder.
            </p>
          </section>

          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">Who builds it</h2>
            <p>
              RSMM is built and maintained by volunteers from the Ravenswatch community. It is not
              affiliated with or endorsed by Passtech Games or Nacon, the developers and publisher of
              Ravenswatch. <em>Ravenswatch</em> and all related trademarks belong to their respective
              owners; this project is an independent, fan-made tool.
            </p>
          </section>

          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">Support the project</h2>
            <p>
              RSMM is free and open source, and always will be. If it saved you an evening of
              fiddling with file paths, you can chip in on{' '}
              <a
                href="https://ko-fi.com/W7W41FW3YE"
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-foreground"
              >
                Ko-fi
              </a>
              . It funds nothing but coffee and the hours of reverse-engineering behind each release
              &mdash; there is no paid tier, and nothing is held back for donors.
            </p>
          </section>

          <section className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground">Get started</h2>
            <p>
              Browse the <Link href="/registry" className="underline hover:text-foreground">mod registry</Link>,{' '}
              <Link href="/download" className="underline hover:text-foreground">download the desktop app</Link>, or
              read the{' '}
              <a
                href="https://docs.rsmm.me"
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-foreground"
              >
                documentation
              </a>{' '}
              to learn how to make your own mods. Questions? See the{' '}
              <Link href="/contact" className="underline hover:text-foreground">contact page</Link>.
            </p>
          </section>
        </CardContent>
      </Card>
    </main>
  );
}
