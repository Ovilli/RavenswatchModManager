import {
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
const installGuideUrl = 'https://docs.rsmm.me/getting-started/install/';

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
    details: 'A standard installer for 64-bit Windows 10 and 11.',
    note: 'Once installed, the app checks for a new version each time it starts and updates in one click.',
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
  'Download the file for your system and install it.',
  'Open the app. It finds Ravenswatch in your Steam library, or you can choose the game folder yourself.',
  'Install mods from the Browse tab, press Apply, and start the game.',
];

/** Button text for a release file: what it is, not just its extension. */
function assetLabel(name: string): string {
  if (name.endsWith('.exe')) return 'Windows installer';
  if (name.endsWith('.msi')) return 'Windows installer (MSI)';
  if (name.endsWith('.AppImage')) return 'AppImage';
  if (name.endsWith('.deb')) return 'Debian package';
  return name.slice(name.lastIndexOf('.'));
}

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
          <h1 className="font-fraktur text-6xl text-parchment sm:text-7xl">Download</h1>
          <p className="mx-auto mt-6 max-w-2xl text-xl leading-relaxed text-parchment/80">
            Ravenswatch Mod Manager is free, for Windows 10 and 11 and for Linux, including Steam
            Deck. Once installed, it keeps itself up to date.
          </p>
          <p className="mt-3 text-base text-parchment/55">
            Latest version: {currentVersion.replace(/^v/, '')}
          </p>

          <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
            {/* Detects the OS and starts the installer download directly. It
                used to link to the GitHub release page, which is why the button
                on the DOWNLOAD page did not download anything. */}
            <OsDownload release={release} fallbackHref={latestUrl} showVersion={false} />
            <a
              className={buttonVariants({ variant: 'outline', size: 'lg' })}
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
                    <ul className="space-y-1 rounded-md border border-dashed border-border/70 bg-background/60 px-4 py-3 font-data leading-6">
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
                        {assetLabel(a.name)}
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
