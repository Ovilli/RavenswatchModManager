'use client';

import type { ModListItem } from '@rsmm/schemas';
import { Badge, Spinner, buttonVariants } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  LayoutGrid,
  Rows3,
  Star,
} from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useRef, useState } from 'react';
import { api } from '../../../lib/api';
import { getApiUrl } from '../../../lib/api-url';
import {
  type RegistryFilters,
  readRegistryQuery,
  registryFilterCount,
  registryFilterHref,
  registryHref,
} from '../../../lib/registry-query';
import { ModCard } from '../../components/mod-card';
import { ModCover } from '../../components/mod-cover';
import { RegistrySearch, RegistrySearchFallback } from '../../components/registry-search';
import { type RegistryFacet, RegistryFilterDialog } from './registry-filters';
import './registry.css';

type View = 'grid' | 'list';
const VIEW_KEY = 'rsmm:registry-view';
const PAGE_SIZE = 48;

export default function RegistryPage() {
  return (
    <Suspense fallback={<RegistryFallback />}>
      <RegistryInner />
    </Suspense>
  );
}

function RegistryFallback() {
  return (
    <main className="registry-explore">
      <div className="registry-browse-space">
        <div className="registry-browse-bar">
          <h1>Explore mods</h1>
          <RegistrySearchFallback />
          <div className="registry-toolbar-controls-placeholder" aria-hidden />
        </div>
      </div>
      <div className="registry-loading">
        <Spinner />
        <span>Loading mods…</span>
      </div>
    </main>
  );
}

