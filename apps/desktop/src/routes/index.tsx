import { useQuery } from '@tanstack/react-query';
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router';
import {
  AlertTriangle,
  GripVertical,
  LayoutGrid,
  List,
  Plus,
  Search,
  SlidersHorizontal,
  X,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  CopyButton,
  EmptyState,
  Fleuron,
  InkSwitch,
  MonoTag,
  SectionHeader,
  StatPill,
} from '../components/chrome';
import { SetupBanner } from '../components/setup-banner';
import { UpdatesPanel } from '../components/updates-panel';
import type { ModCategory } from '../data/mock-mods';
import { listLocalMods } from '../lib/rsmm';
import { activeProfile, detectConflicts, getMod, isEnabledIn, useApp } from '../store';

export const Route = createFileRoute('/')({
  component: LibraryPage,
});

type ViewMode = 'cards' | 'list';
type LibraryStatusFilter = 'all' | 'enabled' | 'disabled' | 'outdated';

const LIBRARY_CATEGORIES: { id: ModCategory | 'all'; label: string }[] = [
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
  const profile = useApp(activeProfile);
  const toggleMod = useApp((s) => s.toggleMod);
  const reorderMod = useApp((s) => s.reorderMod);
  const uninstall = useApp((s) => s.uninstallMod);
  const installed = useApp((s) => s.installed);
  const syncLocalMods = useApp((s) => s.syncLocalMods);
  const modsDir = useApp((s) => s.settings.modsDir);
  const [view, setView] = useState<ViewMode>('cards');
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<ModCategory | 'all'>('all');
  const [status, setStatus] = useState<LibraryStatusFilter>('all');
  // Library is *profile-scoped*: a mod is in the user's library iff
  // it's been explicitly added to the active profile's load order.
  // Mods present on disk but not in this profile live in /browse with
  // an "Installed elsewhere" badge — they don't show up here.
  const enabledCount = useMemo(
    () => profile.loadOrder.filter((id) => isEnabledIn(profile, id)).length,
    [profile],
  );
  const conflicts = useMemo(() => detectConflicts(profile), [profile]);

  const { data: localMods, error: localModsError } = useQuery({
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
    return profile.loadOrder
      .map((id, orderIdx) => {
        const mod = getMod(id);
        if (!mod) return null;
        const enabled = isEnabledIn(profile, id);
        const outdated = mod.version !== mod.latestVersion;
        return { id, orderIdx, mod, enabled, outdated };
      })
      .filter((row): row is NonNullable<typeof row> => {
        if (!row) return false;
        if (category !== 'all' && row.mod.category !== category) return false;
        if (status === 'enabled' && !row.enabled) return false;
        if (status === 'disabled' && row.enabled) return false;
        if (status === 'outdated' && !row.outdated) return false;
        if (!needle) return true;
        return (
          row.mod.name.toLowerCase().includes(needle) ||
          row.mod.author.toLowerCase().includes(needle) ||
          row.mod.summary.toLowerCase().includes(needle) ||
          row.mod.category.toLowerCase().includes(needle) ||
          row.mod.tags.some((tag) => tag.toLowerCase().includes(needle))
        );
      });
  }, [category, profile, query, status]);

  const grouped = useMemo(() => {
    const groups = new Map<ModCategory, { id: string; orderIdx: number }[]>();
    for (const { id, orderIdx, mod } of filtered) {
      const list = groups.get(mod.category) ?? [];
      list.push({ id, orderIdx });
      groups.set(mod.category, list);
    }
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [filtered]);

  const filterCount = [category !== 'all', status !== 'all', query.trim().length > 0].filter(
    Boolean,
  ).length;

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
              onClick={() => setView('cards')}
              aria-pressed={view === 'cards'}
              variant={view === 'cards' ? 'gilt' : 'default'}
              size="sm"
              aria-label="Card view"
            >
              <LayoutGrid className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              onClick={() => setView('list')}
              aria-pressed={view === 'list'}
              variant={view === 'list' ? 'gilt' : 'default'}
              size="sm"
              aria-label="List view"
            >
              <List className="h-4 w-4" />
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
          {(['all', 'enabled', 'disabled', 'outdated'] as const).map((item) => (
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
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {LIBRARY_CATEGORIES.map((item) => (
          <Button
            key={item.id}
            type="button"
            onClick={() => setCategory(item.id)}
            aria-pressed={category === item.id}
            variant={category === item.id ? 'danger' : 'default'}
            size="sm"
          >
            {item.label}
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
              onToggle={toggleMod}
              onUninstall={uninstall}
            />
          ) : (
            <ListView
              items={items}
              profile={profile}
              onToggle={toggleMod}
              onUninstall={uninstall}
              onReorder={reorderMod}
            />
          )}
        </section>
      ))}

      <div className="font-mono pt-6 text-center text-ash">
        <div className="flex justify-center">
          <StatPill value={installed.length} label="in folder" />
          <StatPill value={enabledCount} label="enabled in profile" className="ml-2" />
        </div>
      </div>

      {filtered.length === 0 ? (
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
}

function CardGrid({ items, profile, onOpen, onToggle, onUninstall }: RowProps) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      {items.map(({ id, orderIdx }) => {
        const mod = getMod(id);
        if (!mod) return null;
        const enabled = isEnabledIn(profile, id);
        const outdated = mod.version !== mod.latestVersion;
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
              <InkSwitch
                on={enabled}
                onClick={() => onToggle(id)}
                label={`${enabled ? 'Disable' : 'Enable'} ${mod.name}`}
              />
            </header>
            <p className="font-serif-italic text-sm leading-snug text-smoke">{mod.summary}</p>
            <div className="flex flex-wrap items-center gap-2">
              {outdated ? <MonoTag tone="gilt">Update {mod.latestVersion}</MonoTag> : null}
              <MonoTag tone="default">{mod.category}</MonoTag>
              <StatPill value={`#${orderIdx + 1}`} label="folder" className="tracking-normal" />
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
          </div>
        );
      })}
    </div>
  );
}

function ListView({ items, profile, onToggle, onReorder, onUninstall }: RowProps) {
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
