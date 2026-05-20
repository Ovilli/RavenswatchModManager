import { Badge, Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle, buttonVariants } from '@rsmm/ui';
import Link from 'next/link';

const releaseUrl = 'https://github.com/Ovilli/RavenswatchModManager/releases/latest';
const releasesUrl = 'https://github.com/Ovilli/RavenswatchModManager/releases';
const installGuideUrl = 'https://github.com/Ovilli/RavenswatchModManager/blob/main/docs/INSTALLATION.md';

const platforms = [
  {
    name: 'Windows',
    details: 'Best option for most players. Grab the latest desktop installer from the release page.',
    note: 'Signed builds will appear here once code signing is added.',
  },
  {
    name: 'macOS',
    details: 'Universal release for Apple Silicon and Intel Macs.',
    note: 'Gatekeeper prompts are expected on unsigned local builds.',
  },
  {
    name: 'Linux',
    details: 'Native desktop build for common desktop distributions.',
    note: 'If your distro needs extra libraries, the install guide covers the setup.',
  },
];

const steps = [
  'Open the latest GitHub release and download the installer for your platform.',
  'Install the client, then sign in or create an account from the app.',
  'Browse the registry, install a mod, and launch the game with the manager applied.',
];

export default function DownloadPage() {
  return (
    <main className="relative overflow-hidden">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(56,189,248,0.16),_transparent_40%),radial-gradient(circle_at_bottom_right,_rgba(148,163,184,0.16),_transparent_32%)]" />
      <div className="relative container mx-auto px-6 py-16 lg:py-24">
        <section className="mx-auto max-w-4xl text-center">
          <Badge variant="outline" className="mb-5 border-sky-400/30 bg-sky-500/10 text-sky-200">
            Desktop client
          </Badge>
          <h1 className="text-5xl font-black tracking-tight sm:text-6xl">
            Download the Ravenswatch Mod Manager client
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground">
            One desktop app for browsing the registry, applying mods, and managing rollback-safe
            installs across Windows, macOS, and Linux.
          </p>

          <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <a className={buttonVariants({ size: 'lg' })} href={releaseUrl} target="_blank" rel="noreferrer">
              Get the latest release
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
            <Card key={platform.name} className="border-border/60 bg-card/80 backdrop-blur">
              <CardHeader>
                <CardTitle>{platform.name}</CardTitle>
                <CardDescription>{platform.details}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4 text-sm text-muted-foreground">
                <p>{platform.note}</p>
                <div className="rounded-md border border-dashed border-border/70 bg-background/60 px-4 py-3 text-xs leading-5 text-muted-foreground">
                  Download assets are published to the GitHub Releases page for each tagged build.
                </div>
              </CardContent>
              <CardFooter>
                <a className={buttonVariants({ variant: 'outline' })} href={releasesUrl} target="_blank" rel="noreferrer">
                  Open releases
                </a>
              </CardFooter>
            </Card>
          ))}
        </section>

        <section className="mt-16 grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
          <Card className="border-border/60 bg-card/80 backdrop-blur">
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

          <Card className="border-sky-400/20 bg-sky-500/10 backdrop-blur">
            <CardHeader>
              <CardTitle>Need the source instead?</CardTitle>
              <CardDescription>
                The repo includes the desktop client, API, docs, and release workflow.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 text-sm text-muted-foreground">
              <p>
                If you are packaging or auditing a build, the repository and install docs explain
                the release pipeline end to end.
              </p>
            </CardContent>
            <CardFooter className="flex flex-col items-stretch gap-3 sm:flex-row">
              <a className={buttonVariants({})} href={releaseUrl} target="_blank" rel="noreferrer">
                Latest release
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