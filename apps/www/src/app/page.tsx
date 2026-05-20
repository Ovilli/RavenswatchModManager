import { Button, buttonVariants } from '@rsmm/ui';
import Link from 'next/link';
import { FAQ } from './components/faq';

const features = [
  {
    title: 'One-click install',
    body: 'Grab a mod and the manager puts it where Ravenswatch expects it. No manual steps, no guesswork.',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5" aria-hidden="true">
        <path d="M5 12h14" /><path d="m12 5 7 7-7 7" />
      </svg>
    ),
  },
  {
    title: 'Manage with confidence',
    body: 'See everything in My Mods. Toggle on or off, update, or remove whenever you like with full rollback support.',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5" aria-hidden="true">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      </svg>
    ),
  },
  {
    title: 'Built-in browser',
    body: 'Search and discover community mods without leaving the app. It is all in one place.',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5" aria-hidden="true">
        <circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" />
      </svg>
    ),
  },
  {
    title: 'Cross-platform',
    body: 'Works on Windows, macOS, and Linux. Small download, quick start, low overhead.',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5" aria-hidden="true">
        <rect x="2" y="3" width="20" height="14" rx="2" ry="2" /><line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" />
      </svg>
    ),
  },
  {
    title: 'Open source',
    body: 'Trust what you use. Read the code, file issues, or contribute features — your call.',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5" aria-hidden="true">
        <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22" />
      </svg>
    ),
  },
  {
    title: 'Easy updates',
    body: 'Out-of-date mods are clearly marked. Update them in one click to keep everything working.',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5" aria-hidden="true">
        <polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" /><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
      </svg>
    ),
  },
];

const placeholderMods = Array.from({ length: 4 }, (_, i) => ({
  name: `Mod #${i + 1}`,
  author: '???',
  downloads: '?',
  likes: '?',
  category: '???',
}));

export default function Home() {
  return (
    <main className="relative overflow-hidden">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_-20%,hsl(var(--crimson)/0.12),transparent_50%),radial-gradient(circle_at_80%_80%,hsl(var(--oxblood)/0.08),transparent_50%)]" />

      {/* ───── Hero ───── */}
      <section className="relative container mx-auto px-6 pb-8 pt-16 lg:pb-16 lg:pt-24">
        <div className="mx-auto max-w-3xl text-center">
          <h1 className="bg-gradient-to-r from-parchment via-gilt to-parchment bg-clip-text text-5xl font-extrabold tracking-tight text-transparent sm:text-6xl">
            Ravenswatch Mod Manager
          </h1>
          <p className="mt-4 text-lg text-muted-foreground">
            Mods for Ravenswatch, minus the hassle. Find, install, and update mods in a couple of
            clicks. No folders, no guesswork.
          </p>

          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link href="/download" className={buttonVariants({ size: 'lg' })}>
              Download for Linux
            </Link>
            <Link
              href="/download"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              All Downloads{' '}
              <span aria-hidden="true" className="text-gilt">→</span>
            </Link>
          </div>
        </div>

        <div className="mt-12 overflow-hidden rounded-xl border border-border/50 bg-card/50 backdrop-blur-sm">
          <div className="cover-placeholder aspect-video w-full" />
        </div>
      </section>

      {/* ───── Features ───── */}
      <section className="container mx-auto px-6 py-16 lg:py-24">
        <div className="mx-auto max-w-5xl">
          <div className="mb-12 text-center">
            <h2 className="text-3xl font-bold tracking-tight">Features</h2>
            <p className="mt-2 text-muted-foreground">Make Ravenswatch yours</p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {features.map((f) => (
              <div key={f.title} className="grimoire-card flex gap-4 p-5">
                <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-gilt/20 bg-crimson/10 text-gilt">
                  {f.icon}
                </div>
                <div>
                  <h3 className="font-semibold text-foreground">{f.title}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">{f.body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ───── Stats ───── */}
      <section className="container mx-auto px-6 py-16 lg:py-24">
        <div className="mb-12 text-center">
          <h2 className="text-3xl font-bold tracking-tight">Stats</h2>
          <p className="mt-2 text-muted-foreground">
            By the numbers — a growing library of mods and an active community.
          </p>
        </div>
        <div className="grid gap-6 sm:grid-cols-3">
          {[
            { label: 'Available Mods', value: '?' },
            { label: 'Mod Downloads', value: '?' },
            { label: 'App Downloads', value: '?' },
          ].map((stat) => (
            <div key={stat.label} className="grimoire-card p-6 text-center">
              <div className="text-4xl font-bold tracking-tight text-foreground">{stat.value}</div>
              <div className="mt-1 text-sm text-muted-foreground">{stat.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ───── Showcase ───── */}
      <section className="container mx-auto px-6 py-16 lg:py-24">
        <div className="mb-12 text-center">
          <h2 className="text-3xl font-bold tracking-tight">Showcase</h2>
          <p className="mt-2 text-muted-foreground">
            Browse &amp; Install Mods in Seconds — discover popular mods and install with a single
            click.
          </p>
        </div>
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {placeholderMods.map((mod) => (
            <div key={mod.name} className="grimoire-card overflow-hidden">
              <div className="cover-placeholder aspect-[4/3] w-full" />
              <div className="space-y-2 p-4">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <h3 className="text-sm font-semibold leading-tight text-foreground">
                      {mod.name}
                    </h3>
                    <p className="text-xs text-muted-foreground">by {mod.author}</p>
                  </div>
                  <span className="shrink-0 rounded-md border border-border/50 px-1.5 py-0.5 font-mono text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                    {mod.category}
                  </span>
                </div>
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <span>{mod.downloads} downloads</span>
                  <span>{mod.likes} likes</span>
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="mt-8 text-center">
          <Link href="/registry" className={buttonVariants({ size: 'lg' })}>
            Install Mod
          </Link>
          <p className="mt-3 text-sm text-muted-foreground">
            Click once to install · Works automatically · Ready in seconds
          </p>
          <div className="mt-6">
            <Link
              href="/registry"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              Browse All Mods{' '}
              <span aria-hidden="true" className="text-gilt">→</span>
            </Link>
          </div>
        </div>
      </section>

      {/* ───── FAQ ───── */}
      <section className="container mx-auto px-6 py-16 lg:py-24">
        <div className="mx-auto max-w-3xl">
          <div className="mb-10 text-center">
            <h2 className="text-3xl font-bold tracking-tight">FAQ</h2>
            <p className="mt-2 text-muted-foreground">Frequently asked questions</p>
          </div>
          <FAQ />
          <p className="mt-8 text-center text-sm text-muted-foreground">
            Have a different question and cannot find the answer? Check out our{' '}
            <a
              href="https://github.com/Ovilli/RavenswatchModManager"
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2 hover:text-foreground"
            >
              documentation
            </a>{' '}
            or{' '}
            <a
              href="https://github.com/Ovilli/RavenswatchModManager/issues"
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2 hover:text-foreground"
            >
              create an issue
            </a>
            .
          </p>
        </div>
      </section>
    </main>
  );
}
