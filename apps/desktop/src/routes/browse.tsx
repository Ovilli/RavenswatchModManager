import {
  type Collection,
  type ModListItem,
  hasPrivateOnlyTag,
  isPrivateOnlyTag,
} from '@rsmm/schemas';
import {
  RegistryFilterDialog,
  RegistryModCard,
  RegistryResultsControls,
  RegistrySearchBar,
} from '@rsmm/ui';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router';
import { ExternalLink, Loader2, Plus, WifiOff, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Button, CopyButton, Cover, Panel, StatPill, useModalChrome } from '../components/chrome';
import { CheckIcon } from '../components/icons/CheckIcon';
import { ModDetail } from '../components/mod-detail';
import { PrivateGamesOnlyBadge } from '../components/private-games-only-badge';
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
import { installModIntoProfile } from '../lib/profile-mods';
import { validateProfileName } from '../lib/profile-name';
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
  const profiles = useApp((s) => s.profiles);
  const createProfile = useApp((s) => s.createProfile);
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
      // Downloads into the TARGET profile's folder unless that folder already
      // has the mod. `installed` describes the active profile, which the
      // target often is not (the picker offers every profile).
      await installModIntoProfile(slug, targetProfileId);
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
                            onPick={openPicker}
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

      {pickerSlug ? (
        <ProfilePicker
          slug={pickerSlug}
          profiles={profiles}
          onPick={pickProfile}
          onCreate={pickNewProfile}
          onCancel={() => setPickerSlug(null)}
        />
      ) : null}
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
      className="registry-install-button min-w-0 justify-center whitespace-nowrap"
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
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
          <span className="registry-install-label">{t('downloading')}</span>
        </>
      ) : inProfile ? (
        <>
          <CheckIcon className="h-4 w-4 shrink-0" />
          <span className="registry-install-label">{t('in profile')}</span>
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
  const nameRef = useRef<HTMLInputElement>(null);
  const rootRef = useRef<HTMLDialogElement>(null);
  // Focus starts on the dialog (nothing in the profile list is focused when it
  // renders, so Escape would never reach onKeyDown) and returns to Install on
  // close. Declared before the effect below so a create form opening on mount
  // still ends up with focus in its field.
  const onKeyDown = useModalChrome(rootRef, onCancel);

  // Focus the field ONCE, when the create form appears. An inline
  // `ref={(el) => el?.focus()}` has a new identity every render, so React
  // detached and reattached it and re-ran `focus()` on every keystroke and
  // every parent re-render.
  useEffect(() => {
    if (creating) nameRef.current?.focus();
  }, [creating]);
  const [name, setName] = useState('');

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
      onKeyDown={onKeyDown}
    >
      <div className="absolute inset-0 bg-pitch/80" onClick={onCancel} />
      <div className="grimoire-card grimoire-card--raised relative w-[min(480px,92vw)] p-5">
        <h3 className="font-fraktur text-xl text-parchment">{t('Install to profile')}</h3>
        <p className="font-serif-italic text-ash mt-2">
          <TParts
            text={t('Pick which profile receives {slug}.')}
            parts={{ slug: <span className="font-data">{slug}</span> }}
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
              ref={nameRef}
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
