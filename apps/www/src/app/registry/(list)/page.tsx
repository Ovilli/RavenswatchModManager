'use client';
import type { ModCategory } from '@rsmm/schemas';
import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Spinner,
  buttonVariants,
} from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import {
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  EyeOff,
  Search,
  Star,
} from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useRef, useState } from 'react';
import { api } from '../../../lib/api';
import { getApiUrl } from '../../../lib/api-url';

type Sort = 'popular' | 'recent' | 'rating';

const CATEGORIES: { id: ModCategory | 'all'; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'gameplay', label: 'Gameplay' },
  { id: 'balance', label: 'Balance' },
  { id: 'cosmetic', label: 'Cosmetic' },
  { id: 'qol', label: 'QoL' },
  { id: 'audio', label: 'Audio' },
  { id: 'difficulty', label: 'Difficulty' },
  { id: 'speedrun', label: 'Speedrun' },
  { id: 'utility', label: 'Utility' },
];

export default function RegistryPage() {
  return (
    <Suspense fallback={<RegistryFallback />}>
      <RegistryInner />
    </Suspense>
  );
}

function RegistryFallback() {
  return (
    <main className="relative overflow-hidden animate-page-in">
      <div className="container mx-auto flex items-center justify-center px-6 py-24">
        <Spinner />
      </div>
    </main>
  );
}

const PAGE_SIZE = 48;
const SORTS: { id: Sort; label: string }[] = [
  { id: 'popular', label: 'Popular' },
  { id: 'recent', label: 'Recent' },
  { id: 'rating', label: 'Top rated' },
];

