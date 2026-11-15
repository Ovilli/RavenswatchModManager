import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
  buttonVariants,
} from '@rsmm/ui';
import type { Metadata } from 'next';
import { RELEASES_URL, getLatestRelease } from '../../lib/releases';
import { DownloadOptions } from './download-options';

export const metadata: Metadata = {
  title: 'Download Ravenswatch Mod Manager — Windows & Linux',
  description:
    'Get the free Ravenswatch Mod Manager for Windows and Linux. Installer, portable build and AppImage, with one-click mod installs and a fully reversible game install.',
  alternates: { canonical: '/download' },
};

export const revalidate = 3600;

const releaseUrl = (tag: string) =>
  `https://github.com/Ovilli/RavenswatchModManager/releases/tag/${tag}`;
const releasesUrl = RELEASES_URL;

const steps = [
  'Download the file for your system and install it.',
  'Open the app. It finds Ravenswatch in your Steam library, or you can choose the game folder yourself.',
  'Install mods from the Browse tab, press Apply, and start the game.',
];

export default async function DownloadPage() {
  const release = await getLatestRelease();
  const currentVersion = release.tag ?? 'the latest release';

  return (
    <main className="relative overflow-hidden animate-page-in">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,hsl(var(--crimson)/0.1),transparent_40%),radial-gradient(circle_at_bottom_right,hsl(var(--oxblood)/0.08),transparent_32%)]" />
      <div className="relative container mx-auto px-6 py-16 lg:py-24">
        <section className="mx-auto max-w-4xl text-center">
          <h1 className="font-display text-6xl text-parchment sm:text-7xl">Download</h1>
          <p className="mx-auto mt-6 max-w-2xl text-xl leading-relaxed text-parchment/80">
            Ravenswatch Mod Manager is free, for Windows 10 and 11 and for Linux, including Steam
            Deck. Once installed, it keeps itself up to date.
          </p>
          <p className="mt-3 text-base text-parchment/55">
            Latest version: {currentVersion.replace(/^v/, '')}
          </p>
        </section>

        <DownloadOptions release={release} />

        <section className="mt-16 grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
          <Card className="grimoire-card">
            <CardHeader>
              <CardTitle>Quick install flow</CardTitle>
              <CardDescription>Fastest path from download to mod browsing.</CardDescription>
            </CardHeader>
            <CardContent>
              <ol className="space-y-4 text-sm text-muted-foreground">
                {steps.map((step, index) => (
                  <li key={step} className="flex gap-4">
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border/70 bg-background text-xs font-semibold text-foreground">
                      {index + 1}
                    </span>
                    <span className="pt-1">{step}</span>
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>

          <Card className="grimoire-card border-crimson/20">
            <CardHeader>
              <CardTitle>Auto-updates</CardTitle>
              <CardDescription>
                Stay on the latest build without re-downloading by hand.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-muted-foreground">
              <p>
                Once {currentVersion} or newer is installed, RSMM polls for signed releases on
                launch. When one is available, a banner appears with an{' '}
                <strong>Install &amp; restart</strong> button — the app downloads, verifies the
                signature, swaps the binary, and relaunches.
              </p>
              <p>
                You can also trigger a manual check from <strong>Settings → Updates</strong> inside
                the app.
              </p>
            </CardContent>
            <CardFooter className="flex flex-col items-stretch gap-3 sm:flex-row">
              <a
                className={buttonVariants({})}
                href={releaseUrl(currentVersion)}
                target="_blank"
                rel="noreferrer"
              >
                {currentVersion} notes
              </a>
              <a
                className={buttonVariants({ variant: 'outline' })}
                href={releasesUrl}
                target="_blank"
                rel="noreferrer"
              >
                All releases
              </a>
            </CardFooter>
          </Card>
        </section>
      </div>
    </main>
  );
}