function RegistryInner() {
  const router = useRouter();
  const search = useSearchParams();
  const { query, filters, sort, page } = readRegistryQuery(search.toString());
  const { category, tags, minRating, featuredOnly, showNsfw } = filters;
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [view, setView] = useState<View>('grid');
  const resultsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(VIEW_KEY);
      if (stored === 'grid' || stored === 'list') setView(stored);
    } catch {
      /* Storage can be disabled; the grid remains available. */
    }
  }, []);

  const chooseView = (next: View) => {
    setView(next);
    try {
      localStorage.setItem(VIEW_KEY, next);
    } catch {
      /* Optional preference. */
    }
  };
  const applyFilters = (next: RegistryFilters) => {
    window.history.replaceState(null, '', registryFilterHref(window.location.search, next));
    setFiltersOpen(false);
  };
  const resetSearch = () => window.history.replaceState(null, '', '/registry');
  const goToPage = (next: number) => {
    const params = new URLSearchParams(window.location.search);
    if (next > 1) params.set('page', String(next));
    else params.delete('page');
    window.history.replaceState(null, '', registryHref(params));
    resultsRef.current?.scrollIntoView({ block: 'start' });
  };

  const list = useQuery({
    queryKey: ['registry', query, category, tags, minRating, sort, featuredOnly, showNsfw, page],
    queryFn: () =>
      api.mods.list({
        q: query || undefined,
        category: category === 'all' ? undefined : category,
        tags: tags.length ? tags : undefined,
        minRating: minRating || undefined,
        sort,
        featured: featuredOnly || undefined,
        nsfw: showNsfw ? undefined : false,
        facets: true,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      }),
    placeholderData: (previous) => previous,
  });
  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const facetsRef = useRef<{ categories: RegistryFacet[]; tags: RegistryFacet[] }>({
    categories: [],
    tags: [],
  });
  if (list.data?.facets) facetsRef.current = list.data.facets;
  const facets = facetsRef.current;
  const activeFilters = registryFilterCount(filters);
  const heading =
    list.isLoading || list.isError
      ? 'Explore mods'
      : list.isPlaceholderData
        ? 'Finding mods…'
        : query
          ? `${total.toLocaleString()} ${total === 1 ? 'mod' : 'mods'} for “${query}”`
          : `${total.toLocaleString()} ${total === 1 ? 'mod' : 'mods'} to explore`;

  return (
    <main className="registry-explore">
      <div className="registry-browse-space">
        <header className="registry-browse-bar">
          <h1 title={heading}>{heading}</h1>
          <RegistrySearch
            activeFilters={activeFilters}
            filtersOpen={filtersOpen}
            onOpenFilters={() => setFiltersOpen(true)}
          />
          <div className="registry-result-controls">
            <label className="registry-sort">
              <span>Sort by</span>
              <select
                aria-label="Sort mods"
                value={sort}
                onChange={(event) => {
                  const params = new URLSearchParams(window.location.search);
                  params.delete('page');
                  if (event.target.value === 'popular') params.delete('sort');
                  else params.set('sort', event.target.value);
                  window.history.replaceState(null, '', registryHref(params));
                }}
              >
                <option value="popular">Popular</option>
                <option value="recent">Recent</option>
                <option value="rating">Top rated</option>
              </select>
              <ChevronDown size={14} aria-hidden />
            </label>
            <fieldset className="registry-view-switch">
              <legend className="sr-only">Layout</legend>
              <button
                type="button"
                className="registry-icon-button"
                aria-label="Cards"
                aria-pressed={view === 'grid'}
                onClick={() => chooseView('grid')}
              >
                <LayoutGrid size={18} aria-hidden />
              </button>
              <button
                type="button"
                className="registry-icon-button"
                aria-label="List"
                aria-pressed={view === 'list'}
                onClick={() => chooseView('list')}
              >
                <Rows3 size={18} aria-hidden />
              </button>
            </fieldset>
          </div>
        </header>
      </div>

      <div ref={resultsRef} className="registry-results" aria-busy={list.isFetching}>
        <output className="sr-only">
          {list.isFetching
            ? 'Updating mods…'
            : list.isError
              ? 'The registry could not be reached.'
              : `${total} mods found.`}
        </output>
        {list.isLoading ? (
          <div className="registry-loading">
            <Spinner />
            <span>Loading mods…</span>
          </div>
        ) : list.isError ? (
          <div className="registry-empty">
            <h2>We couldn’t load the mods</h2>
            <p>Check your connection and try again.</p>
            <button type="button" className="registry-apply" onClick={() => list.refetch()}>
              Try again
            </button>
          </div>
        ) : items.length === 0 ? (
          <div className="registry-empty">
            <h2>No mods found</h2>
            <p>Try a different search or remove a filter to see more mods.</p>
            <button type="button" className="registry-apply" onClick={resetSearch}>
              Reset search and filters
            </button>
          </div>
        ) : (
          <div className={view === 'grid' ? 'registry-grid' : 'registry-list'}>
            {items.map((mod) =>
              view === 'grid' ? (
                <ModCard key={mod.id} mod={mod} featured={mod.featured} />
              ) : (
                <ModListRow
                  key={mod.id}
                  m={mod}
                  onOpen={() => router.push(`/registry/${mod.slug}` as Route)}
                />
              ),
            )}
          </div>
        )}
        {!list.isError && totalPages > 1 ? (
          <nav className="registry-pagination" aria-label="Result pages">
            <button
              type="button"
              onClick={() => goToPage(page - 1)}
              disabled={page <= 1 || list.isFetching}
              className={buttonVariants({ variant: 'outline', size: 'sm' })}
            >
              <ChevronLeft size={16} aria-hidden /> Previous
            </button>
            <span>
              Page {page} of {totalPages}
            </span>
            <button
              type="button"
              onClick={() => goToPage(page + 1)}
              disabled={page >= totalPages || list.isFetching}
              className={buttonVariants({ variant: 'outline', size: 'sm' })}
            >
              Next <ChevronRight size={16} aria-hidden />
            </button>
          </nav>
        ) : null}
        <p className="registry-help">
          New to modding? <Link href="/download">Get the Mod Manager</Link> or read the{' '}
          <Link href="/modding">Modding Guide</Link>.
        </p>
      </div>
      {filtersOpen ? (
        <RegistryFilterDialog
          filters={filters}
          categories={facets.categories}
          tags={facets.tags}
          onApply={applyFilters}
          onClose={() => setFiltersOpen(false)}
        />
      ) : null}
    </main>
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
        <ModCover
          seed={m.slug}
          name={m.name}
          size="sm"
          className="hidden h-10 w-16 shrink-0 rounded sm:flex"
        />
      )}

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <Link
            href={`/registry/${m.slug}` as Route}
            onClick={(e) => e.stopPropagation()}
            className="truncate text-base leading-tight transition-colors hover:text-gilt"
          >
            {m.name}
          </Link>
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
