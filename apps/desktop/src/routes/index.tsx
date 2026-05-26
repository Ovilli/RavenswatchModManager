import { useQuery } from '@tanstack/react-query';
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
import { SetupBanner } from '../components/setup-banner';
import { useDialog } from '../components/toast';
import { useToast } from '../components/toast';
import { UpdatesPanel } from '../components/updates-panel';
import type { ModCategory } from '../data/mock-mods';
import { listLocalMods, uninstallLocalMod } from '../lib/rsmm';
import { activeProfile, detectConflicts, getMod, isEnabledIn, useApp } from '../store';

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
  const modsDir = useApp((s) => s.settings.modsDir);
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
    () => profile.loadOrder.filter((id) => isEnabledIn(profile, id)).length,
    [profile],
  );
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
    queryKey: ['rsmm', 'list', modsDir],
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
  const refreshLocalMods = useCallback(async () => {
    const local = await listLocalMods();
    if (local) syncLocalMods(local);
  }, [syncLocalMods]);

  const removeLocalMod = useCallback(async (id: string) => {
    const result = await uninstallLocalMod(id);
    if (!result || !result.ok) {
      throw new Error(result?.error || `Failed to uninstall ${id}`);
    }
  }, []);

  const uninstall = useCallback(
    async (id: string) => {
      await removeLocalMod(id);
      await refreshLocalMods();
      toast.push('Mod uninstalled.', 'success');
    },
    [refreshLocalMods, removeLocalMod, toast],
  );

  const bulkUninstall = useCallback(() => {
    void (async () => {
      try {
        for (const id of selected) {
          await removeLocalMod(id);
        }
        await refreshLocalMods();
        clearSelection();
        toast.push('Selected mods uninstalled.', 'success');
      } catch (err) {
        toast.push(err instanceof Error ? err.message : String(err), 'error');
      }
    })();
  }, [clearSelection, refreshLocalMods, removeLocalMod, selected, toast]);

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

  // Mods exist on disk but the active profile hasn't opted any of them
  // in yet (e.g. a freshly created profile). The Library is profile-
  // scoped, so we deliberately don't surface the disk-only mods here —
  // /browse is where the user picks which ones to add.
  if (profile.loadOrder.length === 0) {
    return (
      <div className="space-y-6">
        <SetupBanner />
        <EmptyState
          title={`“${profile.name}” has no mods yet`}
          body={
            installed.length === 1
              ? '1 mod is present on disk. Browse to add it to this profile.'
              : `${installed.length} mods are present on disk. Browse to add them to this profile.`
          }
          action={
            <Link to="/browse" className="btn-grim" data-variant="primary">
              Browse mods
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
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
        <Panel className="flex flex-wrap items-center justify-between gap-3">
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
        {filterCount > 0 ? (
          <Button
            type="button"
            onClick={() => {
              setQuery('');
              setCategory('all');
              setStatus('all');
            }}
            variant="default"
            size="sm"
          >
            <X className="h-4 w-4" /> Clear filters
          </Button>
        ) : null}
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

      {localModsLoading && Object.keys(localModsState).length === 0 ? (
        <Panel>
          <div className="space-y-3 animate-pulse" aria-busy="true">
            <div className="h-6 w-56 rounded bg-oxblood/20" />
            <div className="h-4 w-96 max-w-full rounded bg-oxblood/15" />
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <div
                  // biome-ignore lint/suspicious/noArrayIndexKey: fixed loading placeholders
                  key={i}
                  className="h-36 rounded border border-border bg-pitch/40"
                />
              ))}
            </div>
          </div>
        </Panel>
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
            className="grimoire-card flex flex-col gap-3 p-5 transition-colors duration-150 hover:border-gilt/40 cursor-pointer"
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
            <div className="flex flex-wrap items-center gap-2">
              {outdated ? <MonoTag tone="gilt">Update {mod.latestVersion}</MonoTag> : null}
              {depCount > 0 ? <MonoTag tone="crimson">{depCount} missing deps</MonoTag> : null}
              {conflictCount > 0 ? (
                <MonoTag tone="crimson">{conflictCount} conflicts</MonoTag>
              ) : null}
              <MonoTag tone="default">{mod.category}</MonoTag>
              <StatPill value={`#${orderIdx + 1}`} label="folder" className="tracking-normal" />
              <InkSwitch
                on={enabled}
                onClick={() => onToggle(id)}
                label={`${enabled ? 'Disable' : 'Enable'} ${mod.name}`}
              />
              <Button
                type="button"
                onClick={() => onUninstall(id)}
                variant="danger"
                size="sm"
                className="ml-auto"
              >
                uninstall
              </Button>
            </div>
            <DependencyStrip mod={mod} profile={profile} onEnableDependency={onEnableDependency} />
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
              <div className="mt-1 flex flex-wrap gap-1.5">
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
            <StatPill value={`#${orderIdx + 1}`} label="folder" className="tracking-normal" />
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

function getMissingDependencyCount(
  mod: NonNullable<ReturnType<typeof getMod>>,
  profile: ReturnType<typeof activeProfile>,
): number {
  return mod.dependencies.filter((depId) => !profile.loadOrder.includes(depId)).length;
}

function compareVersions(a: string, b: string): number {
  const parse = (value: string) =>
    value
      .split(/[^0-9A-Za-z]+/)
      .filter(Boolean)
      .map((part) => {
        const numeric = Number(part);
        return Number.isNaN(numeric) ? part.toLowerCase() : numeric;
      });
  const left = parse(a);
  const right = parse(b);
  const len = Math.max(left.length, right.length);
  for (let i = 0; i < len; i += 1) {
    const l = left[i];
    const r = right[i];
    if (l === undefined) return -1;
    if (r === undefined) return 1;
    if (typeof l === 'number' && typeof r === 'number' && l !== r) return l - r;
    if (typeof l === 'number' && typeof r === 'string') return 1;
    if (typeof l === 'string' && typeof r === 'number') return -1;
    if (l !== r) return String(l).localeCompare(String(r));
  }
  return 0;
}

function buildEnablePlan(ids: string[]): { order: string[]; missing: string[] } {
  const seen = new Set<string>();
  const visiting = new Set<string>();
  const missing = new Set<string>();
  const order: string[] = [];

  const visit = (id: string) => {
    if (seen.has(id) || visiting.has(id)) return;
    visiting.add(id);
    const mod = getMod(id);
    if (!mod) {
      missing.add(id);
      visiting.delete(id);
      return;
    }
    for (const depId of mod.dependencies) visit(depId);
    visiting.delete(id);
    seen.add(id);
    order.push(id);
  };

  for (const id of ids) visit(id);
  return { order, missing: [...missing] };
}

function findBlockingDependents(ids: string[], profile: ReturnType<typeof activeProfile>) {
  const target = new Set(ids);
  const blocked = new Map<string, string[]>();

  for (const modId of profile.loadOrder) {
    if (!isEnabledIn(profile, modId) || target.has(modId)) continue;
    const mod = getMod(modId);
    if (!mod) continue;
    for (const depId of mod.dependencies) {
      if (!target.has(depId)) continue;
      const list = blocked.get(depId) ?? [];
      list.push(mod.name);
      blocked.set(depId, list);
    }
  }

  return [...blocked.entries()].map(([targetId, dependents]) => [targetId, dependents] as const);
}
