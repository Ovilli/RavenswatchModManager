import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router';
import {
  AlertTriangle,
  ArrowUpDown,
  ExternalLink,
  GripVertical,
  LayoutGrid,
  List,
  Plus,
  Search,
  SlidersHorizontal,
  Trash2,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  CopyButton,
  EmptyState,
  Fleuron,
  InkSwitch,
  MonoTag,
  Panel,
  SectionHeader,
  StatPill,
} from '../components/chrome';
import { ConfigButton } from '../components/config-button';
import { ModConfigPanel } from '../components/mod-config-panel';
import { OverlayButton } from '../components/overlay-button';
import { SetupBanner } from '../components/setup-banner';
import { useDialog, useToast } from '../components/toast';
import { UpdatesPanel } from '../components/updates-panel';
import { useModToggle } from '../components/use-mod-toggle';
import { msg } from '../lib/i18n';
import { useT } from '../lib/i18n-react';
import {
  type LibrarySort,
  type LibraryStatusFilter,
  conflictCountByMod as buildConflictCounts,
  buildLibraryRows,
  missingDepCounts as buildMissingDepCounts,
  countLibraryFilters,
  filterLibraryRows,
  groupByCategory,
} from '../lib/library-filter';
import type { ReactNode } from 'react';
import type { ModCategory } from '../lib/mod-types';
import { disableHookWarning, listLocalMods, uninstallLocalMod } from '../lib/rsmm';
import {
  activeProfile,
  detectConflicts,
  getMod,
  isEnabledIn,
  unadoptedMods,
  useApp,
} from '../store';

type ViewMode = 'cards' | 'list' | 'config';

const VIEW_MODES: ViewMode[] = ['cards', 'list', 'config'];

/**
 * The view lives in the URL so the per-mod Configure button can link straight
 * into the config view. It used to link to the mod's store page, which is no
 * longer where settings live.
 */
export const Route = createFileRoute('/')({
  component: LibraryPage,
  validateSearch: (search: Record<string, unknown>): { view?: ViewMode } => {
    const v = search.view;
    return typeof v === 'string' && (VIEW_MODES as string[]).includes(v)
      ? { view: v as ViewMode }
      : {};
  },
});

/** Anchor a config panel carries, so Configure can scroll to one mod. */
export const configAnchorId = (modId: string) => `mod-config-${modId}`;

/** English sources; render sites pass them through `t()`. */
const CATEGORY_LABEL: Record<ModCategory, string> = {
  gameplay: msg('Gameplay'),
  balance: msg('Balance'),
  cosmetic: msg('Cosmetic'),
  qol: msg('Quality of life'),
  audio: msg('Audio'),
  difficulty: msg('Difficulty'),
  speedrun: msg('Speedrun'),
  utility: msg('Utility'),
};

/** Status filter rows. The stored value is the filter; the label is copy. */
const STATUS_LABEL: Record<LibraryStatusFilter, string> = {
  all: msg('All'),
  enabled: msg('Enabled'),
  disabled: msg('Disabled'),
  outdated: msg('Outdated'),
  missingDeps: msg('Missing deps'),
};

/** A facet heading in the filter rail. Sentence case, not tracked-out caps:
 *  the rail is navigation furniture and should sit under the content it
 *  filters, not shout over it. */
function FacetLabel({ icon, children }: { icon?: ReactNode; children: ReactNode }) {
  return (
    <span className="flex items-center gap-2 text-ash text-xs">
      {icon}
      {children}
    </span>
  );
}

/** One row in a facet list. Full-width and left-aligned so the rail reads as a
 *  list of choices rather than a heap of chips at three different widths. */
function FacetRow({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={[
        'w-full rounded-sm px-2 py-1 text-left text-sm transition-colors duration-150',
        active
          ? 'bg-parchment/10 text-parchment'
          : 'text-smoke hover:bg-parchment/5 hover:text-parchment',
      ].join(' ')}
    >
      {children}
    </button>
  );
}

