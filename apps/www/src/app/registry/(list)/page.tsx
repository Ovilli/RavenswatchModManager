'use client';
import type { ModCategory, ModListItem } from '@rsmm/schemas';
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
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Download,
  ExternalLink,
  EyeOff,
  LayoutGrid,
  Rows3,
  Search,
  Star,
  X,
} from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useCallback, useEffect, useId, useRef, useState } from 'react';
import { api } from '../../../lib/api';
import { getApiUrl } from '../../../lib/api-url';

type Sort = 'popular' | 'recent' | 'rating';
type View = 'grid' | 'list';

/**
 * Categories the schema allows. Used only to validate a `?category=` off the
 * URL — what the panel OFFERS comes from the API's facet counts, so a category
 * nothing is published under is never presented as a filter that can only ever
 * return nothing.
 */
const CATEGORY_IDS: ModCategory[] = [
  'gameplay',
  'balance',
  'cosmetic',
  'qol',
  'audio',
  'difficulty',
  'speedrun',
  'utility',
];

const RATINGS: { value: number; label: string }[] = [
  { value: 0, label: 'Any rating' },
  { value: 3, label: '★ 3+' },
  { value: 4, label: '★ 4+' },
  { value: 4.5, label: '★ 4.5+' },
];

/** Remembered per browser, the way the desktop client remembers it per profile. */
const VIEW_KEY = 'rsmm:registry-view';

function readStoredView(): View | null {
  try {
    const v = localStorage.getItem(VIEW_KEY);
    return v === 'grid' || v === 'list' ? v : null;
  } catch {
    // Private windows and blocked site data throw on access, not on read.
    return null;
  }
}

