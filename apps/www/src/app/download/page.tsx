import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
  buttonVariants,
} from '@rsmm/ui';
import { Download } from 'lucide-react';
import type { Metadata } from 'next';
import Link from 'next/link';
import {
  LATEST_RELEASE_URL,
  RELEASES_URL,
  type ReleaseAsset,
  formatBytes,
  getLatestRelease,
  pickAsset,
} from '../../lib/releases';
import { OsDownload } from '../os-download';

export const metadata: Metadata = {
  title: 'Download Ravenswatch Mod Manager — Windows & Linux',
  description:
    'Get the free Ravenswatch Mod Manager for Windows and Linux. Installer, portable build and AppImage, with one-click mod installs and a fully reversible game install.',
  alternates: { canonical: '/download' },
};

export const revalidate = 3600;

const releaseUrl = (tag: string) =>
  `https://github.com/Ovilli/RavenswatchModManager/releases/tag/${tag}`;
const latestUrl = LATEST_RELEASE_URL;
const releasesUrl = RELEASES_URL;
const installGuideUrl =
  'https://github.com/Ovilli/RavenswatchModManager/blob/main/docs/INSTALLATION.md';

interface Platform {
  name: string;
  details: string;
  note: string;
  /** Extensions to offer, in preference order; each becomes its own button. */
  exts: string[];
}

const platforms: Platform[] = [
  {
    name: 'Windows',
    details:
      'Best option for most players. Ships as an NSIS installer for 64-bit Windows 10 and 11.',
    note: 'Auto-updater is enabled — once installed, the app checks for new releases on launch and applies them in one click.',
    exts: ['.msi', '.exe'],
  },
  {
    name: 'Linux',
    details: 'AppImage for portable use, or a Debian package for apt-based distros.',
    note: 'AppImage needs the executable bit set (chmod +x). On Debian/Ubuntu, install the .deb with apt. WebKitGTK 4.1 must be present.',
    exts: ['.AppImage', '.deb'],
  },
];

const steps = [
  'Download the installer for your platform — the buttons above pull it straight from the latest GitHub release.',
  'Install the client, then sign in or create an account from the app.',
  'Browse the registry, install a mod, and launch the game with the manager applied.',
];

/**
 * Every asset for a platform, in preference order, deduplicated.
 *
 * `pickAsset` returns the first match; the cards want all of them, because a
 * Linux visitor should not have to guess whether the AppImage or the .deb is
 * the one on offer.
 */
function assetsFor(all: ReleaseAsset[], exts: string[]): ReleaseAsset[] {
  const seen = new Set<string>();
  const out: ReleaseAsset[] = [];
  for (const ext of exts) {
    const hit = pickAsset(all, [ext]);
    if (hit && !seen.has(hit.url)) {
      seen.add(hit.url);
      out.push(hit);
    }
  }
  return out;
}

export default async function DownloadPage() {
  const release = await getLatestRelease();
  const currentVersion = release.tag ?? 'the latest release';

  return (
    <main className="relative overflow-hidden animate-page-in">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,hsl(var(--crimson)/0.1),transparent_40%),radial-gradient(circle_at_bottom_right,hsl(var(--oxblood)/0.08),transparent_32%)]" />
      <div className="relative container mx-auto px-6 py-16 lg:py-24">
        <section className="mx-auto max-w-4xl text-center">
          <Badge variant="outline" className="mb-5 border-crimson/30 bg-crimson/10 text-parchment">
            Desktop client · {currentVersion}
          </Badge>
          <h1 className="text-5xl font-black tracking-tight sm:text-6xl">
            Download the Ravenswatch Mod Manager client
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground">
            One desktop app for browsing the registry, applying mods, and managing rollback-safe
            installs across Windows and Linux — with built-in auto-updates.
          </p>

          <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
            {/* Detects the OS and starts the installer download directly. It
                used to link to the GitHub release page, which is why the button
                on the DOWNLOAD page did not download anything. */}
            <OsDownload release={release} fallbackHref={latestUrl} />
            <Link className={buttonVariants({ variant: 'outline', size: 'lg' })} href="/registry">
              Browse the registry
            </Link>
            <a
              className={buttonVariants({ variant: 'secondary', size: 'lg' })}
              href={installGuideUrl}
              target="_blank"
              rel="noreferrer"
            >
              Installation guide
            </a>
          </div>
        </section>

        <section className="mt-16 grid gap-6 lg:grid-cols-2">
          {platforms.map((platform) => {
            const assets = assetsFor(release.assets, platform.exts);
            return (
              <Card key={platform.name} className="grimoire-card">
                <CardHeader>
                  <CardTitle>{platform.name}</CardTitle>
                  <CardDescription>{platform.details}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4 text-sm text-muted-foreground">
                  <p>{platform.note}</p>
                  {/* The filenames were a hardcoded glob that had drifted from
                      what the releases actually contain. They are read off the
                      release now, so they cannot go stale again. */}
                  {assets.length > 0 ? (
                    <ul className="space-y-1 rounded-md border border-dashed border-border/70 bg-background/60 px-4 py-3 font-mono text-xs leading-5">
                      {assets.map((a) => (
                        <li key={a.url} className="flex justify-between gap-3">
                          <span className="truncate">{a.name}</span>
                          {a.size > 0 ? (
                            <span className="shrink-0 text-muted-foreground/70">
                              {formatBytes(a.size)}
                            </span>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </CardContent>
                <CardFooter className="flex flex-wrap gap-2">
                  {assets.length > 0 ? (
                    assets.map((a, i) => (
                      <a
                        key={a.url}
                        className={buttonVariants({ variant: i === 0 ? 'default' : 'outline' })}
                        href={a.url}
                        rel="noreferrer"
                      >
                        <Download className="mr-1.5 h-4 w-4" aria-hidden="true" />
                        {a.name.slice(a.name.lastIndexOf('.'))}
                      </a>
                    ))
                  ) : (
                    // No matching asset in the latest release, or the lookup
                    // failed — send them somewhere that definitely works.
                    <a
                      className={buttonVariants({ variant: 'outline' })}
                      href={latestUrl}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open release
                    </a>
                  )}
                </CardFooter>
              </Card>
            );
          })}
        </section>

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
