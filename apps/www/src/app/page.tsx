import { type ModListItem, jsonLd } from '@rsmm/schemas';
import { buttonVariants } from '@rsmm/ui';
import { Search } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { getApiUrl } from '../lib/api-url';
import { type LatestRelease, getLatestRelease } from '../lib/releases';
import { FAQ } from './components/faq';
import { faqs } from './components/faq-data';
import { ModCard } from './components/mod-card';
import { OsDownload } from './os-download';

export const revalidate = 300;

interface HomeData {
  mods: ModListItem[];
  featured: ModListItem[];
  totalMods: number;
  totalModDownloads: number;
  appDownloads: number;
  release: LatestRelease;
}

// Installer bundles only. `latest.json` and `*.sig` are fetched by the updater on
// every launch, so counting them reports polling traffic, not downloads.
const INSTALLER_EXT = ['.exe', '.msi', '.deb', '.rpm', '.AppImage', '.dmg'];

function isInstaller(name: string): boolean {
  return INSTALLER_EXT.some((ext) => name.endsWith(ext));
}

interface GhRelease {
  draft?: boolean;
  assets?: { name: string; download_count?: number }[];
}

// Sums installer downloads across every published release — `releases/latest`
// alone reports one version and undercounts the real total by an order of
// magnitude.
async function getAppDownloads(): Promise<number> {
  let total = 0;

  for (let page = 1; page <= 5; page++) {
    const res = await fetch(
      `https://api.github.com/repos/Ovilli/RavenswatchModManager/releases?per_page=100&page=${page}`,
    );
    if (!res.ok) break;

    const releases: GhRelease[] = await res.json();
    if (!Array.isArray(releases) || releases.length === 0) break;

    for (const rel of releases) {
      if (rel.draft) continue;
      for (const asset of rel.assets ?? []) {
        if (isInstaller(asset.name)) total += asset.download_count ?? 0;
      }
    }

    if (releases.length < 100) break;
  }

  return total;
}

async function getHomeData(): Promise<HomeData> {
  const apiBase = getApiUrl().replace(/\/+$/, '');
  const noRelease: LatestRelease = { tag: null, windows: null, linux: null, assets: [] };
  const fallback: HomeData = {
    mods: [],
    featured: [],
    totalMods: 0,
    totalModDownloads: 0,
    appDownloads: 0,
    release: noRelease,
  };

  try {
    const [modRes, featRes, ghRes, relRes] = await Promise.allSettled([
      fetch(`${apiBase}/api/mods?limit=48`),
      fetch(`${apiBase}/api/mods?featured=true&sort=featured&limit=8`),
      getAppDownloads(),
      getLatestRelease(),
    ]);

    let mods: ModListItem[] = [];
    let featured: ModListItem[] = [];
    let totalMods = 0;
    let totalModDownloads = 0;
    let appDownloads = 0;
    let release = noRelease;

    if (modRes.status === 'fulfilled' && modRes.value.ok) {
      const body = await modRes.value.json();
      mods = body.items ?? [];
      totalMods = body.total ?? 0;
      // Prefer the server-side aggregate over all mods; fall back to summing
      // the current page only if an older API build omits it.
      totalModDownloads =
        body.totalDownloads ??
        mods.reduce((s: number, m: ModListItem) => s + (m.downloads ?? 0), 0);
    }

    if (featRes.status === 'fulfilled' && featRes.value.ok) {
      const body = await featRes.value.json();
      featured = body.items ?? [];
    }

    if (ghRes.status === 'fulfilled') {
      appDownloads = ghRes.value;
    }

    if (relRes.status === 'fulfilled') {
      release = relRes.value;
    }

    return { mods, featured, totalMods, totalModDownloads, appDownloads, release };
  } catch {
    return fallback;
  }
}

