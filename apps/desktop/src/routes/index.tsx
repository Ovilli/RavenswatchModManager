import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router';
import {
  AlertTriangle,
  ArrowUpDown,
  GripVertical,
  LayoutGrid,
  List,
  Plus,
  Search,
  SlidersHorizontal,
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
import { ModConfigPanel } from '../components/mod-config-panel';
import { OverlayButton } from '../components/overlay-button';
import { SetupBanner } from '../components/setup-banner';
import { useDialog } from '../components/toast';
import { useToast } from '../components/toast';
import { UpdatesPanel } from '../components/updates-panel';
import {
  buildEnablePlan,
  compareVersions,
  findBlockingDependents,
  getMissingDependencyCount,
} from '../lib/library-deps';
import type { ModCategory } from '../lib/mod-types';
import { listLocalMods, uninstallLocalMod } from '../lib/rsmm';
import {
  activeProfile,
  detectConflicts,
  getMod,
  isEnabledIn,
  unadoptedMods,
  useApp,
} from '../store';

export const Route = createFileRoute('/')({
  component: LibraryPage,
});

type ViewMode = 'cards' | 'list' | 'config';
type LibraryStatusFilter = 'all' | 'enabled' | 'disabled' | 'outdated' | 'missingDeps';
type LibrarySort = 'load-order' | 'name' | 'author' | 'version';

const CATEGORY_LABEL: Record<ModCategory, string> = {
  gameplay: 'Gameplay',
  balance: 'Balance',
  cosmetic: 'Cosmetic',
  qol: 'Quality of life',
  audio: 'Audio',
  difficulty: 'Difficulty',
  speedrun: 'Speedrun',
  utility: 'Utility',
};

function LibraryPage() {
  const navigate = useNavigate();
  const dialog = useDialog();
  const toast = useToast();
  const profile = useApp(activeProfile);
  const toggleMod = useApp((s) => s.toggleMod);
  const reorderMod = useApp((s) => s.reorderMod);
  const installed = useApp((s) => s.installed);
  const syncLocalMods = useApp((s) => s.syncLocalMods);
  const adoptMods = useApp((s) => s.adoptMods);
  const activeProfileId = useApp((s) => s.activeProfileId);
  const [view, setView] = useState<ViewMode>('cards');
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
  const conflictCountByMod = useMemo(() => {
    const counts = new Map<string, number>();
    for (const conflict of conflicts) {
      for (const modId of conflict.modIds) {
        counts.set(modId, (counts.get(modId) ?? 0) + 1);
      }
    }
    return counts;
  }, [conflicts]);

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

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const rows = profile.loadOrder
      .map((id, orderIdx) => {
        const mod = localModsState[id];
        if (!mod) return null;
        const enabled = isEnabledIn(profile, id);
        const outdated = mod.version !== mod.latestVersion;
        const missingDeps = getMissingDependencyCount(mod, profile);
        return { id, orderIdx, mod, enabled, outdated, missingDeps };
      })
      .filter((row): row is NonNullable<typeof row> => {
        if (!row) return false;
        if (category !== 'all' && row.mod.category !== category) return false;
        if (status === 'enabled' && !row.enabled) return false;
        if (status === 'disabled' && row.enabled) return false;
        if (status === 'outdated' && !row.outdated) return false;
        if (status === 'missingDeps' && row.missingDeps === 0) return false;
        if (!needle) return true;
        return (
          row.mod.name.toLowerCase().includes(needle) ||
          row.mod.author.toLowerCase().includes(needle) ||
          row.mod.summary.toLowerCase().includes(needle) ||
          row.mod.slug.toLowerCase().includes(needle) ||
          row.mod.version.toLowerCase().includes(needle) ||
          row.mod.category.toLowerCase().includes(needle) ||
          row.mod.tags.some((tag) => tag.toLowerCase().includes(needle))
        );
      });
    return [...rows].sort((a, b) => {
      if (sort === 'load-order') return a.orderIdx - b.orderIdx;
      if (sort === 'name') return a.mod.name.localeCompare(b.mod.name);
      if (sort === 'author') return a.mod.author.localeCompare(b.mod.author);
      if (sort === 'version') return compareVersions(b.mod.version, a.mod.version);
      return a.orderIdx - b.orderIdx;
    });
  }, [category, localModsState, profile, query, sort, status]);

  const grouped = useMemo(() => {
    const groups = new Map<ModCategory, { id: string; orderIdx: number }[]>();
    for (const { id, orderIdx, mod } of filtered) {
      const list = groups.get(mod.category) ?? [];
      list.push({ id, orderIdx });
      groups.set(mod.category, list);
    }
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [filtered]);

  const selectedRows = useMemo(
    () => filtered.filter((row) => selected.has(row.id)),
    [filtered, selected],
  );
  const selectedMissingDeps = useMemo(
    () => selectedRows.reduce((count, row) => count + row.missingDeps, 0),
    [selectedRows],
  );

  const missingDepCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of filtered) {
      if (row.missingDeps > 0) counts.set(row.id, row.missingDeps);
    }
    return counts;
  }, [filtered]);

  const filterCount = [category !== 'all', status !== 'all', query.trim().length > 0].filter(
    Boolean,
  ).length;
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

  const changeView = (next: ViewMode) => {
    if (view === 'config' && next !== 'config' && hasDirtyConfigs) {
      const ok = window.confirm('You have unsaved config changes. Discard them?');
      if (!ok) return;
    }
    setView(next);
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

  const requestEnableMods = useCallback(
    async (ids: string[]) => {
      const plan = buildEnablePlan(ids);
      if (plan.missing.length > 0) {
        const ok = await dialog.confirm({
          title: 'Missing dependencies',
          body: `These dependencies are not installed: ${plan.missing.join(', ')}. Enable the selected mods anyway?`,
          confirmLabel: 'Enable anyway',
          destructive: true,
        });
        if (!ok) return;
      }
      for (const id of plan.order) {
        if (!isEnabledIn(profile, id)) toggleMod(id);
      }
      clearSelection();
    },
    [clearSelection, dialog, profile, toggleMod],
  );

  const requestDisableMods = useCallback(
    async (ids: string[]) => {
      const blocked = findBlockingDependents(ids, profile);
      if (blocked.length > 0) {
        const body = blocked
          .map(([target, dependents]) => `${target}: ${dependents.join(', ')}`)
          .join('\n');
        const ok = await dialog.confirm({
          title: 'Broken dependency chain',
          body: `Disabling these mods will leave others missing dependencies:\n${body}\nContinue?`,
          confirmLabel: 'Disable anyway',
          destructive: true,
        });
        if (!ok) return;
      }
      for (const id of ids) {
        if (isEnabledIn(profile, id)) toggleMod(id);
      }
      clearSelection();
    },
    [clearSelection, dialog, profile, toggleMod],
  );
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

  const removeLocalMod = useCallback(async (id: string) => {
    const result = await uninstallLocalMod(id);
    if (!result || !result.ok) {
      throw new Error(result?.error || `Failed to uninstall ${id}`);
    }
  }, []);

  const uninstallModStore = useApp((s) => s.uninstallMod);
  const uninstall = useCallback(
    async (id: string) => {
      // Card/list buttons call this fire-and-forget — catch here or a
      // sidecar failure becomes an unhandled rejection the user never sees.
      try {
        await removeLocalMod(id);
        uninstallModStore(id);
        await refreshLocalMods();
        toast.push('Mod uninstalled.', 'success');
      } catch (err) {
        console.error('[library] uninstall failed', err);
        toast.push(err instanceof Error ? err.message : String(err), 'error');
      }
    },
    [refreshLocalMods, removeLocalMod, toast, uninstallModStore],
  );

  const bulkUninstall = useCallback(() => {
    void (async () => {
      try {
        for (const id of selected) {
          await removeLocalMod(id);
          uninstallModStore(id);
        }
        await refreshLocalMods();
        clearSelection();
        toast.push('Selected mods uninstalled.', 'success');
      } catch (err) {
        toast.push(err instanceof Error ? err.message : String(err), 'error');
      }
    })();
  }, [clearSelection, refreshLocalMods, removeLocalMod, selected, toast, uninstallModStore]);

  const handleToggle = useCallback(
    (id: string) => {
      if (isEnabledIn(profile, id)) void requestDisableMods([id]);
      else void requestEnableMods([id]);
    },
    [profile, requestDisableMods, requestEnableMods],
  );

  if (installed.length === 0) {
    return (
      <EmptyState
        title="An empty grimoire"
        body="No mods installed yet. Browse the index to add your first."
        action={
          <Link to="/browse" className="btn-grim" data-variant="primary">
            Browse mods
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
          title={`“${profile.name}” has no mods yet`}
          body={
            unadopted.length === 0
              ? 'No mods found on disk yet. Browse the index to add your first.'
              : unadopted.length === 1
                ? '1 mod is present on disk but not in this profile.'
                : `${unadopted.length} mods are present on disk but not in this profile.`
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
                      unadopted.length === 1
                        ? 'Added 1 mod from disk to this profile'
                        : `Added ${unadopted.length} mods from disk to this profile`,
                      'success',
                    );
                  }}
                >
                  Add {unadopted.length} from disk
                </Button>
              ) : null}
              <Link to="/browse" className="btn-grim" data-variant="default">
                Browse mods
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
        title="Library"
        subtitle={`${installed.length} mods in the local folder.`}
        right={
          <div className="flex items-center gap-2">
            <Button
              type="button"
              onClick={() => changeView('cards')}
              aria-pressed={view === 'cards'}
              variant={view === 'cards' ? 'gilt' : 'default'}
              size="sm"
              aria-label="Card view"
            >
              <LayoutGrid className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              onClick={() => changeView('list')}
              aria-pressed={view === 'list'}
              variant={view === 'list' ? 'gilt' : 'default'}
              size="sm"
              aria-label="List view"
            >
              <List className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              onClick={() => changeView('config')}
              aria-pressed={view === 'config'}
              variant={view === 'config' ? 'gilt' : 'default'}
              size="sm"
              aria-label="Config view"
            >
              <SlidersHorizontal className="h-4 w-4" />
            </Button>
            <Link to="/browse" className="btn-grim ml-2" data-variant="primary">
              <Plus className="h-4 w-4" /> Add mod
            </Link>
          </div>
        }
      />

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[260px] flex-1">
          <Search
            className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ash"
            aria-hidden
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search installed mods…"
            aria-label="Search installed mods"
            className="input-grim pl-9"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-2 font-mono text-xs uppercase tracking-[0.22em] text-ash">
            <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden /> Filters
          </span>
          {(['all', 'enabled', 'disabled', 'outdated', 'missingDeps'] as const).map((item) => (
            <Button
              key={item}
              type="button"
              onClick={() => setStatus(item)}
              aria-pressed={status === item}
              variant={status === item ? 'gilt' : 'default'}
              size="sm"
            >
              {item}
            </Button>
          ))}
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as LibrarySort)}
            className="select-grim font-mono border border-border bg-pitch/60 px-3 py-2 text-xs text-parchment focus:border-gilt/60 focus:outline-none"
            aria-label="Sort mods"
          >
            <option value="load-order">Load order</option>
            <option value="name">Name</option>
            <option value="author">Author</option>
            <option value="version">Version</option>
          </select>
          <ArrowUpDown className="h-4 w-4 text-ash" aria-hidden />
        </div>
      </div>

      {hasSelection ? (
        <Panel className="fixed inset-x-0 bottom-0 z-40 flex flex-wrap items-center justify-between gap-3 rounded-none border-x-0 border-b-0">
          <div>
            <h3 className="font-fraktur text-lg text-parchment">{selected.size} selected</h3>
            <p className="font-serif-italic text-sm text-ash">
              Bulk actions apply to the active profile.
              {selectedMissingDeps > 0
                ? ` ${selectedMissingDeps} missing dependencies across the selection.`
                : ''}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" size="sm" variant="primary" onClick={bulkEnable}>
              Enable selected
            </Button>
            <Button type="button" size="sm" onClick={bulkDisable}>
              Disable selected
            </Button>
            <Button type="button" size="sm" variant="danger" onClick={bulkUninstall}>
              Uninstall selected
            </Button>
            <Button type="button" size="sm" onClick={selectAllVisible}>
              Select filtered
            </Button>
            <Button type="button" size="sm" onClick={clearSelection}>
              Clear
            </Button>
          </div>
        </Panel>
      ) : null}

      <div className="flex flex-wrap gap-1.5">
        {availableCategories.map((cat) => (
          <Button
            key={cat}
            type="button"
            onClick={() => setCategory(cat)}
            aria-pressed={category === cat}
            variant={category === cat ? 'danger' : 'default'}
            size="sm"
          >
            {cat === 'all' ? 'All' : CATEGORY_LABEL[cat]}
          </Button>
        ))}
        {/* Always mounted, disabled when idle — mounting it on the first
            filter click re-wrapped the chip row and moved every category
            button out from under the cursor. */}
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
          className="ml-auto disabled:cursor-default disabled:opacity-40"
        >
          <X className="h-4 w-4" /> Clear filters
        </Button>
      </div>

      {localModsError ? (
        <div className="ember-banner flex items-center gap-3 px-4 py-3">
          <AlertTriangle className="h-4 w-4 text-crimson shrink-0" />
          <span className="font-serif-italic text-base">
            Couldn’t reach rsmm CLI. Showing cached library only.
          </span>
          <CopyButton value={(localModsError as Error).message} />
        </div>
      ) : null}

      {unadopted.length > 0 ? (
        <div className="ember-banner flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <span className="font-serif-italic text-base">
            {unadopted.length === 1
              ? '1 mod is on disk but not in this profile.'
              : `${unadopted.length} mods are on disk but not in this profile.`}
          </span>
          <Button
            type="button"
            size="sm"
            variant="primary"
            onClick={() => {
              adoptMods(unadopted);
              toast.push(
                unadopted.length === 1
                  ? 'Added 1 mod from disk to this profile'
                  : `Added ${unadopted.length} mods from disk to this profile`,
                'success',
              );
            }}
          >
            Add to profile
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
        <Link to="/conflicts" className="ember-banner flex items-center justify-between px-4 py-3">
          <span className="flex items-center gap-3">
            <AlertTriangle className="h-4 w-4 text-crimson" />
            <span className="font-serif-italic text-base">
              {conflicts.length} {conflicts.length === 1 ? 'conflict' : 'conflicts'} between enabled
              mods.
            </span>
          </span>
          <span className="font-mono text-ash">Resolve →</span>
        </Link>
      ) : null}

      {grouped.map(([category, items]) => (
        <section key={category} className="space-y-3">
          <h3 className="font-fraktur text-xl text-parchment">{CATEGORY_LABEL[category]}</h3>
          <Fleuron />
          {view === 'cards' ? (
            <CardGrid
              items={items}
              profile={profile}
              onOpen={(slug) => navigate({ to: '/mod/$slug', params: { slug } })}
              onToggle={handleToggle}
              onUninstall={uninstall}
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
              onReorder={reorderMod}
              selected={selected}
              onSelect={toggleSelected}
              conflictCounts={conflictCountByMod}
              missingDeps={missingDepCounts}
              onEnableDependency={(depId) => void requestEnableMods([depId])}
            />
          ) : (
            <div className="space-y-4">
              {items.map(({ id }) => {
                const mod = getMod(id);
                if (!mod) return null;
                return (
                  <ModConfigPanel
                    key={id}
                    modId={id}
                    modName={mod.name}
                    enabled={isEnabledIn(profile, id)}
                    onToggleEnabled={() => handleToggle(id)}
                    onDirtyChange={markConfigDirty}
                  />
                );
              })}
            </div>
          )}
        </section>
      ))}

      {view === 'config' && hasDirtyConfigs ? (
        <div className="ember-banner flex items-center justify-between gap-3 px-4 py-3">
          <span className="font-serif-italic text-base">
            {dirtyConfigs.size} config panel{dirtyConfigs.size === 1 ? '' : 's'} have unsaved
            changes.
          </span>
          <span className="font-mono text-ash">Save or reset before leaving.</span>
        </div>
      ) : null}

      <div className="font-mono pt-6 text-center text-ash">
        <div className="flex justify-center">
          <StatPill value={installed.length} label="in folder" />
          <StatPill value={enabledCount} label="enabled in profile" className="ml-2" />
        </div>
      </div>

      {!localModsLoading && filtered.length === 0 ? (
        <EmptyState
          title="No mods match those filters"
          body="Try a broader search or clear one of the filters to show more installed mods."
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
              Reset filters
            </Button>
          }
        />
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
  selected,
  onSelect,
  conflictCounts,
  missingDeps,
  onEnableDependency,
}: RowProps) {
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
            onClick={(e) => {
              const el = e.target as HTMLElement;
              if (el.closest('button, a, input, textarea, select, [role="switch"]')) return;
              e.preventDefault();
              onOpen?.(mod.slug);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onOpen?.(mod.slug);
              }
            }}
            className="grimoire-card flex h-full min-h-[15rem] flex-col gap-3 p-5 transition-colors duration-150 hover:border-gilt/40 cursor-pointer"
          >
            <header className="flex items-start justify-between gap-3">
              <div>
                <Link
                  to="/mod/$slug"
                  params={{ slug: mod.slug }}
                  className="font-serif-italic text-xl leading-tight text-parchment hover:text-gilt"
                >
                  {mod.name}
                </Link>
                <p className="font-mono mt-1 text-ash">
                  {mod.author} · v{mod.version}
                </p>
              </div>
              <input
                type="checkbox"
                checked={selectedHere}
                onChange={() => onSelect(id)}
                className="mt-1 h-4 w-4 rounded border-border bg-pitch/60"
                aria-label={`Select ${mod.name}`}
              />
            </header>
            <p className="font-serif-italic text-sm leading-snug text-smoke">{mod.summary}</p>
            {/* Status tags mount and unmount as a toggle changes conflict and
                dependency counts. They get their own reserved-height row so
                that reflow can never reach the controls below. */}
            <div className="flex min-h-[1.75rem] flex-wrap items-center gap-2">
              {outdated ? <MonoTag tone="gilt">Update {mod.latestVersion}</MonoTag> : null}
              {depCount > 0 ? <MonoTag tone="crimson">{depCount} missing deps</MonoTag> : null}
              {conflictCount > 0 ? (
                <MonoTag tone="crimson">{conflictCount} conflicts</MonoTag>
              ) : null}
              <MonoTag tone="default">{mod.category}</MonoTag>
              <StatPill value={`#${orderIdx + 1}`} label="load" className="tracking-normal" />
            </div>
            <DependencyStrip mod={mod} profile={profile} onEnableDependency={onEnableDependency} />
            {/* mt-auto pins the actions to the card's bottom edge, so every
                card in a grid row puts the switch and uninstall button at the
                same y — and a tag appearing above never moves them. */}
            <div className="mt-auto flex items-center gap-2 pt-1">
              <InkSwitch
                on={enabled}
                onClick={() => onToggle(id)}
                label={`${enabled ? 'Disable' : 'Enable'} ${mod.name}`}
              />
              {/* ml-auto lives on the GROUP, not on the first button: the
                  overlay button renders only for a mod that declares an
                  [overlay] block, and hanging the alignment off it would
                  left-align uninstall on every other card. */}
              <div className="ml-auto flex items-center gap-2">
                <OverlayButton modId={id} />
                <Button type="button" onClick={() => onUninstall(id)} variant="danger" size="sm">
                  uninstall
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
  selected,
  onSelect,
  conflictCounts,
  missingDeps,
  onEnableDependency,
}: RowProps) {
  const [dragId, setDragId] = useState<string | null>(null);
  const reorderable = Boolean(onReorder);

  return (
    <ul className="grimoire-card divide-y divide-border">
      {items.map(({ id, orderIdx }) => {
        const mod = getMod(id);
        if (!mod) return null;
        const enabled = isEnabledIn(profile, id);
        const isDragging = dragId === id;
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
            className={`flex items-center gap-4 px-4 py-3 transition-opacity duration-150 ${
              isDragging ? 'opacity-40' : ''
            } ${dragId && !isDragging ? 'opacity-60' : ''} hover:bg-oxblood/10`}
          >
            {reorderable ? <GripVertical className="h-4 w-4 cursor-grab text-ash" /> : null}
            <input
              type="checkbox"
              checked={selected.has(id)}
              onChange={() => onSelect(id)}
              className="h-4 w-4 rounded border-border bg-pitch/60"
              aria-label={`Select ${mod.name}`}
            />
            <InkSwitch
              on={enabled}
              onClick={() => onToggle(id)}
              label={`${enabled ? 'Disable' : 'Enable'} ${mod.name}`}
            />
            <div className="flex-1">
              <Link
                to="/mod/$slug"
                params={{ slug: mod.slug }}
                className="font-serif-italic text-lg text-parchment hover:text-gilt"
              >
                {mod.name}
              </Link>
              <p className="font-mono text-ash">
                {mod.author} · v{mod.version}
                {mod.version !== mod.latestVersion ? (
                  <>
                    {' '}
                    · <span className="text-gilt">→ {mod.latestVersion}</span>
                  </>
                ) : null}
              </p>
              {/* Reserved height: these tags appear the moment a toggle
                  creates a conflict, and a 0px→20px row grew every row below
                  it out from under the pointer. */}
              <div className="mt-1 flex min-h-[1.25rem] flex-wrap gap-1.5">
                {(missingDeps.get(id) ?? 0) > 0 ? (
                  <MonoTag tone="crimson">missing deps</MonoTag>
                ) : null}
                {(conflictCounts.get(id) ?? 0) > 0 ? (
                  <MonoTag tone="crimson">conflict</MonoTag>
                ) : null}
              </div>
              <DependencyStrip
                mod={mod}
                profile={profile}
                onEnableDependency={onEnableDependency}
              />
            </div>
            <StatPill value={`#${orderIdx + 1}`} label="load" className="tracking-normal" />
            <OverlayButton modId={id} />
            <Button type="button" onClick={() => onUninstall(id)} variant="danger" size="sm">
              uninstall
            </Button>
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
  if (mod.dependencies.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="font-mono text-[11px] tracking-[0.18em] text-ash">Requires</span>
      {mod.dependencies.map((depId) => {
        const dep = getMod(depId);
        const enabled = dep ? isEnabledIn(profile, depId) : false;
        if (!dep) {
          return (
            <MonoTag key={depId} tone="crimson">
              {depId} missing
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
