import { type ModListItem, hasPrivateOnlyTag, isPrivateOnlyTag } from '@rsmm/schemas';
import {
  RegistryFilterDialog,
  RegistryGridSkeleton,
  RegistryModCard,
  RegistryResultsControls,
  RegistrySearchBar,
} from '@rsmm/ui';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router';
import { ExternalLink, Loader2, Plus, WifiOff, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Button, CopyButton, Cover, Panel } from '../components/chrome';
import { InstalledState } from '../components/installed-state';
import { ModDetail } from '../components/mod-detail';
import { useToast } from '../components/toast';
import { api, describeApiError, getApiBaseUrl, logApiError } from '../lib/api';
import {
  type BrowseSort,
  computeFacets,
  countActiveFilters,
  filterCollections,
  filterMods,
} from '../lib/browse-filter';
import { useT } from '../lib/i18n-react';
import { installModIntoProfile, resolveInstallTarget } from '../lib/profile-mods';
import { registryCardLabels } from '../lib/registry-labels';
import { activeProfile, useApp } from '../store';
import type { Profile } from '../store';

export const Route = createFileRoute('/browse')({
  component: BrowsePage,
});

type Sort = BrowseSort;
type Tab = 'mods' | 'collections';

function BrowsePage() {
  const t = useT();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>('mods');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<Sort>('popular');
  // Filters. Derived facets rather than a hardcoded list, so a category or tag
  // that nothing in the index uses is never offered as a dead end.
  const [category, setCategory] = useState<string | null>(null);
  const [tags, setTags] = useState<string[]>([]);
  const [hideInstalled, setHideInstalled] = useState(false);
  // The mod open in the split panel. Selecting rather than navigating is the
  // point of the whole layout: clicking through five mods should not cost five
  // navigations and five trips back.
  const [selected, setSelected] = useState<string | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [minRating, setMinRating] = useState(0);
  const installed = useApp((s) => s.installed);
  const profile = useApp(activeProfile);
  const showNsfw = useApp((s) => s.settings.showNsfw);
  const view = useApp((s) => s.settings.browseView);
  const update = useApp((s) => s.updateSettings);
  const queryClient = useQueryClient();
  const toast = useToast();
  // Per-slug install state so each card spins independently.
  const [installing, setInstalling] = useState<Record<string, boolean>>({});
  const [installError, setInstallError] = useState<string | null>(null);

  async function handleInstall(slug: string) {
    setInstallError(null);
    setInstalling((m) => ({ ...m, [slug]: true }));
    try {
      // Capture the active profile before downloading into its folder.
      const targetProfileId = resolveInstallTarget();
      await installModIntoProfile(slug, targetProfileId);
      const profileName =
        useApp.getState().profiles.find((p) => p.id === targetProfileId)?.name ?? t('profile');
      toast.push(t('Added {slug} to “{profile}”.', { slug, profile: profileName }), 'success');
      // Bust the list cache so download counts refresh.
      await queryClient.invalidateQueries({ queryKey: ['mods', 'list'] });
    } catch (err) {
      setInstallError(err instanceof Error ? err.message : String(err));
    } finally {
      setInstalling((m) => ({ ...m, [slug]: false }));
    }
  }

  // Mods query
  const {
    data: modData,
    error: modError,
    isLoading: modLoading,
  } = useQuery({
    queryKey: ['mods', 'list', q],
    queryFn: () => api.mods.list({ q: q.trim() || undefined, limit: 100 }),
    staleTime: 30_000,
    retry: 1,
    enabled: tab === 'mods',
  });

  // Collections query
  const {
    data: colData,
    error: colError,
    isLoading: colLoading,
  } = useQuery({
    queryKey: ['collections', 'public'],
    queryFn: () => api.collections.list(),
    staleTime: 30_000,
    retry: 1,
    enabled: tab === 'collections',
  });

  const facets = useMemo(() => computeFacets(modData?.items ?? [], showNsfw), [modData, showNsfw]);

  const list = useMemo(() => {
    if (tab === 'collections') return [];
    return filterMods(modData?.items ?? [], {
      q,
      sort,
      showNsfw,
      category,
      tags,
      minRating,
      hideInstalled,
      installed,
    });
  }, [modData, sort, q, tab, showNsfw, category, tags, minRating, hideInstalled, installed]);

  const activeFilters = countActiveFilters({ category, tags, minRating, hideInstalled });

  const collections = useMemo(
    () => (tab === 'mods' ? [] : filterCollections(colData?.items ?? [], q)),
    [colData, q, tab],
  );

  const isLoading = tab === 'mods' ? modLoading : colLoading;
  const error = tab === 'mods' ? modError : colError;

  useEffect(() => {
    if (error) logApiError('browse', error);
  }, [error]);

  // Esc closes the detail panel. Registered only while one is open so it never
  // competes with the command palette or a modal for the same key.
  useEffect(() => {
    if (!selected) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelected(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selected]);

  // A filter that hides the open mod would otherwise leave its panel stranded
  // beside a list that no longer contains it.
  useEffect(() => {
    if (selected && !list.some((m) => m.slug === selected)) setSelected(null);
  }, [list, selected]);

  // The split panel belongs to the list. Cards are the roomy view and open the
  // full page, so a selection made in the list must not survive a switch to
  // cards — it would sit there with nothing able to change or close it.
  useEffect(() => {
    if (view !== 'list') setSelected(null);
  }, [view]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          {/* `aria-pressed`, like every other toggle group in the app: colour
              alone was the only signal that one of these two was active. */}
          <Button
            type="button"
            size="sm"
            aria-pressed={tab === 'mods'}
            variant={tab === 'mods' ? 'primary' : 'default'}
            onClick={() => setTab('mods')}
          >
            {t('Mods')}
          </Button>
          <Button
            type="button"
            size="sm"
            aria-pressed={tab === 'collections'}
            variant={tab === 'collections' ? 'primary' : 'default'}
            onClick={() => setTab('collections')}
          >
            {t('Collections')}
          </Button>
        </div>
        <div className="min-w-[260px] flex-1">
          <RegistrySearchBar
            query={q}
            onQueryChange={setQ}
            placeholder={tab === 'mods' ? t('Search the index…') : t('Search collections…')}
            searchLabel={tab === 'mods' ? t('Search mods') : t('Search collections')}
            labels={{
              clear: t('Clear search'),
              filters: t('Filters'),
              activeFilters: t('Filters, {n} active', { n: activeFilters }),
            }}
            activeFilters={activeFilters}
            filtersOpen={filtersOpen}
            onOpenFilters={tab === 'mods' ? () => setFiltersOpen(true) : undefined}
          />
        </div>
        {tab === 'mods' ? (
          <RegistryResultsControls
            sort={sort}
            view={view}
            labels={{
              sortBy: t('Sort by'),
              sort: t('Sort mods'),
              popular: t('popular'),
              recent: t('recent'),
              rating: t('Top rated'),
              layout: t('Layout'),
              cards: t('Cards'),
              list: t('List'),
            }}
            onSortChange={setSort}
            onViewChange={(nextView) => update({ browseView: nextView })}
          />
        ) : null}
      </div>

      {/* The shared registry filter dialog keeps filtering out of the list
          layout, including when a mod detail is open beside it. */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
        {selected ? (
          <section aria-label={t('Mod details')} className="min-w-0 flex-1 lg:order-2">
            <div className="mb-2 flex items-center justify-end gap-2">
              <Link
                to="/mod/$slug"
                params={{ slug: selected }}
                className="font-mono text-xs text-ash underline-offset-2 hover:text-parchment hover:underline"
              >
                {t('open full page')}
              </Link>
              <Button type="button" size="sm" onClick={() => setSelected(null)}>
                <X className="h-3.5 w-3.5" aria-hidden /> {t('close')}
              </Button>
            </div>
            <ModDetail slug={selected} embedded />
          </section>
        ) : null}

        {/* With a mod open the results become an index column, wide enough for
            a name and its install button and no wider. */}
        <div
          aria-busy={isLoading}
          className={
            selected
              ? 'min-w-0 space-y-3 lg:order-1 lg:w-[22rem] lg:shrink-0'
              : 'min-w-0 flex-1 space-y-4 lg:order-1'
          }
        >
          {error ? (
            <div className="ember-banner flex flex-col gap-2 px-4 py-3">
              <div className="flex items-center gap-3">
                <WifiOff className="h-4 w-4 text-crimson shrink-0" />
                <span className="font-serif-italic text-base">{t('API unreachable.')}</span>
                <CopyButton value={describeApiError(error)} />
                <button
                  type="button"
                  onClick={() => window.open(getApiBaseUrl(), '_blank')}
                  className="font-mono text-xs text-ash underline-offset-2 hover:text-parchment hover:underline flex items-center gap-1"
                >
                  <ExternalLink className="h-3 w-3" /> {t('open in browser')}
                </button>
              </div>
              <p className="font-serif-italic text-sm text-ash">{describeApiError(error)}</p>
              <Panel variant="inset" className="font-mono px-2 py-1 text-xs text-ash">
                {getApiBaseUrl()} <span className="text-oxblood/60">|</span> {t('origin:')}{' '}
                {window.location.origin}
              </Panel>
            </div>
          ) : null}

          {installError ? (
            <div className="ember-banner flex items-center gap-3 px-4 py-3">
              <span className="font-serif-italic text-base text-crimson flex-1">
                {t('Install failed: {error}', { error: installError })}
              </span>
              <CopyButton value={installError} />
              <Button type="button" size="sm" onClick={() => setInstallError(null)}>
                {t('dismiss')}
              </Button>
            </div>
          ) : null}

          {isLoading ? <RegistryGridSkeleton /> : null}

          {tab === 'collections' ? (
            <>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                {collections.map((c) => (
                  <div
                    key={c.id}
                    tabIndex={0}
                    // biome-ignore lint/a11y/useSemanticElements: card link with nested interactive controls; <a> may not legally wrap them, so a guarded role="link" is used
                    role="link"
                    aria-label={c.name}
                    onClick={(e) => {
                      const el = e.target as HTMLElement;
                      if (el.closest('button, a, input, textarea, select, [role="switch"]')) return;
                      navigate({ to: '/collection/$slug', params: { slug: c.slug } });
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        navigate({ to: '/collection/$slug', params: { slug: c.slug } });
                      }
                    }}
                    className="grimoire-card flex flex-col gap-3 p-5 cursor-pointer transition-colors duration-150 hover:border-gilt/40 focus:border-gilt/60"
                  >
                    {c.imageUrl ? (
                      <Cover
                        src={c.imageUrl}
                        alt={t('{name} cover', { name: c.name })}
                        caption={`${c.slug}.png`}
                      />
                    ) : null}
                    <header className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <Link
                          to="/collection/$slug"
                          params={{ slug: c.slug }}
                          onClick={(e) => e.stopPropagation()}
                          className="font-serif-italic break-words text-xl leading-tight text-parchment hover:text-gilt"
                        >
                          {c.name}
                        </Link>
                        <p className="font-mono mt-1 text-ash">
                          {c.ownerName ?? t('unknown')} · {t.n(c.modCount, '{n} mod', '{n} mods')}
                        </p>
                      </div>
                    </header>
                    {c.summary ? (
                      <p className="font-serif-italic text-sm leading-snug text-smoke">
                        {c.summary}
                      </p>
                    ) : null}
                    <div className="mt-auto flex items-center justify-between gap-2">
                      <span className="font-mono text-xs text-ash">
                        {t('updated {date}', {
                          date: new Date(c.updatedAt).toLocaleDateString(t.tag),
                        })}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
              {!isLoading && !error && collections.length === 0 ? (
                <p className="font-serif-italic py-10 text-center text-ash">
                  {q.trim()
                    ? t('No collections match that search.')
                    : t('No public collections yet.')}
                </p>
              ) : null}
            </>
          ) : (
            <>
              <div className={view === 'list' ? 'registry-list' : 'registry-grid'}>
                {view === 'list'
                  ? list.map((m) => (
                      <ModRow
                        key={m.id}
                        m={m}
                        active={selected === m.slug}
                        onOpen={() => setSelected(m.slug)}
                        install={
                          <InstallButton
                            m={m}
                            installed={installed}
                            profile={profile}
                            installing={installing}
                            onInstall={handleInstall}
                          />
                        }
                      />
                    ))
                  : list.map((m) => (
                      <RegistryModCard
                        key={m.id}
                        mod={m}
                        privateOnly={hasPrivateOnlyTag(m.tags)}
                        active={selected === m.slug}
                        onOpen={() => navigate({ to: '/mod/$slug', params: { slug: m.slug } })}
                        actions={
                          <InstallButton
                            m={m}
                            installed={installed}
                            profile={profile}
                            installing={installing}
                            onInstall={handleInstall}
                          />
                        }
                        locale={t.tag}
                        labels={registryCardLabels(t, m)}
                      />
                    ))}
              </div>
              {!isLoading && !error && list.length === 0 ? (
                <p className="font-serif-italic py-10 text-center text-ash">
                  {q.trim()
                    ? t('No mods match that search.')
                    : t('No mods published to the index yet.')}
                </p>
              ) : null}
            </>
          )}
        </div>
      </div>

      {filtersOpen && tab === 'mods' ? (
        <RegistryFilterDialog
          value={{
            category: category ?? '',
            tags,
            minRating,
            toggles: { hideInstalled, showNsfw },
          }}
          categories={facets.categories.map(([name, count]) => ({
            value: name,
            label: name,
            count,
          }))}
          tags={facets.tags.map(([name, count]) => ({
            value: name,
            label: isPrivateOnlyTag(name) ? t('Private games only') : name,
            count,
          }))}
          ratings={[
            { value: 0, label: t('any') },
            { value: 3, label: '3+' },
            { value: 4, label: '4+' },
            { value: 4.5, label: '4.5+' },
          ]}
          toggles={[
            { id: 'hideInstalled', label: t('Hide what I already have'), checked: hideInstalled },
            { id: 'showNsfw', label: t('Include mature content'), checked: showNsfw },
          ]}
          labels={{
            title: t('Filters'),
            close: t('Close filters'),
            category: t('Category'),
            tags: t('Tags'),
            rating: t('Rating'),
            preferences: t('Preferences'),
            all: t('any'),
            clear: t('Clear all'),
            apply: t('Show mods'),
          }}
          onApply={(next) => {
            setCategory(next.category || null);
            setTags(next.tags);
            setMinRating(next.minRating);
            setHideInstalled(next.toggles.hideInstalled ?? false);
            update({ showNsfw: next.toggles.showNsfw ?? showNsfw });
            setFiltersOpen(false);
          }}
          onClose={() => setFiltersOpen(false)}
          onClear={() => ({
            category: '',
            tags: [],
            minRating: 0,
            toggles: { hideInstalled: false, showNsfw },
          })}
        />
      ) : null}
    </div>
  );
}

interface InstallButtonProps {
  m: ModListItem;
  /** Slugs present on disk. */
  installed: string[];
  profile: Profile;
  installing: Record<string, boolean>;
  onInstall: (slug: string) => void;
}

/**
 * The install control, shared by the card and the list row.
 *
 * Extracted rather than duplicated: it encodes four states (installing / in
 * profile / on disk / not fetched) plus the width floor that stops it
 * resizing mid-download, and two copies of that would drift apart the first
 * time one of them was touched.
 */
function InstallButton({ m, installed, profile, installing, onInstall }: InstallButtonProps) {
  const t = useT();
  const onDisk = installed.includes(m.slug);
  // "In profile" must mean the mod is BOTH listed by the profile and
  // actually on disk. A profile entry whose folder is gone (failed install,
  // deleted outside the app) otherwise rendered as "in profile" with the
  // button disabled — leaving no way to install the mod it pointed at.
  const inProfile = profile.loadOrder.includes(m.slug) && onDisk;
  if (inProfile && !installing[m.slug]) {
    return <InstalledState title={t('Already in "{profile}"', { profile: profile.name })} />;
  }
  return (
    <Button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onInstall(m.slug);
      }}
      disabled={installing[m.slug]}
      variant="primary"
      size="sm"
      className="registry-install-button min-w-0 justify-center whitespace-nowrap"
      title={
        onDisk
          ? t('On disk — click to add to "{profile}"', { profile: profile.name })
          : t('Download from index + add to "{profile}"', { profile: profile.name })
      }
    >
      {installing[m.slug] ? (
        <>
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
          <span className="registry-install-label">{t('downloading')}</span>
        </>
      ) : onDisk ? (
        <>
          <Plus className="h-3.5 w-3.5 shrink-0" />
          <span className="registry-install-label">{t('add')}</span>
        </>
      ) : (
        <>
          <Plus className="h-3.5 w-3.5 shrink-0" />
          <span className="registry-install-label">{t('install')}</span>
        </>
      )}
    </Button>
  );
}

/**
 * One mod as a dense row.
 *
 * The card view is for discovery — cover art, summary, room to breathe. This is
 * for comparison: everything on one line, so the eye can run down a column of
 * ratings or download counts instead of hopping around a grid.
 *
 * The install control is passed IN rather than rebuilt here. It carries four
 * states and a width floor, and a second copy would drift from the card's the
 * first time either was touched.
 *
 * @param compact  the row is in a narrow column (the split view's index), so
 *                 drop the stat columns. They are hidden by `md:`/`lg:`
 *                 breakpoints otherwise — and those measure the VIEWPORT, not
 *                 this row's container, so on a wide window they kept rendering
 *                 inside an 18rem column and squeezed the mod name to nothing.
 */
function ModRow({
  m,
  install,
  onOpen,
  active,
}: {
  m: ModListItem;
  install: React.ReactNode;
  onOpen: () => void;
  active: boolean;
}) {
  const t = useT();
  return (
    <RegistryModCard
      view="list"
      mod={m}
      privateOnly={hasPrivateOnlyTag(m.tags)}
      active={active}
      onOpen={onOpen}
      actions={install}
      locale={t.tag}
      labels={registryCardLabels(t, m)}
    />
  );
}
