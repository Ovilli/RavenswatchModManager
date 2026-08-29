import type { Collection, ModListItem } from '@rsmm/schemas';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router';
import {
  ChevronDown,
  ChevronRight,
  ExternalLink,
  EyeOff,
  LayoutGrid,
  Loader2,
  Plus,
  Rows3,
  Search,
  WifiOff,
  X,
} from 'lucide-react';
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Button, CopyButton, Cover, MonoTag, SectionHeader, StatPill } from '../components/chrome';
import { CheckIcon } from '../components/icons/CheckIcon';
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
import { TParts, useT } from '../lib/i18n-react';
import { validateProfileName } from '../lib/profile-name';
import { installModFromIndex, listLocalModsForProfile } from '../lib/rsmm';
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
  // `null` = follow the layout: open when browsing, collapsed while a mod's
  // details are taking up the middle column. A click on the header pins it
  // either way, because a filter panel that reopens itself is worse than one
  // that stays where you put it.
  const [filtersPinned, setFiltersPinned] = useState<boolean | null>(null);
  const filterBodyId = useId();
  const [minRating, setMinRating] = useState(0);
  const installed = useApp((s) => s.installed);
  const profiles = useApp((s) => s.profiles);
  const installMod = useApp((s) => s.installMod);
  const createProfile = useApp((s) => s.createProfile);
  const syncLocalMods = useApp((s) => s.syncLocalMods);
  const profile = useApp(activeProfile);
  const showNsfw = useApp((s) => s.settings.showNsfw);
  const view = useApp((s) => s.settings.browseView);
  const update = useApp((s) => s.updateSettings);
  const queryClient = useQueryClient();
  const toast = useToast();
  // Per-slug install state so each card spins independently.
  const [installing, setInstalling] = useState<Record<string, boolean>>({});
  const [installError, setInstallError] = useState<string | null>(null);
  // Profile-picker modal state: when set, user picked Install on a
  // card and needs to choose which profile to drop it into.
  const [pickerSlug, setPickerSlug] = useState<string | null>(null);

  async function handleInstall(slug: string, targetProfileId: string) {
    setInstallError(null);
    setInstalling((m) => ({ ...m, [slug]: true }));
    try {
      // Already-on-disk path skips the network round-trip.
      if (!installed.includes(slug)) {
        const result = await installModFromIndex(slug, targetProfileId);
        if (!result || !result.ok) {
          throw new Error(result?.error ?? t('install failed'));
        }
        const local = await listLocalModsForProfile(targetProfileId);
        if (local) syncLocalMods(local);
      }
      installMod(slug, targetProfileId);
      // Default profile installs create a new "My Mods" profile — read the
      // active profile after installMod, not the requested id.
      const { profiles, activeProfileId } = useApp.getState();
      const profileName = profiles.find((p) => p.id === activeProfileId)?.name ?? t('profile');
      toast.push(t('Added {slug} to “{profile}”.', { slug, profile: profileName }), 'success');
      // Bust the list cache so download counts refresh.
      await queryClient.invalidateQueries({ queryKey: ['mods', 'list'] });
    } catch (err) {
      setInstallError(err instanceof Error ? err.message : String(err));
    } finally {
      setInstalling((m) => ({ ...m, [slug]: false }));
    }
  }

  function openPicker(slug: string) {
    setInstallError(null);
    setPickerSlug(slug);
  }

  function pickProfile(profileId: string) {
    const slug = pickerSlug;
    setPickerSlug(null);
    if (!slug) return;
    void handleInstall(slug, profileId);
  }

  function pickNewProfile(name: string) {
    const trimmed = name.trim();
    if (!trimmed) return;
    const err = validateProfileName(trimmed);
    if (err) {
      toast.push(err, 'error');
      return;
    }
    const slug = pickerSlug;
    setPickerSlug(null);
    if (!slug) return;
    const newId = createProfile(trimmed);
    void handleInstall(slug, newId);
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

  const clearFilters = () => {
    setCategory(null);
    setTags([]);
    setMinRating(0);
    setHideInstalled(false);
  };

  const toggleTag = (t: string) =>
    setTags((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]));

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

  // Auto-collapse, unless the user has said otherwise.
  const filtersOpen = filtersPinned ?? selected === null;

  /**
   * Hoisted so it can be rendered in either place: its own column while
   * browsing, or folded into the narrow index column once a mod's page has
   * taken the right-hand side. One definition, two homes — a second copy would
   * drift the first time a facet was added.
   */
  const filterPanel =
    tab === 'mods' ? (
      <aside
        aria-label={t('Filters')}
        // Its own sticky column while browsing; a plain block at the top of the
        // index column once a mod is open, where the column already sets the
        // width and the sticky/order rules would fight it.
        className={`grimoire-card flex flex-col gap-3 p-3 ${
          selected
            ? ''
            : `p-4 lg:sticky lg:top-2 lg:order-3 lg:shrink-0 ${filtersOpen ? 'lg:w-64' : 'lg:w-auto'}`
        }`}
      >
        <button
          type="button"
          onClick={() => setFiltersPinned(!filtersOpen)}
          aria-expanded={filtersOpen}
          aria-controls={filterBodyId}
          className="flex items-baseline justify-between gap-3 text-left"
        >
          <span className="font-fraktur inline-flex items-baseline gap-2 text-lg text-parchment">
            {filtersOpen ? (
              <ChevronDown className="h-4 w-4 self-center text-ash" aria-hidden />
            ) : (
              <ChevronRight className="h-4 w-4 self-center text-ash" aria-hidden />
            )}
            {t('Filters')}
          </span>
          {/* Collapsed, the count of ACTIVE filters is the load-bearing
                      number: it is the only way to tell a short result list from a
                      filtered one when the facets are hidden. */}
          <span className="font-mono whitespace-nowrap text-xs text-ash">
            {filtersOpen
              ? t.n(list.length, '{n} mod', '{n} mods')
              : activeFilters > 0
                ? t('{n} on', { n: activeFilters })
                : t('off')}
          </span>
        </button>

        {filtersOpen ? (
          <div id={filterBodyId} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <span className="font-mono text-xs uppercase tracking-widest text-ash">
                {t('category')}
              </span>
              <div className="flex flex-wrap gap-1.5">
                <FilterChip active={category === null} onClick={() => setCategory(null)}>
                  {t('any')}
                </FilterChip>
                {facets.categories.map(([name, count]) => (
                  <FilterChip
                    key={name}
                    active={category === name}
                    onClick={() => setCategory(category === name ? null : name)}
                  >
                    {name} <span className="text-ash">{count}</span>
                  </FilterChip>
                ))}
              </div>
              {facets.categories.length === 0 ? (
                <span className="font-serif-italic text-sm text-ash">
                  {t('nothing published yet')}
                </span>
              ) : null}
            </div>

            {facets.tags.length > 0 ? (
              <div className="flex flex-col gap-2">
                <span className="font-mono text-xs uppercase tracking-widest text-ash">
                  {t('tags')}
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {facets.tags.map(([name, count]) => (
                    <FilterChip
                      key={name}
                      active={tags.includes(name)}
                      onClick={() => toggleTag(name)}
                    >
                      {name} <span className="text-ash">{count}</span>
                    </FilterChip>
                  ))}
                </div>
              </div>
            ) : null}

            <label className="flex flex-col gap-2">
              <span className="font-mono text-xs uppercase tracking-widest text-ash">
                {t('rating')}
              </span>
              <select
                value={minRating}
                onChange={(e) => setMinRating(Number(e.target.value))}
                aria-label={t('Minimum rating')}
                className="select-grim"
              >
                <option value={0}>{t('any')}</option>
                <option value={3}>★ 3+</option>
                <option value={4}>★ 4+</option>
                <option value={4.5}>★ 4.5+</option>
              </select>
            </label>

            <label className="flex cursor-pointer items-start gap-2 text-parchment">
              <input
                type="checkbox"
                checked={hideInstalled}
                onChange={(e) => setHideInstalled(e.target.checked)}
                className="mt-1 h-4 w-4 accent-crimson"
              />
              <span className="font-serif-italic text-sm">{t('Hide what I already have')}</span>
            </label>

            {activeFilters > 0 ? (
              <Button type="button" size="sm" onClick={clearFilters} className="w-full">
                <X className="h-3.5 w-3.5" aria-hidden /> {t('clear {n}', { n: activeFilters })}
              </Button>
            ) : null}
          </div>
        ) : null}
      </aside>
    ) : null;

  return (
    <div className="space-y-6">
      <SectionHeader
        title={tab === 'mods' ? t('Browse') : t('Collections')}
        subtitle={
          tab === 'mods'
            ? t('The remote index. Mods from the community catalog.')
            : t('Curated bundles of mods made by the community.')
        }
      />

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant={tab === 'mods' ? 'primary' : 'default'}
            onClick={() => setTab('mods')}
          >
            {t('Mods')}
          </Button>
          <Button
            type="button"
            size="sm"
            variant={tab === 'collections' ? 'primary' : 'default'}
            onClick={() => setTab('collections')}
          >
            {t('Collections')}
          </Button>
        </div>
        <div className="relative flex-1 min-w-[260px]">
          <Search
            className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ash"
            aria-hidden
          />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={tab === 'mods' ? t('Search the index…') : t('Search collections…')}
            aria-label={tab === 'mods' ? t('Search mods') : t('Search collections')}
            className="input-grim"
          />
        </div>
        {tab === 'mods' ? (
          <>
            <div className="flex items-center gap-2">
              {(['popular', 'recent', 'rating'] as const).map((s) => (
                <Button
                  key={s}
                  type="button"
                  onClick={() => setSort(s)}
                  aria-pressed={sort === s}
                  variant={sort === s ? 'gilt' : 'default'}
                  size="sm"
                >
                  {s === 'popular' ? t('popular') : s === 'recent' ? t('recent') : t('rating')}
                </Button>
              ))}
            </div>
            <label className="flex cursor-pointer items-center gap-2 text-parchment">
              <input
                type="checkbox"
                checked={showNsfw}
                onChange={(e) => update({ showNsfw: e.target.checked })}
                className="h-4 w-4 accent-crimson"
              />
              <span className="inline-flex items-center gap-1 rounded border border-crimson/30 bg-crimson/10 px-1.5 py-0.5 font-mono text-[11px] uppercase tracking-widest text-crimson/80">
                <EyeOff className="h-3 w-3" /> NSFW
              </span>
            </label>
            <fieldset className="ml-auto flex items-center gap-1">
              <legend className="sr-only">{t('Layout')}</legend>
              <Button
                type="button"
                size="sm"
                aria-pressed={view === 'grid'}
                variant={view === 'grid' ? 'gilt' : 'default'}
                onClick={() => update({ browseView: 'grid' })}
                title={t('Cards')}
              >
                <LayoutGrid className="h-3.5 w-3.5" aria-hidden /> {t('cards')}
              </Button>
              <Button
                type="button"
                size="sm"
                aria-pressed={view === 'list'}
                variant={view === 'list' ? 'gilt' : 'default'}
                onClick={() => update({ browseView: 'list' })}
                title={t('List')}
              >
                <Rows3 className="h-3.5 w-3.5" aria-hidden /> {t('list')}
              </Button>
            </fieldset>
          </>
        ) : null}
      </div>

      {/* TWO columns, never three. Faceted search reads as a column beside the
          results — but once a mod's page is open there is no room for a third,
          so the filters fold into the index column (collapsed, see
          `filtersOpen`) and the store page takes the whole right-hand side.
          Squeezed into a middle column it had nowhere to put its own two-column
          layout, and the index beside it was too narrow to show a mod's name.

          Below `lg` there is no second column at all, so everything stacks —
          a filter you cannot reach is worse than one that costs a scroll. */}
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

        {/* Browsing: the filters get their own column on the right. */}
        {selected ? null : filterPanel}

        {/* With a mod open the results become an index column, wide enough for
            a name and its install button and no wider. */}
        <div
          className={
            selected
              ? 'min-w-0 space-y-3 lg:order-1 lg:w-[22rem] lg:shrink-0'
              : 'min-w-0 flex-1 space-y-4 lg:order-1'
          }
        >
          {/* …and the filters ride along above it, collapsed. */}
          {selected ? filterPanel : null}
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
              <div className="font-mono text-xs text-ash bg-pitch/30 px-2 py-1 rounded">
                {getApiBaseUrl()} <span className="text-oxblood/60">|</span> {t('origin:')}{' '}
                {window.location.origin}
              </div>
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

          {isLoading ? <BrowseSkeleton /> : null}

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
                    className="grimoire-card flex flex-col gap-3 p-5 cursor-pointer transition-colors duration-150 hover:border-gilt/40 focus:border-gilt/60 focus:outline-none"
                  >
                    {c.imageUrl ? (
                      <Cover
                        src={c.imageUrl}
                        alt={t('{name} cover', { name: c.name })}
                        caption={`${c.slug}.png`}
                      />
                    ) : null}
                    <header className="flex items-start justify-between gap-3">
                      <div>
                        <Link
                          to="/collection/$slug"
                          params={{ slug: c.slug }}
                          onClick={(e) => e.stopPropagation()}
                          className="font-serif-italic text-xl leading-tight text-parchment hover:text-gilt"
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
              <div
                className={
                  view === 'list'
                    ? 'flex flex-col gap-2'
                    : 'grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3'
                }
              >
                {view === 'list'
                  ? list.map((m) => (
                      <ModRow
                        key={m.id}
                        m={m}
                        active={selected === m.slug}
                        compact={selected !== null}
                        onOpen={() => setSelected(m.slug)}
                        install={
                          <InstallButton
                            m={m}
                            installed={installed}
                            profile={profile}
                            installing={installing}
                            onPick={openPicker}
                          />
                        }
                      />
                    ))
                  : list.map((m) => {
                      return (
                        <div
                          key={m.id}
                          tabIndex={0}
                          // biome-ignore lint/a11y/useSemanticElements: card link with nested interactive controls; <a> may not legally wrap them, so a guarded role="link" is used
                          role="link"
                          aria-label={
                            m.author
                              ? t('{name} by {author}', { name: m.name, author: m.author })
                              : m.name
                          }
                          onClick={(e) => {
                            const el = e.target as HTMLElement;
                            if (el.closest('button, a, input, textarea, select, [role="switch"]'))
                              return;
                            navigate({ to: '/mod/$slug', params: { slug: m.slug } });
                          }}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault();
                              navigate({ to: '/mod/$slug', params: { slug: m.slug } });
                            }
                          }}
                          aria-current={selected === m.slug ? 'true' : undefined}
                          className={`grimoire-card flex cursor-pointer flex-col gap-3 p-5 transition-colors duration-150 hover:border-gilt/40 focus:border-gilt/60 focus:outline-none ${
                            selected === m.slug ? 'border-gilt/70 bg-gilt/5' : ''
                          }`}
                        >
                          {m.imageUrl ? (
                            <Cover
                              src={m.imageUrl}
                              alt={t('{name} cover', { name: m.name })}
                              caption={`${m.slug}.png`}
                              nsfw={m.nsfw}
                            />
                          ) : null}
                          <header className="flex items-start justify-between gap-3">
                            <div>
                              <Link
                                to="/mod/$slug"
                                params={{ slug: m.slug }}
                                onClick={(e) => e.stopPropagation()}
                                className="font-serif-italic text-xl leading-tight text-parchment hover:text-gilt"
                              >
                                {m.name}
                              </Link>
                              <p className="font-mono mt-1 text-ash">
                                {m.author ?? t('unknown')}
                                {m.latestVersion ? ` · v${m.latestVersion}` : ''}
                              </p>
                            </div>
                            <InstallButton
                              m={m}
                              installed={installed}
                              profile={profile}
                              installing={installing}
                              onPick={openPicker}
                            />
                          </header>
                          {m.summary ? (
                            <p className="font-serif-italic text-sm leading-snug text-smoke">
                              {m.summary}
                            </p>
                          ) : null}
                          <div className="mt-auto flex items-center justify-between gap-2">
                            <div className="flex flex-wrap gap-1">
                              {m.category ? <MonoTag tone="default">{m.category}</MonoTag> : null}
                              {m.tags.slice(0, 2).map((t) => (
                                <MonoTag key={t} tone="default">
                                  {t}
                                </MonoTag>
                              ))}
                            </div>
                            <StatPill
                              value={m.rating != null ? `★ ${m.rating.toFixed(1)}` : '—'}
                              label={
                                m.downloads != null
                                  ? t('{n} dl', { n: m.downloads.toLocaleString(t.tag) })
                                  : ''
                              }
                            />
                          </div>
                        </div>
                      );
                    })}
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

      {pickerSlug ? (
        <ProfilePicker
          slug={pickerSlug}
          profiles={profiles}
          onPick={pickProfile}
          onCreate={pickNewProfile}
          onCancel={() => setPickerSlug(null)}
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
  onPick: (slug: string) => void;
}

/**
 * The install control, shared by the card and the list row.
 *
 * Extracted rather than duplicated: it encodes four states (installing / in
 * profile / on disk / not fetched) plus the width floor that stops it
 * resizing mid-download, and two copies of that would drift apart the first
 * time one of them was touched.
 */
function InstallButton({ m, installed, profile, installing, onPick }: InstallButtonProps) {
  const t = useT();
  const onDisk = installed.includes(m.slug);
  // "In profile" must mean the mod is BOTH listed by the profile and
  // actually on disk. A profile entry whose folder is gone (failed install,
  // deleted outside the app) otherwise rendered as "in profile" with the
  // button disabled — leaving no way to install the mod it pointed at.
  const inProfile = profile.loadOrder.includes(m.slug) && onDisk;
  return (
    <Button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onPick(m.slug);
      }}
      disabled={inProfile || installing[m.slug]}
      variant={inProfile ? 'default' : 'primary'}
      size="sm"
      // The label cycles install → downloading → in profile,
      // each a different width. Without a floor the button
      // resizes mid-download and squeezes the title next to it.
      className="min-w-[7.5rem] justify-center whitespace-nowrap"
      title={
        inProfile
          ? t('Already in "{profile}"', { profile: profile.name })
          : onDisk
            ? t('On disk — click to add to "{profile}"', { profile: profile.name })
            : t('Download from index + add to "{profile}"', { profile: profile.name })
      }
    >
      {installing[m.slug] ? (
        <>
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> {t('downloading')}
        </>
      ) : inProfile ? (
        <>
          <CheckIcon className="h-4 w-4" /> {t('in profile')}
        </>
      ) : onDisk ? (
        <>
          <Plus className="h-3.5 w-3.5" /> {t('add')}
        </>
      ) : (
        <>
          <Plus className="h-3.5 w-3.5" /> {t('install')}
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
  compact = false,
}: {
  m: ModListItem;
  install: React.ReactNode;
  onOpen: () => void;
  active: boolean;
  compact?: boolean;
}) {
  const t = useT();
  const open = onOpen;
  return (
    <div
      tabIndex={0}
      // biome-ignore lint/a11y/useSemanticElements: row link with nested interactive controls; <a> may not legally wrap them, so a guarded role="link" is used
      role="link"
      aria-label={m.author ? t('{name} by {author}', { name: m.name, author: m.author }) : m.name}
      onClick={(e) => {
        const el = e.target as HTMLElement;
        if (el.closest('button, a, input, textarea, select, [role="switch"]')) return;
        open();
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          open();
        }
      }}
      aria-current={active ? 'true' : undefined}
      className={`grimoire-card flex cursor-pointer items-center gap-3 px-3 py-2 transition-colors duration-150 hover:border-gilt/40 focus:border-gilt/60 focus:outline-none ${
        active ? 'border-gilt/70 bg-gilt/5' : ''
      }`}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          {/* Plain text, NOT a link to the full page.
              The row selects; the name is the most obvious thing to aim at, and
              having it navigate away instead meant a slightly-off click threw
              you out of the list you were working through. The detail panel
              carries an explicit "open full page" for when that IS the intent. */}
          <span className="font-serif-italic truncate text-base leading-tight text-parchment">
            {m.name}
          </span>
          {m.nsfw ? (
            <span className="font-mono shrink-0 rounded border border-crimson/30 bg-crimson/10 px-1 text-[10px] uppercase tracking-widest text-crimson/80">
              {t('nsfw')}
            </span>
          ) : null}
        </div>
        <p className="font-mono truncate text-xs text-ash">
          {m.author ?? t('unknown')}
          {m.latestVersion ? ` · v${m.latestVersion}` : ''}
          {m.summary ? ` — ${m.summary}` : ''}
        </p>
      </div>

      {/* Category and rating are the two columns worth scanning down, so they
          get fixed slots rather than flowing with the title's length. Hidden on
          a narrow window instead of crushing the name. */}
      {compact ? null : (
        <>
          <div className="hidden w-24 shrink-0 md:block">
            {m.category ? <MonoTag tone="default">{m.category}</MonoTag> : null}
          </div>
          <div className="font-mono hidden w-16 shrink-0 text-right text-xs text-gilt lg:block">
            {m.rating != null ? `★ ${m.rating.toFixed(1)}` : '—'}
          </div>
          <div className="font-mono hidden w-20 shrink-0 text-right text-xs text-ash lg:block">
            {m.downloads != null ? t('{n} dl', { n: m.downloads.toLocaleString(t.tag) }) : ''}
          </div>
        </>
      )}
      <div className="shrink-0">{install}</div>
    </div>
  );
}

