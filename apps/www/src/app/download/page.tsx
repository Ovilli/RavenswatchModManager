import { Badge, Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle, buttonVariants } from '@rsmm/ui';
import Link from 'next/link';

export const revalidate = 3600;

const releaseUrl = (tag: string) => `https://github.com/Ovilli/RavenswatchModManager/releases/tag/${tag}`;
const latestUrl = 'https://github.com/Ovilli/RavenswatchModManager/releases/latest';
const releasesUrl = 'https://github.com/Ovilli/RavenswatchModManager/releases';
const installGuideUrl = 'https://github.com/Ovilli/RavenswatchModManager/blob/main/docs/INSTALLATION.md';

interface Platform {
  name: string;
  details: string;
  assetHint: string;
  note: string;
}

const platforms: Platform[] = [
  {
    name: 'Windows',
    details: 'Best option for most players. Ships as an MSI installer for 64-bit Windows 10 and 11.',
    assetHint: 'Ravenswatch.Mod.Manager_*_x64_en-US.msi',
    note: 'Auto-updater is enabled — once installed, the app checks for new releases on launch and applies them in one click.',
  },
  {
    name: 'macOS',
    details: 'Universal DMG for Apple Silicon and Intel Macs. Requires macOS 12 or newer.',
    assetHint: 'Ravenswatch.Mod.Manager_*_universal.dmg',
    note: 'Gatekeeper may show a warning on first launch — open via right-click → Open. Auto-updates work the same as on Windows.',
  },
  {
    name: 'Linux',
    details: 'AppImage for portable use, or a Debian package for apt-based distros.',
    assetHint: 'rsmm-desktop_*.AppImage  ·  rsmm-desktop_*_amd64.deb',
    note: 'AppImage needs the executable bit set (chmod +x). On Debian/Ubuntu, install the .deb with apt. WebKitGTK 4.1 must be present.',
  },
];

const steps = [
  'Open the latest GitHub release and download the installer for your platform.',
  'Install the client, then sign in or create an account from the app.',
  'Browse the registry, install a mod, and launch the game with the manager applied.',
];

async function getLatestVersion(): Promise<string> {
  try {
    const res = await fetch(
      'https://api.github.com/repos/Ovilli/RavenswatchModManager/releases/latest',
    );
    if (!res.ok) return 'v0.1.0-beta.2';
    const data = await res.json();
    return data.tag_name ?? 'v0.1.0-beta.2';
  } catch {
    return 'v0.1.0-beta.2';
  }
}

export default async function DownloadPage() {
  const currentVersion = await getLatestVersion();

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
            installs across Windows, macOS, and Linux — with built-in auto-updates.
          </p>

          <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <a className={buttonVariants({ size: 'lg' })} href={latestUrl} target="_blank" rel="noreferrer">
              Get {currentVersion}
            </a>
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

        <section className="mt-16 grid gap-6 lg:grid-cols-3">
          {platforms.map((platform) => (
            <Card key={platform.name} className="grimoire-card">
              <CardHeader>
                <CardTitle>{platform.name}</CardTitle>
                <CardDescription>{platform.details}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4 text-sm text-muted-foreground">
                <p>{platform.note}</p>
                <div className="rounded-md border border-dashed border-border/70 bg-background/60 px-4 py-3 font-mono text-xs leading-5 text-muted-foreground">
                  {platform.assetHint}
                </div>
              </CardContent>
              <CardFooter>
                <a className={buttonVariants({ variant: 'outline' })} href={latestUrl} target="_blank" rel="noreferrer">
                  Open release
                </a>
              </CardFooter>
            </Card>
          ))}
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
              <CardDescription>Stay on the latest build without re-downloading by hand.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-muted-foreground">
              <p>
                Once {currentVersion} or newer is installed, RSMM polls for signed releases on
                launch. When one is available, a banner appears with an <strong>Install &amp; restart</strong>
                {' '}button — the app downloads, verifies the signature, swaps the binary, and relaunches.
              </p>
              <p>
                You can also trigger a manual check from <strong>Settings → Updates</strong> inside the app.
              </p>
            </CardContent>
            <CardFooter className="flex flex-col items-stretch gap-3 sm:flex-row">
              <a className={buttonVariants({})} href={releaseUrl(currentVersion)} target="_blank" rel="noreferrer">
                {currentVersion} notes
              </a>
              <a className={buttonVariants({ variant: 'outline' })} href={releasesUrl} target="_blank" rel="noreferrer">
                All releases
              </a>
            </CardFooter>
          </Card>
        </section>
      </div>
    </main>
  );
}