function LibraryPage() {
  const t = useT();
  const navigate = useNavigate();
  const toast = useToast();
  const dialog = useDialog();
  const profile = useApp(activeProfile);
  const reorderMod = useApp((s) => s.reorderMod);
  const installed = useApp((s) => s.installed);
  const syncLocalMods = useApp((s) => s.syncLocalMods);
  const adoptMods = useApp((s) => s.adoptMods);
  const activeProfileId = useApp((s) => s.activeProfileId);
  const search = Route.useSearch();
  const [view, setView] = useState<ViewMode>(search.view ?? 'cards');
  // Following a Configure link while the Library is already open changes the
  // search param without remounting, so the view has to track it.
  // `view` is the value being synced, not an input: listing it would re-run
  // the effect on every local view change and fight the toolbar.
  // biome-ignore lint/correctness/useExhaustiveDependencies: see above
  useEffect(() => {
    if (search.view && search.view !== view) setView(search.view);
  }, [search.view]);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<ModCategory | 'all'>('all');
  const [status, setStatus] = useState<LibraryStatusFilter>('all');
  const [sort, setSort] = useState<LibrarySort>('load-order');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [dirtyConfigs, setDirtyConfigs] = useState<Set<string>>(new Set());
  const localModsState = useApp((s) => s.localMods);
  // Library is *profile-scoped*: a mod is in the user's library iff
  // it's been explicitly added to the active profile's load order.
  // Mods present on disk but not in this profile live in /browse with
  // an "Installed elsewhere" badge — they don't show up here.

  const availableCategories = useMemo(() => {
    const cats = new Set(Object.values(localModsState).map((m) => m.category));
    return ['all' as const, ...cats];
  }, [localModsState]);

  const enabledCount = useMemo(
    () => profile.loadOrder.filter((id) => localModsState[id] && isEnabledIn(profile, id)).length,
    [profile, localModsState],
  );
  // Mods the CLI found on disk that this profile hasn't opted into — a mod
  // folder copied in by hand, or one installed while another profile was
  // active. Without surfacing these, dropping a folder into mods/ looked
  // like the app had simply ignored it.
  const unadopted = useMemo(() => unadoptedMods(profile, installed), [profile, installed]);
  const conflicts = useMemo(() => detectConflicts(profile), [profile]);
  const conflictCountByMod = useMemo(() => buildConflictCounts(conflicts), [conflicts]);

  const {
    data: localMods,
    error: localModsError,
    isLoading: localModsLoading,
  } = useQuery({
    queryKey: ['rsmm', 'list', activeProfileId],
    queryFn: listLocalMods,
    retry: false,
    staleTime: 5_000,
  });

  useEffect(() => {
    if (localMods) syncLocalMods(localMods);
  }, [localMods, syncLocalMods]);

  const filtered = useMemo(
    () =>
      filterLibraryRows(buildLibraryRows(profile, localModsState), {
        query,
        category,
        status,
        sort,
      }),
    [category, localModsState, profile, query, sort, status],
  );

  const grouped = useMemo(() => groupByCategory(filtered), [filtered]);

  const selectedRows = useMemo(
    () => filtered.filter((row) => selected.has(row.id)),
    [filtered, selected],
  );
  const selectedMissingDeps = useMemo(
    () => selectedRows.reduce((count, row) => count + row.missingDeps, 0),
    [selectedRows],
  );

  const missingDepCounts = useMemo(() => buildMissingDepCounts(filtered), [filtered]);

  const filterCount = countLibraryFilters({ category, status, query });
  const hasDirtyConfigs = dirtyConfigs.size > 0;
  const hasSelection = selected.size > 0;
  const markConfigDirty = useCallback((id: string, dirty: boolean) => {
    setDirtyConfigs((current) => {
      const next = new Set(current);
      if (dirty) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  useEffect(() => {
    if (!hasDirtyConfigs) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [hasDirtyConfigs]);

  useEffect(() => {
    setSelected((current) => {
      if (current.size === 0) return current;
      const visibleIds = new Set(filtered.map((row) => row.id));
      const next = new Set([...current].filter((id) => visibleIds.has(id)));
      return next.size === current.size ? current : next;
    });
  }, [filtered]);

  const changeView = async (next: ViewMode) => {
    if (view === 'config' && next !== 'config' && hasDirtyConfigs) {
      // NOT `window.confirm`: a Tauri webview can answer a native confirm
      // without ever showing it, which makes the control that raised it look
      // dead (see the note in components/config-button.tsx). Losing typed-in
      // config is exactly the prompt that must not be skippable.
      const ok = await dialog.confirm({
        title: t('Discard unsaved changes?'),
        body: t('You have unsaved config changes. Discard them?'),
        confirmLabel: t('Discard'),
        destructive: true,
      });
      if (!ok) return;
    }
    setView(next);
    // Keep the URL in step so a Configure link and the toolbar agree, and so
    // the view survives a reload.
    void navigate({ to: '/', search: next === 'cards' ? {} : { view: next }, replace: true });
  };

  const clearSelection = useCallback(() => setSelected(new Set()), []);
  const toggleSelected = useCallback((id: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);
  const selectAllVisible = useCallback(() => {
    setSelected(new Set(filtered.map((row) => row.id)));
  }, [filtered]);

  // Shared with the mod detail page so both screens honour the same
  // dependency prompts.
  const {
    enableMods: requestEnableMods,
    disableMods: requestDisableMods,
    toggle: handleToggle,
  } = useModToggle(clearSelection);

  const bulkEnable = useCallback(() => {
    void requestEnableMods([...selected]);
  }, [requestEnableMods, selected]);
  const bulkDisable = useCallback(() => {
    void requestDisableMods([...selected]);
  }, [requestDisableMods, selected]);
  const queryClient = useQueryClient();
  const refreshLocalMods = useCallback(async () => {
    const local = await listLocalMods();
    if (local) {
      syncLocalMods(local);
      queryClient.setQueryData(['rsmm', 'list', activeProfileId], local);
    }
  }, [syncLocalMods, queryClient, activeProfileId]);

  const removeLocalMod = useCallback(
    async (id: string) => {
      const result = await uninstallLocalMod(id);
      if (!result || !result.ok) {
        throw new Error(result?.error || t('Failed to uninstall {id}', { id }));
      }
      return result;
    },
    [t],
  );

  const uninstallModStore = useApp((s) => s.uninstallMod);
  /** Ids currently being uninstalled — buttons are disabled while non-empty. */
  const [uninstalling, setUninstalling] = useState<Set<string>>(new Set());

  const uninstall = useCallback(
    async (id: string) => {
      // Deleting a mod's folder has no undo, and on the list view this hangs
      // off an icon-only trash button in a dense row. Ask first.
      const mod = getMod(id);
      const ok = await dialog.confirm({
        title: t('Uninstall {name}?', { name: mod?.name ?? id }),
        body: t('This deletes the mod from disk. There is no undo.'),
        confirmLabel: t('Uninstall'),
        destructive: true,
      });
      if (!ok) return;

      // Card/list buttons call this fire-and-forget — catch here or a
      // sidecar failure becomes an unhandled rejection the user never sees.
      setUninstalling((cur) => new Set(cur).add(id));
      try {
        const result = await removeLocalMod(id);
        uninstallModStore(id);
        await refreshLocalMods();
        const warning = disableHookWarning(result);
        if (warning) toast.push(warning, 'error');
        else toast.push(t('Mod uninstalled.'), 'success');
      } catch (err) {
        console.error('[library] uninstall failed', err);
        toast.push(err instanceof Error ? err.message : String(err), 'error');
      } finally {
        setUninstalling((cur) => {
          const next = new Set(cur);
          next.delete(id);
          return next;
        });
      }
    },
    [dialog, refreshLocalMods, removeLocalMod, t, toast, uninstallModStore],
  );

  const bulkUninstall = useCallback(() => {
    void (async () => {
      const ids = [...selected];
      if (ids.length === 0) return;
      const ok = await dialog.confirm({
        title: t.n(ids.length, 'Uninstall {n} mod?', 'Uninstall {n} mods?'),
        body: t('This deletes them from disk. There is no undo.'),
        confirmLabel: t('Uninstall'),
        destructive: true,
      });
      if (!ok) return;

      setUninstalling(new Set(ids));
      const warnings: string[] = [];
      const failures: string[] = [];
      let done = 0;
      // One `try` PER MOD. Wrapping the whole loop meant the first failure
      // left every remaining mod neither uninstalled nor reported, skipped
      // `clearSelection`, and showed a single error for an N-item operation.
      for (const id of ids) {
        try {
          const warning = disableHookWarning(await removeLocalMod(id));
          if (warning) warnings.push(warning);
          uninstallModStore(id);
          done += 1;
        } catch (err) {
          failures.push(
            `${getMod(id)?.name ?? id}: ${err instanceof Error ? err.message : String(err)}`,
          );
        }
      }
      await refreshLocalMods();
      clearSelection();
      setUninstalling(new Set());
      if (failures.length) {
        toast.push(
          `${t('{done} of {total} uninstalled.', { done, total: ids.length })} ${failures.join(' ')}`,
          'error',
        );
      } else if (warnings.length) {
        toast.push(warnings.join(' '), 'error');
      } else {
        toast.push(t('Selected mods uninstalled.'), 'success');
      }
    })();
  }, [
    clearSelection,
    dialog,
    refreshLocalMods,
    removeLocalMod,
    selected,
    t,
    toast,
    uninstallModStore,
  ]);

  if (installed.length === 0) {
    return (
      <EmptyState
        title={t('An empty grimoire')}
        body={t('No mods installed yet. Browse the index to add your first.')}
        action={
          <Link to="/browse" className="btn-grim" data-variant="primary">
            {t('Browse mods')}
          </Link>
        }
      />
    );
  }

  // Mods exist on disk but the active profile hasn't opted any of them in
  // yet (a fresh profile, or a mod folder copied in by hand). The Library is
  // profile-scoped, but hiding disk-only mods entirely made a hand-dropped
  // mod look like it was ignored by the app — so offer to adopt them here
  // instead of sending the user to /browse to find something already local.
  if (profile.loadOrder.length === 0) {
    return (
      <div className="space-y-6">
        <SetupBanner />
        <EmptyState
          title={t('“{name}” has no mods yet', { name: profile.name })}
          body={
            unadopted.length === 0
              ? t('No mods found on disk yet. Browse the index to add your first.')
              : t.n(
                  unadopted.length,
                  '1 mod is present on disk but not in this profile.',
                  '{n} mods are present on disk but not in this profile.',
                )
          }
          action={
            <div className="flex flex-wrap items-center justify-center gap-2">
              {unadopted.length > 0 && profile.id !== 'default' ? (
                <Button
                  type="button"
                  variant="primary"
                  onClick={() => {
                    adoptMods(unadopted);
                    toast.push(
                      t.n(
                        unadopted.length,
                        'Added 1 mod from disk to this profile',
                        'Added {n} mods from disk to this profile',
                      ),
                      'success',
                    );
                  }}
                >
                  {t('Add {n} from disk', { n: unadopted.length })}
                </Button>
              ) : null}
              <Link to="/browse" className="btn-grim" data-variant="default">
                {t('Browse mods')}
              </Link>
            </div>
          }
        />
      </div>
    );
  }

  return (
    // pb-24 is permanent, not conditional: the bulk-action bar below is a
    // fixed overlay so selecting a mod never pushes the list down, and the
    // padding keeps the last row reachable above it either way.
    <div className="space-y-6 pb-24">
      <SetupBanner />
      <UpdatesPanel />
      <SectionHeader
        title={t('Library')}
        subtitle={t.n(
          installed.length,
          '{n} mod in the local folder.',
          '{n} mods in the local folder.',
        )}
        right={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button
              type="button"
              onClick={() => void changeView('cards')}
              aria-pressed={view === 'cards'}
              variant={view === 'cards' ? 'gilt' : 'default'}
              size="sm"
              aria-label={t('Card view')}
            >
              <LayoutGrid className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              onClick={() => void changeView('list')}
              aria-pressed={view === 'list'}
              variant={view === 'list' ? 'gilt' : 'default'}
              size="sm"
              aria-label={t('List view')}
            >
              <List className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              onClick={() => void changeView('config')}
              aria-pressed={view === 'config'}
              variant={view === 'config' ? 'gilt' : 'default'}
              size="sm"
              aria-label={t('Config view')}
            >
              <SlidersHorizontal className="h-4 w-4" />
            </Button>
            <Link to="/browse" className="btn-grim ml-2" data-variant="primary">
              <Plus className="h-4 w-4" /> {t('Add mod')}
            </Link>
          </div>
        }
      />

      {/* Filters live in a rail beside the list, not in a bar above it. As a
          horizontal strip they wrapped onto two or three rows at narrow widths
          and pushed the mods themselves below the fold. */}
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_15rem]">
        {/* The rail stays FIRST in the DOM so that on a narrow window — where
            the grid collapses to one column — the filters are still above the
            list rather than stranded below it. `order` moves it to the right
            only once there are two columns to move it between. */}
        <aside className="space-y-5 lg:sticky lg:top-4 lg:order-2">
          <div className="relative">
            <Search
              className="-translate-y-1/2 absolute top-1/2 left-3 h-4 w-4 text-ash"
              aria-hidden
            />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('Search…')}
              aria-label={t('Search installed mods')}
              className="input-grim w-full pl-9"
            />
          </div>

          <div className="space-y-1">
            <FacetLabel icon={<SlidersHorizontal className="h-3.5 w-3.5" aria-hidden />}>
              {t('Status')}
            </FacetLabel>
            {(['all', 'enabled', 'disabled', 'outdated', 'missingDeps'] as const).map((item) => (
              <FacetRow key={item} active={status === item} onClick={() => setStatus(item)}>
                {t(STATUS_LABEL[item])}
              </FacetRow>
            ))}
          </div>

          {availableCategories.length > 1 ? (
            <div className="space-y-1">
              <FacetLabel>{t('Category')}</FacetLabel>
              {availableCategories.map((cat) => (
                <FacetRow key={cat} active={category === cat} onClick={() => setCategory(cat)}>
                  {cat === 'all' ? t('All') : t(CATEGORY_LABEL[cat])}
                </FacetRow>
              ))}
            </div>
          ) : null}

          <div className="space-y-2">
            <FacetLabel icon={<ArrowUpDown className="h-3.5 w-3.5" aria-hidden />}>
              {t('Sort')}
            </FacetLabel>
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as LibrarySort)}
              className="select-grim w-full py-1.5 text-sm"
              aria-label={t('Sort mods')}
            >
              <option value="load-order">{t('Load order')}</option>
              <option value="name">{t('Name')}</option>
              <option value="author">{t('Author')}</option>
              <option value="version">{t('Version')}</option>
            </select>
          </div>

          {/* Always mounted, disabled when idle — mounting it on the first
              filter click re-flowed the rail under the cursor. */}
          <Button
            type="button"
            onClick={() => {
              setQuery('');
              setCategory('all');
              setStatus('all');
            }}
            disabled={filterCount === 0}
            variant="default"
            size="sm"
            className="w-full disabled:cursor-default disabled:opacity-40"
          >
            <X className="h-4 w-4" /> {t('Clear filters')}
          </Button>
        </aside>

        <div className="min-w-0 space-y-6 lg:order-1">
          {localModsError ? (
            <div className="ember-banner flex items-center gap-3 px-4 py-3">
              <AlertTriangle className="h-4 w-4 text-crimson shrink-0" />
              <span className="font-serif-italic text-base">
                {t('Couldn’t reach rsmm CLI. Showing cached library only.')}
              </span>
              <CopyButton value={(localModsError as Error).message} />
            </div>
          ) : null}

          {unadopted.length > 0 ? (
            <div className="ember-banner flex flex-wrap items-center justify-between gap-3 px-4 py-3">
              <span className="font-serif-italic text-base">
                {t.n(
                  unadopted.length,
                  '1 mod is on disk but not in this profile.',
                  '{n} mods are on disk but not in this profile.',
                )}
              </span>
              <Button
                type="button"
                size="sm"
                variant="primary"
                onClick={() => {
                  adoptMods(unadopted);
                  toast.push(
                    t.n(
                      unadopted.length,
                      'Added 1 mod from disk to this profile',
                      'Added {n} mods from disk to this profile',
                    ),
                    'success',
                  );
                }}
              >
                {t('Add to profile')}
              </Button>
            </div>
          ) : null}

          {/* Mirrors a real category section — heading, fleuron, then cards at the
          same min height in the same grid — so the swap to loaded content is a
          fade in place rather than the page jumping to a new geometry. */}
          {localModsLoading && Object.keys(localModsState).length === 0 ? (
            <section className="space-y-3 animate-pulse" aria-busy="true">
              <div className="h-6 w-56 rounded bg-oxblood/20" />
              <Fleuron />
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div
                    // biome-ignore lint/suspicious/noArrayIndexKey: fixed loading placeholders
                    key={i}
                    className="min-h-[15rem] rounded border border-border bg-pitch/40"
                  />
                ))}
              </div>
            </section>
          ) : null}

          {conflicts.length > 0 ? (
            <Link
              to="/conflicts"
              className="ember-banner flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-4 py-3"
            >
              <span className="flex items-center gap-3">
                <AlertTriangle className="h-4 w-4 text-crimson" />
                <span className="font-serif-italic text-base">
                  {t.n(
                    conflicts.length,
                    '{n} conflict between enabled mods.',
                    '{n} conflicts between enabled mods.',
                  )}
                </span>
              </span>
              <span className="font-mono text-ash">{t('Resolve →')}</span>
            </Link>
          ) : null}

          {grouped.map(([category, items]) => (
            <section key={category} className="space-y-3">
              <h3 className="font-fraktur text-xl text-parchment">{t(CATEGORY_LABEL[category])}</h3>
              <Fleuron />
              {view === 'cards' ? (
                <CardGrid
                  items={items}
                  profile={profile}
                  onOpen={(slug) => navigate({ to: '/mod/$slug', params: { slug } })}
                  onToggle={handleToggle}
                  onUninstall={uninstall}
                  uninstalling={uninstalling}
                  selected={selected}
                  onSelect={toggleSelected}
                  conflictCounts={conflictCountByMod}
                  missingDeps={missingDepCounts}
                  onEnableDependency={(depId) => void requestEnableMods([depId])}
                />
              ) : view === 'list' ? (
                <ListView
                  items={items}
                  profile={profile}
                  onToggle={handleToggle}
                  onUninstall={uninstall}
                  uninstalling={uninstalling}
                  onReorder={reorderMod}
                  selected={selected}
                  onSelect={toggleSelected}
                  conflictCounts={conflictCountByMod}
                  missingDeps={missingDepCounts}
                  onEnableDependency={(depId) => void requestEnableMods([depId])}
                />
              ) : (
                <div className="space-y-4">
                  {/* Only configurable mods appear here. Rendering a full "declares
                  no editable config fields" panel for every other mod buried
                  the two that had settings under eighteen that did not. */}
                  {items.filter(({ id }) => getMod(id)?.hasConfig).length === 0 ? (
                    <p className="font-mono text-ash">
                      {t('No mod in this section declares config fields.')}
                    </p>
                  ) : null}
                  {items.map(({ id }) => {
                    const mod = getMod(id);
                    if (!mod?.hasConfig) return null;
                    return (
                      <div key={id} id={configAnchorId(id)}>
                        <ModConfigPanel
                          modId={id}
                          modName={mod.name}
                          enabled={isEnabledIn(profile, id)}
                          onToggleEnabled={() => handleToggle(id)}
                          onDirtyChange={markConfigDirty}
                        />
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          ))}

          {view === 'config' && hasDirtyConfigs ? (
            <div className="ember-banner flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-4 py-3">
              <span className="font-serif-italic text-base">
                {t.n(
                  dirtyConfigs.size,
                  '{n} config panel has unsaved changes.',
                  '{n} config panels have unsaved changes.',
                )}
              </span>
              <span className="font-mono text-ash">{t('Save or reset before leaving.')}</span>
            </div>
          ) : null}

          <div className="font-mono pt-6 text-center text-ash">
            <div className="flex justify-center">
              <StatPill value={installed.length} label={t('in folder')} />
              <StatPill value={enabledCount} label={t('enabled in profile')} className="ml-2" />
            </div>
          </div>

          {!localModsLoading && filtered.length === 0 ? (
            <EmptyState
              title={t('No mods match those filters')}
              body={t(
                'Try a broader search or clear one of the filters to show more installed mods.',
              )}
              action={
                <Button
                  type="button"
                  onClick={() => {
                    setQuery('');
                    setCategory('all');
                    setStatus('all');
                  }}
                  variant="primary"
                >
                  {t('Reset filters')}
                </Button>
              }
            />
          ) : null}
        </div>
      </div>

      {hasSelection ? (
        <Panel className="fixed inset-x-0 bottom-0 z-40 flex flex-wrap items-center justify-between gap-3 rounded-none border-x-0 border-b-0">
          <div className="min-w-0">
            <h3 className="font-fraktur text-lg text-parchment">
              {t('{n} selected', { n: selected.size })}
            </h3>
            <p className="font-serif-italic text-sm text-ash">
              {t('Bulk actions apply to the active profile.')}
              {selectedMissingDeps > 0
                ? ` ${t.n(
                    selectedMissingDeps,
                    '{n} missing dependency across the selection.',
                    '{n} missing dependencies across the selection.',
                  )}`
                : ''}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" size="sm" variant="primary" onClick={bulkEnable}>
              {t('Enable selected')}
            </Button>
            <Button type="button" size="sm" onClick={bulkDisable}>
              {t('Disable selected')}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="danger"
              onClick={bulkUninstall}
              disabled={uninstalling.size > 0}
            >
              {uninstalling.size > 0 ? t('Uninstalling…') : t('Uninstall selected')}
            </Button>
            <Button type="button" size="sm" onClick={selectAllVisible}>
              {t('Select filtered')}
            </Button>
            <Button type="button" size="sm" onClick={clearSelection}>
              {t('Clear')}
            </Button>
          </div>
        </Panel>
      ) : null}
    </div>
  );
}

interface RowProps {
  items: { id: string; orderIdx: number }[];
  profile: ReturnType<typeof activeProfile>;
  onOpen?: (slug: string) => void;
  onToggle: (id: string) => void;
  onUninstall: (id: string) => void;
  /** Ids whose uninstall is in flight — their controls are disabled so a slow
   *  sidecar cannot be handed the same delete twice. */
  uninstalling: Set<string>;
  onReorder?: (id: string, toIndex: number) => void;
  selected: Set<string>;
  onSelect: (id: string) => void;
  conflictCounts: Map<string, number>;
  missingDeps: Map<string, number>;
  onEnableDependency: (id: string) => void;
}

function CardGrid({
  items,
  profile,
  onOpen,
  onToggle,
  onUninstall,
  uninstalling,
  selected,
  onSelect,
  conflictCounts,
  missingDeps,
  onEnableDependency,
}: RowProps) {
  const t = useT();
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      {items.map(({ id, orderIdx }) => {
        const mod = getMod(id);
        if (!mod) return null;
        const enabled = isEnabledIn(profile, id);
        const outdated = mod.version !== mod.latestVersion;
        const selectedHere = selected.has(id);
        const depCount = missingDeps.get(id) ?? 0;
        const conflictCount = conflictCounts.get(id) ?? 0;
        return (
          <div
            key={id}
            // Card click SELECTS, matching the list. It used to navigate to
            // the store page, so a mis-aimed click left the library entirely.
            onClick={(e) => {
              const el = e.target as HTMLElement;
              if (el.closest('button, a, input, textarea, select, [role="switch"]')) return;
              e.preventDefault();
              onSelect(id);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onSelect(id);
              }
            }}
            // The card itself is the control; see the list row for why.
            // biome-ignore lint/a11y/useSemanticElements: composite card, see above
            role="checkbox"
            aria-checked={selectedHere}
            tabIndex={0}
            className={[
              'grimoire-card flex h-full cursor-pointer flex-col gap-3 p-5',
              'transition-colors duration-150',
              selectedHere ? 'border-gilt/60 bg-gilt/10' : 'hover:border-gilt/40',
            ].join(' ')}
          >
            <header className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <span className="font-serif break-words text-xl leading-tight text-parchment">
                  {mod.name}
                </span>
                <p className="font-data mt-1 text-ash">
                  {mod.author} · v{mod.version}
                </p>
              </div>
              <button
                type="button"
                onClick={() => onOpen?.(mod.slug)}
                className="btn-grim shrink-0 px-2 py-1.5"
                title={t("Open this mod's store page")}
                aria-label={t('Open the store page for {name}', { name: mod.name })}
              >
                <ExternalLink className="h-4 w-4" />
              </button>
            </header>
            {/* Clamped rather than free-length: an eleven-line summary next to a
                two-line one left half a card of dead space and knocked every
                row of the grid out of alignment. The full text is on the
                store page. */}
            <p className="line-clamp-3 text-sm leading-snug text-smoke">{mod.summary}</p>
            {/* Status tags mount and unmount as a toggle changes conflict and
                dependency counts. They get their own reserved-height row so
                that reflow can never reach the controls below. */}
            <div className="flex min-h-[1.75rem] flex-wrap items-center gap-2">
              {outdated ? (
                <MonoTag tone="gilt">
                  {t('Update {version}', { version: mod.latestVersion })}
                </MonoTag>
              ) : null}
              {depCount > 0 ? (
                <MonoTag tone="crimson">
                  {t.n(depCount, '{n} missing dep', '{n} missing deps')}
                </MonoTag>
              ) : null}
              {conflictCount > 0 ? (
                <MonoTag tone="crimson">
                  {t.n(conflictCount, '{n} conflict', '{n} conflicts')}
                </MonoTag>
              ) : null}
              <MonoTag tone="default">{t(CATEGORY_LABEL[mod.category])}</MonoTag>
              <StatPill value={`#${orderIdx + 1}`} label={t('load')} className="tracking-normal" />
            </div>
            <DependencyStrip mod={mod} profile={profile} onEnableDependency={onEnableDependency} />
            {/* mt-auto pins the actions to the card's bottom edge, so every
                card in a grid row puts the switch and uninstall button at the
                same y — and a tag appearing above never moves them. */}
            {/* flex-wrap because the row's contents are conditional: a mod with
                both a config schema and an overlay carries four controls, which
                overflowed the card at a narrow grid width. */}
            <div className="mt-auto flex flex-wrap items-center gap-2 pt-1">
              <InkSwitch
                on={enabled}
                onClick={() => onToggle(id)}
                label={
                  enabled
                    ? t('Disable {name}', { name: mod.name })
                    : t('Enable {name}', { name: mod.name })
                }
              />
              {/* ml-auto lives on the GROUP, not on the first button: the
                  overlay button renders only for a mod that declares an
                  [overlay] block, and hanging the alignment off it would
                  left-align uninstall on every other card. */}
              <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
                <ConfigButton
                  modId={id}
                  modName={mod.name}
                  hasConfig={mod.hasConfig}
                  enabled={enabled}
                  onToggleEnabled={() => onToggle(id)}
                />
                <OverlayButton modId={id} />
                <Button
                  type="button"
                  onClick={() => onUninstall(id)}
                  disabled={uninstalling.has(id)}
                  variant="danger"
                  size="sm"
                  className="px-2"
                  title={t('Uninstall this mod')}
                  aria-label={t('Uninstall {name}', { name: mod.name })}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ListView({
  items,
  profile,
  onToggle,
  onReorder,
  onUninstall,
  uninstalling,
  selected,
  onSelect,
  conflictCounts,
  missingDeps,
  onOpen,
}: RowProps) {
  const t = useT();
  const [dragId, setDragId] = useState<string | null>(null);
  const reorderable = Boolean(onReorder);

  return (
    <ul className="grimoire-card divide-y divide-border">
      {items.map(({ id, orderIdx }) => {
        const mod = getMod(id);
        if (!mod) return null;
        const enabled = isEnabledIn(profile, id);
        const isDragging = dragId === id;
        const isSelected = selected.has(id);
        const flags =
          (missingDeps.get(id) ?? 0) > 0
            ? t('missing deps')
            : (conflictCounts.get(id) ?? 0) > 0
              ? t('conflict')
              : null;
        return (
          <li
            key={id}
            draggable={reorderable}
            onDragStart={
              reorderable
                ? (e) => {
                    setDragId(id);
                    e.dataTransfer.effectAllowed = 'move';
                  }
                : undefined
            }
            onDragEnd={reorderable ? () => setDragId(null) : undefined}
            onDragOver={
              reorderable
                ? (e) => {
                    e.preventDefault();
                    e.dataTransfer.dropEffect = 'move';
                  }
                : undefined
            }
            onDrop={
              reorderable
                ? (e) => {
                    e.preventDefault();
                    if (dragId && onReorder) onReorder(dragId, orderIdx);
                    setDragId(null);
                  }
                : undefined
            }
            // Clicking the row SELECTS it. It used to open the mod's store
            // page, so a mis-aimed click navigated away from the library; and
            // selection needed its own checkbox sitting right beside the
            // enable switch, two lookalike controls doing opposite things.
            // Now the row is the checkbox and the switch is the only toggle.
            onClick={(e) => {
              if ((e.target as HTMLElement).closest('button, a, input, [role="switch"]')) return;
              onSelect(id);
            }}
            // The row itself is the control: an <input type="checkbox"> cannot
            // wrap a switch, tags and four buttons — which is exactly why the
            // separate checkbox column went away.
            // biome-ignore lint/a11y/useSemanticElements: composite row, see above
            // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: same
            role="checkbox"
            aria-checked={isSelected}
            tabIndex={0}
            onKeyDown={(e) => {
              // Alt+Arrow reorders. Load order is the entire reason the list
              // view exists, and it was reachable only by dragging with a
              // mouse — the grip is decorative and the row's key handler did
              // nothing but select. Alt, so plain arrows keep scrolling.
              if (reorderable && e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
                e.preventDefault();
                const to = orderIdx + (e.key === 'ArrowUp' ? -1 : 1);
                if (to < 0) return;
                onReorder?.(id, to);
                // Keep the moved row under the cursor: React re-renders the
                // list in the new order, and focus would otherwise stay on
                // whatever now occupies this position.
                const li = e.currentTarget;
                requestAnimationFrame(() => {
                  const moved = li.parentElement?.querySelector<HTMLElement>(
                    `[data-mod-id="${CSS.escape(id)}"]`,
                  );
                  moved?.focus();
                });
                return;
              }
              if (e.key !== 'Enter' && e.key !== ' ') return;
              e.preventDefault();
              onSelect(id);
            }}
            data-mod-id={id}
            aria-keyshortcuts={reorderable ? 'Alt+ArrowUp Alt+ArrowDown' : undefined}
            className={[
              'flex items-center gap-3 px-3 py-1.5 text-sm transition-colors',
              isSelected ? 'bg-gilt/15' : 'hover:bg-oxblood/10',
              isDragging ? 'opacity-40' : '',
              dragId && !isDragging ? 'opacity-60' : '',
            ].join(' ')}
          >
            {reorderable ? (
              <GripVertical
                className="h-3.5 w-3.5 shrink-0 cursor-grab text-ash"
                aria-hidden="true"
              />
            ) : null}
            <span className="font-data w-7 shrink-0 text-right text-xs text-ash">
              {orderIdx + 1}
            </span>
            <InkSwitch
              on={enabled}
              onClick={() => onToggle(id)}
              label={
                enabled
                  ? t('Disable {name}', { name: mod.name })
                  : t('Enable {name}', { name: mod.name })
              }
            />
            {/* One line. The old row stacked name, author, a reserved tag
                strip and a dependency strip — four blocks tall, so a dozen
                mods no longer fit on screen. */}
            <span className="min-w-0 flex-1 truncate text-parchment" title={mod.name}>
              {mod.name}
            </span>
            <span className="font-data hidden shrink-0 text-xs text-ash sm:inline">
              {mod.author} · v{mod.version}
            </span>
            {mod.version !== mod.latestVersion ? (
              <MonoTag tone="gilt">→ {mod.latestVersion}</MonoTag>
            ) : null}
            {flags ? <MonoTag tone="crimson">{flags}</MonoTag> : null}
            <ConfigButton
              modId={id}
              modName={mod.name}
              hasConfig={mod.hasConfig}
              enabled={enabled}
              onToggleEnabled={() => onToggle(id)}
            />
            <OverlayButton modId={id} />
            <button
              type="button"
              onClick={() => onOpen?.(mod.slug)}
              className="btn-grim shrink-0 px-2 py-1.5"
              title={t("Open this mod's store page")}
              aria-label={t('Open the store page for {name}', { name: mod.name })}
            >
              <ExternalLink className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => onUninstall(id)}
              disabled={uninstalling.has(id)}
              className="btn-grim shrink-0 px-2 py-1.5"
              data-variant="danger"
              title={t('Uninstall this mod')}
              aria-label={t('Uninstall {name}', { name: mod.name })}
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function DependencyStrip({
  mod,
  profile,
  onEnableDependency,
}: {
  mod: NonNullable<ReturnType<typeof getMod>>;
  profile: ReturnType<typeof activeProfile>;
  onEnableDependency: (id: string) => void;
}) {
  const t = useT();
  if (mod.dependencies.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="font-mono text-[11px] tracking-[0.18em] text-ash">{t('Requires')}</span>
      {mod.dependencies.map((depId) => {
        const dep = getMod(depId);
        const enabled = dep ? isEnabledIn(profile, depId) : false;
        if (!dep) {
          return (
            <MonoTag key={depId} tone="crimson">
              {t('{id} missing', { id: depId })}
            </MonoTag>
          );
        }
        return enabled ? (
          <Link
            key={depId}
            to="/mod/$slug"
            params={{ slug: dep.slug }}
            className="inline-flex items-center gap-1 rounded-full border border-gilt/40 bg-gilt/10 px-2 py-1 font-mono text-[11px] text-gilt hover:border-gilt/70 hover:text-parchment"
          >
            {dep.name}
          </Link>
        ) : (
          <button
            key={depId}
            type="button"
            onClick={() => onEnableDependency(depId)}
            className="inline-flex items-center gap-1 rounded-full border border-border bg-pitch/55 px-2 py-1 font-mono text-[11px] text-ash hover:border-gilt/50 hover:text-parchment"
          >
            {dep.name}
          </button>
        );
      })}
    </div>
  );
}