/** One toggleable facet in the filter bar. */
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
      className={`font-mono rounded border px-2 py-0.5 text-xs lowercase transition-colors duration-150 ${
        active
          ? 'border-gilt/70 bg-gilt/15 text-parchment'
          : 'border-border text-smoke hover:border-gilt/40 hover:text-parchment'
      }`}
    >
      {children}
    </button>
  );
}

function ProfilePicker({
  slug,
  profiles,
  onPick,
  onCreate,
  onCancel,
}: {
  slug: string;
  profiles: Profile[];
  onPick: (profileId: string) => void;
  onCreate: (name: string) => void;
  onCancel: () => void;
}) {
  const t = useT();
  const selectable = profiles.filter((p) => p.id !== 'default');
  const [creating, setCreating] = useState(selectable.length === 0);
  const [name, setName] = useState('');
  const rootRef = useRef<HTMLDialogElement>(null);

  // Escape only reaches onKeyDown when focus is inside the dialog, and nothing
  // here is focused when the profile list (rather than the name field) renders.
  useEffect(() => {
    rootRef.current?.focus();
  }, []);

  // Portalled to <body> on purpose. Rendered in place, this lands inside
  // `main > .animate-page-in`, whose transform animation makes it the
  // containing block for `position: fixed` descendants — so `fixed inset-0`
  // pinned itself to the *page* box, not the viewport, and the picker opened
  // off-screen above the fold whenever the user hit Install after scrolling.
  // Same reason the quit prompt and the mod config dialog portal.
  return createPortal(
    <dialog
      open
      ref={rootRef}
      tabIndex={-1}
      aria-label={t('Choose profile')}
      className="fixed inset-0 z-[70] flex items-center justify-center p-4 animate-fade-in outline-none"
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.preventDefault();
          onCancel();
        }
      }}
    >
      <div className="absolute inset-0 bg-pitch/80" onClick={onCancel} />
      <div className="grimoire-card relative w-[min(480px,92vw)] p-5">
        <h3 className="font-fraktur text-xl text-parchment">{t('Install to profile')}</h3>
        <p className="font-serif-italic text-ash mt-2">
          <TParts
            text={t('Pick which profile receives {slug}.')}
            parts={{ slug: <span className="font-mono">{slug}</span> }}
          />
        </p>
        {!creating && selectable.length > 0 ? (
          <ul className="mt-4 space-y-2">
            {selectable.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => onPick(p.id)}
                  className="grimoire-card w-full px-4 py-3 text-left hover:border-gilt/40 transition-colors"
                >
                  <div className="truncate font-serif-italic text-parchment" title={p.name}>
                    {p.name}
                  </div>
                  <div className="font-mono text-xs text-ash">
                    {t.n(p.loadOrder.length, '{n} mod', '{n} mods')}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        {creating ? (
          <div className="mt-4 space-y-2">
            <label htmlFor="new-profile-name" className="font-mono block text-ash">
              {t('New profile name')}
            </label>
            <input
              id="new-profile-name"
              ref={(el) => el?.focus()}
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  if (name.trim()) onCreate(name);
                }
              }}
              placeholder={t('My Mods')}
              className="input-grim w-full"
            />
          </div>
        ) : null}
        <div className="mt-5 flex items-center justify-between gap-2">
          {selectable.length > 0 ? (
            <Button type="button" size="sm" onClick={() => setCreating((c) => !c)}>
              {creating ? t('pick existing') : t('create new')}
            </Button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button type="button" size="sm" onClick={onCancel}>
              {t('cancel')}
            </Button>
            {creating ? (
              <Button
                type="button"
                size="sm"
                variant="primary"
                onClick={() => onCreate(name)}
                disabled={!name.trim()}
              >
                {t('create + install')}
              </Button>
            ) : null}
          </div>
        </div>
      </div>
    </dialog>,
    document.body,
  );
}

function BrowseSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" aria-busy="true">
      {Array.from({ length: 6 }).map((_, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: static skeleton elements, no reordering
        <div key={i} className="grimoire-card flex flex-col gap-3 p-5 animate-pulse">
          <div className="aspect-video w-full bg-oxblood/20 rounded" />
          <div className="h-6 w-3/4 bg-oxblood/20 rounded" />
          <div className="h-4 w-1/2 bg-oxblood/15 rounded" />
          <div className="h-4 w-full bg-oxblood/10 rounded" />
        </div>
      ))}
    </div>
  );
}
