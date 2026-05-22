import { Badge, buttonVariants } from '@rsmm/ui';
import type { ModListItem } from '@rsmm/schemas';
import Link from 'next/link';
import { FAQ } from './components/faq';
import { OsDownload } from './os-download';
import { QuickSearch } from './quick-search';
import { MockClient } from './mock-client';

interface HomeData {
  mods: ModListItem[];
  totalMods: number;
  totalModDownloads: number;
  appDownloads: number;
}

async function getHomeData(): Promise<HomeData> {
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:3001';
  const fallback: HomeData = { mods: [], totalMods: 0, totalModDownloads: 0, appDownloads: 0 };

  try {
    const [modRes, ghRes] = await Promise.allSettled([
      fetch(`${apiBase}/api/mods?limit=48`, { next: { revalidate: 300 } }),
      fetch('https://api.github.com/repos/Ovilli/RavenswatchModManager/releases/latest', {
        next: { revalidate: 3600 },
      }),
    ]);

    let mods: ModListItem[] = [];
    let totalMods = 0;
    let totalModDownloads = 0;
    let appDownloads = 0;

    if (modRes.status === 'fulfilled' && modRes.value.ok) {
      const body = await modRes.value.json();
      mods = body.items ?? [];
      totalMods = body.total ?? 0;
      totalModDownloads = mods.reduce((s: number, m: ModListItem) => s + (m.downloads ?? 0), 0);
    }

    if (ghRes.status === 'fulfilled' && ghRes.value.ok) {
      const data = await ghRes.value.json();
      if (data.assets) {
        appDownloads = data.assets.reduce(
          (s: number, a: { download_count?: number }) => s + (a.download_count ?? 0),
          0,
        );
      }
    }

    return { mods, totalMods, totalModDownloads, appDownloads };
  } catch {
    return fallback;
  }
}

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

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export default async function Home() {
  const { mods, totalMods, totalModDownloads, appDownloads } = await getHomeData();
  const showcase = [...mods].sort((a, b) => b.downloads - a.downloads).slice(0, 4);

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
            <OsDownload />
            <Link
              href="/download"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              All Downloads{' '}
              <span aria-hidden="true" className="text-gilt">→</span>
            </Link>
          </div>
        </div>

        <MockClient mods={showcase} />
      </section>

      {/* ───── Search ───── */}
      <section className="container mx-auto px-6 pb-8">
        <div className="mx-auto max-w-2xl">
          <QuickSearch />
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
            { label: 'Available Mods', value: totalMods || '?' },
            { label: 'Mod Downloads', value: totalModDownloads || '?' },
            { label: 'App Downloads', value: appDownloads || '?' },
          ].map((stat) => (
            <div key={stat.label} className="grimoire-card p-6 text-center">
              <div className="text-5xl font-black tracking-tight text-foreground">
                {typeof stat.value === 'number' ? fmt(stat.value) : stat.value}
              </div>
              <div className="mt-2 text-sm text-muted-foreground">{stat.label}</div>
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
          {showcase.length > 0
            ? showcase.map((mod) => (
                <Link
                  key={mod.id}
                  href={`/registry/${mod.slug}`}
                  className="grimoire-card overflow-hidden group cursor-pointer hover:border-gilt/40 transition-colors"
                >
                  {mod.imageUrl ? (
                    <div className="aspect-[4/3] w-full overflow-hidden bg-muted">
                      <img
                        src={mod.imageUrl}
                        alt={`${mod.name} preview`}
                        className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
                        loading="lazy"
                      />
                    </div>
                  ) : (
                    <div className="aspect-[4/3] w-full bg-muted" />
                  )}
                  <div className="space-y-2 p-4">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <h3 className="text-sm font-semibold leading-tight text-foreground truncate">
                          {mod.name}
                        </h3>
                        <p className="text-xs text-muted-foreground">by {mod.author ?? 'unknown'}</p>
                      </div>
                      {mod.category ? (
                        <Badge variant="outline" className="shrink-0 text-[0.6rem]">{mod.category}</Badge>
                      ) : null}
                    </div>
                    {mod.summary ? (
                      <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
                        {mod.summary}
                      </p>
                    ) : null}
                    <div className="flex items-center gap-3 text-xs text-muted-foreground">
                      <span>{mod.downloads.toLocaleString()} downloads</span>
                      {mod.rating != null ? <span>★ {mod.rating.toFixed(1)}</span> : null}
                      {mod.latestVersion ? <span className="ml-auto font-mono text-[0.6rem]">v{mod.latestVersion}</span> : null}
                    </div>
                  </div>
                </Link>
              ))
            : Array.from({ length: 4 }, (_, i) => (
                <div key={i} className="grimoire-card overflow-hidden">
                  <div className="aspect-[4/3] w-full bg-muted" />
                  <div className="space-y-2 p-4">
                    <div className="h-4 w-3/4 bg-muted rounded" />
                    <div className="h-3 w-1/2 bg-muted rounded" />
                  </div>
                </div>
              ))}
        </div>

        <div className="mt-8 text-center">
          <Link href="/registry" className={buttonVariants({ size: 'lg' })}>
            Browse All Mods
          </Link>
          <p className="mt-3 text-sm text-muted-foreground">
            Click once to install · Works automatically · Ready in seconds
          </p>
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