const steps = [
  {
    title: 'Pick your mods',
    body: 'Install mods from the registry inside the app, or drop a mod folder into your library.',
  },
  {
    title: 'Apply',
    body: 'One button writes the enabled mods into the game. Every file it replaces is backed up first.',
  },
  {
    title: 'Play',
    body: 'Launch Ravenswatch as usual. Restore puts the unmodded game back whenever you want it.',
  },
];

const screens = [
  {
    src: '/screens/list.jpg',
    alt: 'The library in list view, with each mod switched on or off and numbered in load order',
    title: 'Your library, in order',
    body: 'Every mod in the active profile with its switch, version and load position. Mods with a heads-up display can open it as an overlay while you play.',
  },
  {
    src: '/screens/config.jpg',
    alt: 'The settings dialog of the Damage Meter mod',
    title: 'Settings without editing files',
    body: 'Mods declare their own options. Change a number or flip a switch, save, and apply.',
  },
  {
    src: '/screens/profiles.jpg',
    alt: 'The profiles screen with three saved setups',
    title: 'A setup for every run',
    body: 'Keep separate profiles for solo runs and co-op nights, and share one with a friend as a short code.',
  },
];

// The registry's own category filters, so each one lands on a real result list.
const categories = [
  'gameplay',
  'balance',
  'cosmetic',
  'qol',
  'audio',
  'difficulty',
  'speedrun',
  'utility',
];

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${Math.round(n / 1_000)}K`;
  return n.toLocaleString('en-US');
}

export default async function Home() {
  const { mods, featured, totalMods, totalModDownloads, appDownloads, release } =
    await getHomeData();
  const byDownloads = [...mods].sort((a, b) => (b.downloads ?? 0) - (a.downloads ?? 0));
  const popular = [
    ...featured,
    ...byDownloads.filter((m) => !featured.some((f) => f.id === m.id)),
  ].slice(0, 8);

  return (
    <main className="home">
      {/* Intro, in two zones that share a top and a bottom edge: get the app
          (left) and find a mod (right). The product's own name is in the
          sentence under the headline so "ravenswatch mod manager" and "rsmm"
          have an on-page match. */}
      <section className="container mx-auto px-6 pb-14 pt-12 lg:pb-20 lg:pt-16">
        <div className="grid gap-8 lg:grid-cols-12 lg:gap-10">
          <div className="lg:col-span-7">
            <h1 className="font-display text-5xl text-parchment sm:text-6xl">
              Mods for Ravenswatch
            </h1>
            <p className="mt-5 max-w-xl text-xl leading-relaxed text-parchment/80">
              Ravenswatch Mod Manager (RSMM) is a free app that installs Ravenswatch mods, keeps
              them in order and puts your game back the way it was whenever you ask.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-3">
              <OsDownload release={release} showVersion={false} />
              <Link
                href="/download"
                className="text-lg text-parchment/75 underline underline-offset-4 hover:text-parchment"
              >
                Other downloads
              </Link>
            </div>
            <p className="mt-4 text-base text-parchment/60">
              {release.tag ? `Version ${release.tag.replace(/^v/, '')} for` : 'For'} Windows, Linux
              and Steam Deck. Free and open source.
            </p>
          </div>

          <div className="lg:col-span-5">
            <div className="grimoire-card flex h-full flex-col gap-5 p-6">
              <h2 className="font-display text-2xl text-parchment">Find a mod</h2>
              {/* A plain GET form: works without JavaScript and lands on the
                  registry with the query already filled in. */}
              <form action="/registry" method="get" className="flex gap-2">
                <label htmlFor="home-search" className="sr-only">
                  Search mods
                </label>
                <div className="relative flex-1">
                  <Search
                    className="pointer-events-none absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-parchment/50"
                    aria-hidden="true"
                  />
                  <input
                    id="home-search"
                    name="q"
                    type="search"
                    placeholder="Search mods"
                    className="input-grim !py-3 !pl-11 !text-lg"
                  />
                </div>
                <button type="submit" className={buttonVariants({ size: 'lg' })}>
                  Search
                </button>
              </form>
              <div className="flex flex-wrap gap-2">
                {categories.map((c) => (
                  <Link
                    key={c}
                    href={`/registry?category=${c}` as Route}
                    className="rounded-full border border-border/80 px-3.5 py-1 text-base text-parchment/80 hover:border-gilt/60 hover:text-gilt"
                  >
                    {c}
                  </Link>
                ))}
              </div>
              <p className="mt-auto text-base text-parchment/60">
                {totalMods > 0
                  ? `${totalMods} mods, installed ${fmt(totalModDownloads)} times. Every upload is scanned for malware before it goes live.`
                  : 'Every upload is scanned for malware before it goes live.'}
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Popular mods: the registry is the front page */}
      <section className="container mx-auto px-6 pb-16 lg:pb-24">
        <div className="flex items-baseline justify-between gap-6">
          <h2 className="font-display text-3xl text-parchment sm:text-4xl">Popular mods</h2>
          <Link href="/registry" className="text-lg underline underline-offset-4 hover:text-gilt">
            Browse all mods
          </Link>
        </div>
        {popular.length > 0 ? (
          <div className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {popular.map((mod) => (
              <ModCard key={mod.id} mod={mod} />
            ))}
          </div>
        ) : (
          <p className="mt-8 text-lg text-parchment/70">
            The registry could not be reached just now.{' '}
            <Link href="/registry" className="underline underline-offset-4 hover:text-parchment">
              Open it directly
            </Link>
            .
          </p>
        )}
      </section>

      {/* How it works: a real sequence, so it is numbered */}
      <section className="border-y border-border/60 bg-card/40">
        <ol className="container mx-auto grid gap-10 px-6 py-14 md:grid-cols-3 md:gap-12">
          {steps.map((s, i) => (
            <li key={s.title} className="flex gap-5">
              <span
                className="font-display w-9 shrink-0 text-5xl leading-none text-gilt"
                aria-hidden="true"
              >
                {i + 1}
              </span>
              <div>
                <h2 className="font-display text-2xl text-parchment">{s.title}</h2>
                <p className="mt-2 text-lg leading-relaxed text-parchment/70">{s.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* The app: one large, readable screenshot, then what else it does */}
      <section className="container mx-auto px-6 py-16 lg:py-24">
        <h2 className="font-display text-3xl text-parchment sm:text-4xl">Inside the app</h2>
        <figure className="gilt-frame mt-8">
          <img
            src="/screens/library.jpg"
            alt="The RSMM library: installed mods grouped by category, each with an on/off switch and settings"
            width={2160}
            height={1350}
            className="block h-auto w-full"
            loading="lazy"
          />
        </figure>
        <div className="mt-12 grid gap-12 md:grid-cols-3 md:gap-8">
          {screens.map((s) => (
            <figure key={s.src}>
              <img
                src={s.src}
                alt={s.alt}
                width={2160}
                height={1350}
                loading="lazy"
                className="block h-auto w-full rounded border border-border"
              />
              <figcaption className="mt-5">
                <h3 className="font-display text-2xl text-parchment">{s.title}</h3>
                <p className="mt-2 text-lg leading-relaxed text-parchment/70">{s.body}</p>
              </figcaption>
            </figure>
          ))}
        </div>
      </section>

      {/* For mod authors */}
      <section className="border-y border-border/60 bg-card/40">
        <div className="container mx-auto grid items-center gap-10 px-6 py-16 lg:grid-cols-2 lg:py-20">
          <div>
            <h2 className="font-display text-3xl text-parchment sm:text-4xl">Make your own</h2>
            <p className="mt-5 max-w-lg text-lg leading-relaxed text-parchment/70">
              Mods are data, not code: a manifest that says what changes, plus any textures, models
              or sounds. The open-source <code className="text-gilt">rsmm</code> tool builds, tests
              and publishes them. Gameplay scripting in Lua is there when you need it.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <Link href="/modding" className={buttonVariants({ size: 'lg' })}>
                Modding guide
              </Link>
              <a
                href="https://github.com/Ovilli/RavenswatchModManager"
                className={buttonVariants({ variant: 'outline', size: 'lg' })}
                target="_blank"
                rel="noopener noreferrer"
              >
                Source code
              </a>
            </div>
            <p className="mt-5 text-base text-parchment/60">
              Stuck on a setup problem instead?{' '}
              <Link href="/guides" className="underline underline-offset-4 hover:text-parchment">
                Read the community guides
              </Link>
              .
            </p>
          </div>
          <pre className="overflow-x-auto rounded border border-border bg-background/80 p-6 font-data !text-[0.95rem] leading-7 text-parchment/85">
            <code>
              <span className="text-parchment/45">
                # start from a copy of an existing magical object
              </span>
              {'\n'}rsmm new my-first-mod --kind item{'\n'}
              <span className="text-parchment/45"># check it, then try it in the game</span>
              {'\n'}rsmm lint my-first-mod{'\n'}rsmm apply{'\n'}
              <span className="text-parchment/45"># upload it to the registry</span>
              {'\n'}rsmm publish my-first-mod
            </code>
          </pre>
        </div>
      </section>

      <script
        type="application/ld+json"
        // biome-ignore lint/security/noDangerouslySetInnerHtml: server-built JSON-LD. Serialized through jsonLd() so every ld+json block on the site escapes identically.
        dangerouslySetInnerHTML={{
          __html: jsonLd({
            '@context': 'https://schema.org',
            '@type': 'SoftwareApplication',
            name: 'Ravenswatch Mod Manager',
            alternateName: 'RSMM',
            description:
              'Free, open-source mod manager for Ravenswatch. Installs mods from the registry, backs up every file it replaces and restores the original game on request.',
            applicationCategory: 'UtilitiesApplication',
            operatingSystem: 'Windows, Linux, SteamOS',
            url: 'https://rsmm.me',
            downloadUrl: 'https://rsmm.me/download',
            image: 'https://rsmm.me/screens/library.jpg',
            ...(release.tag ? { softwareVersion: release.tag.replace(/^v/, '') } : {}),
            offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
            publisher: { '@id': 'https://rsmm.me/#org' },
          }),
        }}
      />

      {/* FAQ */}
      <script
        type="application/ld+json"
        // biome-ignore lint/security/noDangerouslySetInnerHtml: static FAQ content. Still serialized through jsonLd() so every ld+json block on the site escapes identically.
        dangerouslySetInnerHTML={{
          __html: jsonLd({
            '@context': 'https://schema.org',
            '@type': 'FAQPage',
            mainEntity: faqs.map((f) => ({
              '@type': 'Question',
              name: f.q,
              acceptedAnswer: { '@type': 'Answer', text: f.a },
            })),
          }),
        }}
      />
      <section className="container mx-auto px-6 pb-16 pt-20 lg:pb-20 lg:pt-28">
        <h2 className="font-display text-3xl text-parchment sm:text-4xl">Questions</h2>
        <FAQ />
        <p className="mt-10 text-lg text-parchment/70">
          Not answered here? The{' '}
          <a
            href="https://docs.rsmm.me"
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-4 hover:text-parchment"
          >
            documentation
          </a>{' '}
          goes deeper, or{' '}
          <a
            href="https://github.com/Ovilli/RavenswatchModManager/issues"
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-4 hover:text-parchment"
          >
            open an issue
          </a>
          .
        </p>
        {appDownloads > 0 ? (
          <p className="mt-2 text-base text-parchment/50">
            The app has been downloaded {fmt(appDownloads)} times.
          </p>
        ) : null}
      </section>
    </main>
  );
}