/** One toggleable facet in the filter panel. */
function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
        active
          ? 'border-crimson/60 bg-crimson/15 text-foreground'
          : 'border-border/70 text-muted-foreground hover:border-border hover:text-foreground'
      }`}
    >
      {children}
    </button>
  );
}

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
    return c && (CATEGORY_IDS as string[]).includes(c) ? (c as ModCategory) : 'all';
  });
  const [tags, setTags] = useState<string[]>(() => {
    const t = search.get('tags');
    return t
      ? t
          .split(',')
          .map((x) => x.trim())
          .filter(Boolean)
      : [];
  });
  const [minRating, setMinRating] = useState(() => {
    const r = Number(search.get('rating'));
    return RATINGS.some((x) => x.value === r) ? r : 0;
  });
  const [filtersOpen, setFiltersOpen] = useState(true);
  const filterBodyId = useId();
  // Starts at the server-rendered default and adopts the stored preference on
  // mount — reading localStorage during render would desync hydration.
  const [view, setView] = useState<View>('grid');
  useEffect(() => {
    const stored = readStoredView();
    if (stored) setView(stored);
  }, []);
  const chooseView = useCallback((v: View) => {
    setView(v);
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      // Not being able to remember the choice is not a reason to refuse it.
    }
  }, []);
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
  }, [debouncedQ, cat, sort, featuredOnly, showNsfw, tags, minRating]);

  // Mirror browse state into the URL (replace, not push — no history spam).
  useEffect(() => {
    const p = new URLSearchParams();
    if (debouncedQ) p.set('q', debouncedQ);
    if (cat !== 'all') p.set('category', cat);
    if (tags.length) p.set('tags', tags.join(','));
    if (minRating > 0) p.set('rating', String(minRating));
    if (sort !== 'popular') p.set('sort', sort);
    if (featuredOnly) p.set('featured', '1');
    if (showNsfw) p.set('nsfw', '1');
    if (page > 1) p.set('page', String(page));
    const qs = p.toString();
    window.history.replaceState(null, '', qs ? `/registry?${qs}` : '/registry');
  }, [debouncedQ, cat, tags, minRating, sort, featuredOnly, showNsfw, page]);

  // Filtering, sorting, and paging all happen server-side now — the old
  // client-side pass only ever saw the first 48 mods.
  const list = useQuery({
    queryKey: ['registry', debouncedQ, cat, tags, minRating, sort, featuredOnly, showNsfw, page],
    queryFn: () =>
      api.mods.list({
        q: debouncedQ || undefined,
        category: cat === 'all' ? undefined : cat,
        tags: tags.length ? tags : undefined,
        minRating: minRating || undefined,
        sort,
        featured: featuredOnly || undefined,
        nsfw: showNsfw ? undefined : false,
        // The panel's counts come from the server, over the search/featured/NSFW
        // conditions but NOT the facet ones — see the list route.
        facets: true,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      }),
    placeholderData: (prev) => prev,
  });

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  // Keep the last non-empty facets while a refetch is in flight, so the panel
  // does not blink empty every time a chip is clicked.
  const facetsRef = useRef<{
    categories: { name: string; count: number }[];
    tags: { name: string; count: number }[];
  }>({ categories: [], tags: [] });
  if (list.data?.facets) facetsRef.current = list.data.facets;
  const facets = facetsRef.current;

  // The API grew `facets` in the same push that added this panel, but www and
  // the API are separate Vercel projects and do not go live in lockstep. Fall
  // back to the schema's categories (countless, but pickable) so the panel is
  // never an empty box against an API that has not rolled yet.
  const categoryFacets = facets.categories.length
    ? facets.categories
    : CATEGORY_IDS.map((name) => ({ name, count: 0 }));

  // Only the panel's own filters count here: it is the number that tells a
  // genuinely short result list apart from a heavily filtered one.
  const activeFilters = (cat === 'all' ? 0 : 1) + tags.length + (minRating > 0 ? 1 : 0);

  const toggleTag = (t: string) =>
    setTags((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]));

  const clearFacets = () => {
    setCat('all');
    setTags([]);
    setMinRating(0);
  };

  const clearFilters = () => {
    setQ('');
    clearFacets();
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
          <fieldset className="ml-auto flex items-center gap-1">
            <legend className="sr-only">Layout</legend>
            <button
              type="button"
              aria-pressed={view === 'grid'}
              onClick={() => chooseView('grid')}
              className={buttonVariants({
                variant: view === 'grid' ? 'default' : 'outline',
                size: 'sm',
              })}
              title="Cards"
            >
              <LayoutGrid className="mr-1 h-3.5 w-3.5" aria-hidden="true" />
              Cards
            </button>
            <button
              type="button"
              aria-pressed={view === 'list'}
              onClick={() => chooseView('list')}
              className={buttonVariants({
                variant: view === 'list' ? 'default' : 'outline',
                size: 'sm',
              })}
              title="List"
            >
              <Rows3 className="mr-1 h-3.5 w-3.5" aria-hidden="true" />
              List
            </button>
          </fieldset>
        </div>

        {/* Two columns: the panel reads as a column beside the results on a wide
            screen and folds above them on a narrow one. */}
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
          <aside
            aria-label="Filters"
            className="grimoire-card flex shrink-0 flex-col gap-3 p-4 lg:sticky lg:top-4 lg:w-64"
          >
            <button
              type="button"
              onClick={() => setFiltersOpen((v) => !v)}
              aria-expanded={filtersOpen}
              aria-controls={filterBodyId}
              className="flex items-baseline justify-between gap-3 text-left"
            >
              <span className="inline-flex items-baseline gap-2 text-base font-semibold">
                {filtersOpen ? (
                  <ChevronDown
                    className="h-4 w-4 self-center text-muted-foreground"
                    aria-hidden="true"
                  />
                ) : (
                  <ChevronUp
                    className="h-4 w-4 self-center text-muted-foreground"
                    aria-hidden="true"
                  />
                )}
                Filters
              </span>
              {/* Collapsed, the count of ACTIVE filters is the load-bearing
                  number: it is the only way to tell a short result list from a
                  filtered one once the facets are hidden. */}
              <span className="whitespace-nowrap font-mono text-xs text-muted-foreground">
                {filtersOpen
                  ? `${total.toLocaleString()} ${total === 1 ? 'mod' : 'mods'}`
                  : activeFilters > 0
                    ? `${activeFilters} on`
                    : 'off'}
              </span>
            </button>

            {filtersOpen ? (
              <div id={filterBodyId} className="flex flex-col gap-4">
                <div className="flex flex-col gap-2">
                  <span className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
                    category
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    <FilterChip active={cat === 'all'} onClick={() => setCat('all')}>
                      any
                    </FilterChip>
                    {categoryFacets.map((c) => (
                      <FilterChip
                        key={c.name}
                        active={cat === c.name}
                        onClick={() => setCat(cat === c.name ? 'all' : (c.name as ModCategory))}
                      >
                        {c.name}
                        {c.count > 0 ? (
                          <span className="text-muted-foreground"> {c.count}</span>
                        ) : null}
                      </FilterChip>
                    ))}
                  </div>
                </div>

                {facets.tags.length > 0 ? (
                  <div className="flex flex-col gap-2">
                    <span className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
                      tags
                    </span>
                    <div className="flex flex-wrap gap-1.5">
                      {facets.tags.map((t) => (
                        <FilterChip
                          key={t.name}
                          active={tags.includes(t.name)}
                          onClick={() => toggleTag(t.name)}
                        >
                          {t.name} <span className="text-muted-foreground">{t.count}</span>
                        </FilterChip>
                      ))}
                    </div>
                    {tags.length > 1 ? (
                      <span className="text-xs text-muted-foreground">
                        Showing mods carrying every selected tag.
                      </span>
                    ) : null}
                  </div>
                ) : null}

                <label className="flex flex-col gap-2">
                  <span className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
                    rating
                  </span>
                  <select
                    value={minRating}
                    onChange={(e) => setMinRating(Number(e.target.value))}
                    aria-label="Minimum rating"
                    className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                  >
                    {RATINGS.map((r) => (
                      <option key={r.value} value={r.value}>
                        {r.label}
                      </option>
                    ))}
                  </select>
                </label>

                {activeFilters > 0 ? (
                  <button
                    type="button"
                    onClick={clearFacets}
                    className={buttonVariants({ variant: 'outline', size: 'sm' })}
                  >
                    <X className="mr-1 h-3.5 w-3.5" aria-hidden="true" /> Clear {activeFilters}
                  </button>
                ) : null}
              </div>
            ) : null}
          </aside>

          <div className="min-w-0 flex-1 space-y-6">
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
              <div
                className={
                  view === 'list'
                    ? 'flex flex-col gap-2'
                    : 'grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3'
                }
              >
                {items.map((m) => {
                  const open = () => router.push(`/registry/${m.slug}` as Route);
                  return view === 'list' ? (
                    <ModListRow key={m.id} m={m} onOpen={open} />
                  ) : (
                    <ModGridCard key={m.id} m={m} onOpen={open} />
                  );
                })}
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
        </div>
      </div>
    </main>
  );
}

/** Card layout — image, title, actions, summary, stats. */
function ModGridCard({ m, onOpen }: { m: ModListItem; onOpen: () => void }) {
  return (
    <div
      className="grimoire-card cursor-pointer overflow-hidden"
      tabIndex={0}
      // biome-ignore lint/a11y/useSemanticElements: card-as-link composite with nested interactive children; wrapping with <a> would invalidate the descendant <a>/<button> tags Next.js Link inserts.
      role="link"
      onClick={(e) => {
        const el = e.target as HTMLElement;
        if (el.closest('a, button, input, textarea, select, [role="switch"]')) return;
        onOpen();
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onOpen();
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
            {m.downloads != null ? <span>{m.downloads.toLocaleString()} dl</span> : null}
          </div>
          <div className="flex items-center gap-1">
            {m.rating != null ? <span>★ {m.rating.toFixed(1)}</span> : null}
          </div>
        </div>
      </CardContent>
    </div>
  );
}

/**
 * Row layout — the same mods, one line each, for scanning rather than browsing.
 *
 * Category, rating and downloads get fixed-width slots so they line up into
 * columns down the page instead of flowing with each title's length; the
 * narrower ones drop out on small screens rather than crushing the name.
 */
function ModListRow({ m, onOpen }: { m: ModListItem; onOpen: () => void }) {
  return (
    <div
      tabIndex={0}
      // biome-ignore lint/a11y/useSemanticElements: row-as-link composite with nested interactive children; an <a> may not legally wrap them.
      role="link"
      aria-label={`${m.name}${m.author ? ` by ${m.author}` : ''}`}
      onClick={(e) => {
        const el = e.target as HTMLElement;
        if (el.closest('a, button, input, textarea, select, [role="switch"]')) return;
        onOpen();
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onOpen();
        }
      }}
      className="grimoire-card flex cursor-pointer items-center gap-3 px-3 py-2"
    >
      {m.imageUrl ? (
        <img
          src={m.imageUrl}
          alt=""
          loading="lazy"
          className="hidden h-10 w-16 shrink-0 rounded object-cover sm:block"
        />
      ) : (
        <div className="hidden h-10 w-16 shrink-0 rounded bg-muted sm:block" />
      )}

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <a
            href={`/registry/${m.slug}`}
            onClick={(e) => e.stopPropagation()}
            className="truncate text-base leading-tight transition-colors hover:text-gilt"
          >
            {m.name}
          </a>
          {m.featured ? (
            <Star className="h-3 w-3 shrink-0 text-gilt" aria-label="Featured" />
          ) : null}
          {m.nsfw ? (
            <span className="shrink-0 rounded border border-crimson/40 bg-crimson/10 px-1 font-mono text-[10px] uppercase tracking-widest text-crimson">
              nsfw
            </span>
          ) : null}
        </div>
        <p className="truncate text-xs text-muted-foreground">
          {m.author ?? 'unknown'}
          {m.latestVersion ? ` · v${m.latestVersion}` : ''}
          {m.summary ? ` — ${m.summary}` : ''}
        </p>
      </div>

      <div className="hidden w-24 shrink-0 md:block">
        {m.category ? (
          <Badge variant="secondary" className="text-[0.65rem]">
            {m.category}
          </Badge>
        ) : null}
      </div>
      <div className="hidden w-14 shrink-0 text-right font-mono text-xs text-gilt lg:block">
        {m.rating != null ? `★ ${m.rating.toFixed(1)}` : '—'}
      </div>
      <div className="hidden w-20 shrink-0 text-right font-mono text-xs text-muted-foreground lg:block">
        {m.downloads != null ? `${m.downloads.toLocaleString()} dl` : ''}
      </div>

      <div className="flex shrink-0 items-center gap-1">
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
  );
}