function RegistryInner() {
  const router = useRouter();
  const search = useSearchParams();
  // Seed all browse state from the URL so deep links (and Google's sitelinks
  // search box via the WebSite SearchAction) land on pre-filled results.
  const [q, setQ] = useState(() => search.get('q') ?? '');
  const [debouncedQ, setDebouncedQ] = useState(q);
  const [cat, setCat] = useState<ModCategory | 'all'>(() => {
    const c = search.get('category');
    return c && CATEGORIES.some((x) => x.id === c) ? (c as ModCategory) : 'all';
  });
  const [sort, setSort] = useState<Sort>(() => {
    const s = search.get('sort');
    return s === 'recent' || s === 'rating' ? s : 'popular';
  });
  const [featuredOnly, setFeaturedOnly] = useState(() => search.get('featured') === '1');
  const [showNsfw, setShowNsfw] = useState(() => search.get('nsfw') === '1');
  const [page, setPage] = useState(() => Math.max(1, Number(search.get('page')) || 1));

  // Debounce typing so each keystroke doesn't hit the API.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q), 300);
    return () => clearTimeout(t);
  }, [q]);

  // Any filter change restarts at page 1 (skip the initial mount so a
  // deep-linked ?page= survives).
  const mounted = useRef(false);
  // biome-ignore lint/correctness/useExhaustiveDependencies: the filter values are the trigger, not inputs — the effect intentionally runs on every filter change.
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    setPage(1);
  }, [debouncedQ, cat, sort, featuredOnly, showNsfw]);

  // Mirror browse state into the URL (replace, not push — no history spam).
  useEffect(() => {
    const p = new URLSearchParams();
    if (debouncedQ) p.set('q', debouncedQ);
    if (cat !== 'all') p.set('category', cat);
    if (sort !== 'popular') p.set('sort', sort);
    if (featuredOnly) p.set('featured', '1');
    if (showNsfw) p.set('nsfw', '1');
    if (page > 1) p.set('page', String(page));
    const qs = p.toString();
    window.history.replaceState(null, '', qs ? `/registry?${qs}` : '/registry');
  }, [debouncedQ, cat, sort, featuredOnly, showNsfw, page]);

  // Filtering, sorting, and paging all happen server-side now — the old
  // client-side pass only ever saw the first 48 mods.
  const list = useQuery({
    queryKey: ['registry', debouncedQ, cat, sort, featuredOnly, showNsfw, page],
    queryFn: () =>
      api.mods.list({
        q: debouncedQ || undefined,
        category: cat === 'all' ? undefined : cat,
        sort,
        featured: featuredOnly || undefined,
        nsfw: showNsfw ? undefined : false,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      }),
    placeholderData: (prev) => prev,
  });

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const clearFilters = () => {
    setQ('');
    setCat('all');
    setSort('popular');
    setFeaturedOnly(false);
    setShowNsfw(false);
    setPage(1);
  };

  return (
    <main className="relative overflow-hidden animate-page-in">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,hsl(var(--crimson)/0.08),transparent_50%)]" />
      <div className="relative container mx-auto space-y-6 px-6 py-12">
        <header className="space-y-2">
          <h1 className="text-4xl font-bold tracking-tight">Mod Registry</h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Browse community-published mods for Ravenswatch — hero skins, balance tweaks, custom
            magical objects, quality-of-life improvements, audio swaps, and more. Search or filter
            by category below, then install in one click with the{' '}
            <Link href="/download" className="underline hover:text-foreground">
              Mod Manager
            </Link>
            . New to modding? Start with the{' '}
            <Link href="/modding" className="underline hover:text-foreground">
              Modding Guide
            </Link>
            .
          </p>
        </header>

        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-[260px] flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search by name, author, or summary…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="pl-9"
            />
          </div>
          {SORTS.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => setSort(s.id)}
              className={buttonVariants({
                variant: sort === s.id ? 'default' : 'outline',
                size: 'sm',
              })}
            >
              {s.label}
            </button>
          ))}
          <button
            type="button"
            onClick={() => setFeaturedOnly((v) => !v)}
            className={buttonVariants({
              variant: featuredOnly ? 'default' : 'outline',
              size: 'sm',
            })}
            title="Show only featured mods"
          >
            <Star className="mr-1 h-3.5 w-3.5" />
            Featured
          </button>
          <button
            type="button"
            onClick={() => setShowNsfw((v) => !v)}
            className={buttonVariants({
              variant: showNsfw ? 'default' : 'outline',
              size: 'sm',
            })}
            title="Show NSFW/mature mods"
          >
            <EyeOff className="mr-1 h-3.5 w-3.5" />
            NSFW
          </button>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {CATEGORIES.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => setCat(c.id)}
              className={buttonVariants({
                variant: cat === c.id ? 'default' : 'outline',
                size: 'sm',
              })}
            >
              {c.label}
            </button>
          ))}
        </div>

        {list.isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Spinner />
          </div>
        ) : list.isError ? (
          <div className="grimoire-card flex flex-col items-center gap-3 p-10 text-center">
            <p className="text-sm text-muted-foreground">
              The registry could not be reached. Check your connection and try again.
            </p>
            <button
              type="button"
              onClick={() => list.refetch()}
              className={buttonVariants({ variant: 'outline', size: 'sm' })}
            >
              Try again
            </button>
          </div>
        ) : items.length === 0 ? (
          <div className="grimoire-card flex flex-col items-center gap-3 p-10 text-center">
            <p className="text-sm text-muted-foreground">
              No mods match these filters{debouncedQ ? ` for “${debouncedQ}”` : ''}.
            </p>
            <button
              type="button"
              onClick={clearFilters}
              className={buttonVariants({ variant: 'outline', size: 'sm' })}
            >
              Clear filters
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {items.map((m) => (
              <div
                key={m.id}
                className="grimoire-card cursor-pointer overflow-hidden"
                tabIndex={0}
                // biome-ignore lint/a11y/useSemanticElements: card-as-link composite with nested interactive children; wrapping with <a> would invalidate the descendant <a>/<button> tags Next.js Link inserts.
                role="link"
                onClick={(e) => {
                  const el = e.target as HTMLElement;
                  if (el.closest('a, button, input, textarea, select, [role="switch"]')) return;
                  router.push(`/registry/${m.slug}` as Route);
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    router.push(`/registry/${m.slug}` as Route);
                  }
                }}
              >
                <div className="relative">
                  {m.imageUrl ? (
                    <div className="aspect-[16/9] w-full overflow-hidden bg-muted">
                      <img
                        src={m.imageUrl}
                        alt={`${m.name} preview`}
                        className="h-full w-full object-cover"
                        loading="lazy"
                      />
                    </div>
                  ) : (
                    <div className="aspect-[16/9] w-full bg-muted" />
                  )}
                  {m.featured ? (
                    <Badge className="absolute left-2 top-2 bg-gilt/15 text-[0.65rem] text-gilt border-gilt/40 backdrop-blur-sm">
                      <Star className="mr-1 h-3 w-3" /> Featured
                    </Badge>
                  ) : null}
                  {m.nsfw ? (
                    <Badge className="absolute right-2 top-2 bg-crimson/15 text-[0.65rem] text-crimson border-crimson/40 backdrop-blur-sm">
                      <EyeOff className="mr-1 h-3 w-3" /> NSFW
                    </Badge>
                  ) : null}
                </div>
                <CardHeader>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <a
                        href={`/registry/${m.slug}`}
                        onClick={(e) => e.stopPropagation()}
                        className="hover:text-gilt transition-colors"
                      >
                        <CardTitle className="text-lg">{m.name}</CardTitle>
                      </a>
                      <CardDescription className="mt-0.5">
                        {m.author ?? 'unknown'}
                        {m.latestVersion ? (
                          <Badge variant="outline" className="ml-2 text-[0.6rem]">
                            v{m.latestVersion}
                          </Badge>
                        ) : null}
                      </CardDescription>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      {m.latestVersion ? (
                        <a
                          href={`${getApiUrl()}/api/mods/${m.slug}/${m.latestVersion}/download`}
                          className={buttonVariants({ variant: 'outline', size: 'sm' })}
                          title="Download mod archive"
                          aria-label={`Download ${m.name} archive`}
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Download className="h-3.5 w-3.5" aria-hidden="true" />
                        </a>
                      ) : null}
                      <a
                        href={`rsmm://mods/${m.slug}`}
                        className={buttonVariants({ variant: 'outline', size: 'sm' })}
                        title="Open in RSMM desktop app"
                        aria-label={`Open ${m.name} in the RSMM desktop app`}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                      </a>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  {m.summary ? (
                    <p className="text-sm text-muted-foreground line-clamp-2">{m.summary}</p>
                  ) : null}
                  <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                    <div className="flex items-center gap-2">
                      {m.category ? <Badge variant="secondary">{m.category}</Badge> : null}
                      <span>{m.downloads.toLocaleString()} dl</span>
                    </div>
                    <div className="flex items-center gap-1">
                      {m.rating != null ? <span>★ {m.rating.toFixed(1)}</span> : null}
                    </div>
                  </div>
                </CardContent>
              </div>
            ))}
          </div>
        )}

        {!list.isError && totalPages > 1 ? (
          <div className="flex items-center justify-center gap-4 pt-2">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1 || list.isFetching}
              className={buttonVariants({ variant: 'outline', size: 'sm' })}
            >
              <ChevronLeft className="h-4 w-4" /> Previous
            </button>
            <span className="text-sm text-muted-foreground">
              Page {page} of {totalPages} · {total.toLocaleString()} mods
            </span>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages || list.isFetching}
              className={buttonVariants({ variant: 'outline', size: 'sm' })}
            >
              Next <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        ) : null}
      </div>
    </main>
  );
}
