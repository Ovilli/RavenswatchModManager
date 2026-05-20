import { Link, createFileRoute, useNavigate } from '@tanstack/react-router';
import { AlertTriangle, GripVertical, LayoutGrid, List, Plus } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button, EmptyState, Fleuron, MonoTag, SectionHeader, InkSwitch, StatPill } from '../components/chrome';
import { MOCK_MODS, type ModCategory } from '../data/mock-mods';
import { activeProfile, detectConflicts, getMod, useApp } from '../store';

export const Route = createFileRoute('/')({
  component: LibraryPage,
});

type ViewMode = 'cards' | 'list';

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
  const [view, setView] = useState<ViewMode>('cards');
  const conflicts = useMemo(() => detectConflicts(profile), [profile]);

  const grouped = useMemo(() => {
    const groups = new Map<ModCategory, { id: string; orderIdx: number }[]>();
    profile.loadOrder.forEach((id, orderIdx) => {
      const mod = getMod(id);
      if (!mod) return;
      const list = groups.get(mod.category) ?? [];
      list.push({ id, orderIdx });
      groups.set(mod.category, list);
    });
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [profile.loadOrder]);

  if (profile.loadOrder.length === 0) {
    return (
      <EmptyState
        title="An empty grimoire"
        body="No mods in this profile yet. Browse the index to add your first."
        action={
          <Link
            to="/browse"
            className="btn-grim"
            data-variant="primary"
          >
            Browse mods
          </Link>
        }
      />
    );
  }

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Library"
        subtitle={`${profile.loadOrder.length} mods bound to ${profile.name}.`}
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
            <Link
              to="/browse"
              className="btn-grim ml-2"
              data-variant="primary"
            >
              <Plus className="h-4 w-4" /> Add mod
            </Link>
          </div>
        }
      />

      {conflicts.length > 0 ? (
        <Link
          to="/conflicts"
          className="ember-banner flex items-center justify-between px-4 py-3"
        >
          <span className="flex items-center gap-3">
            <AlertTriangle className="h-4 w-4 text-crimson" />
            <span className="font-serif-italic text-base">
              {conflicts.length} {conflicts.length === 1 ? 'conflict' : 'conflicts'} between
              enabled mods.
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
          <StatPill value={installed.length} label={`installed in ${profile.name}`} />
        </div>
      </div>
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
        const enabled = !profile.disabled.has(id);
        const outdated = mod.version !== mod.latestVersion;
        return (
          <a
            key={id}
            href={`/mod/${mod.slug}`}
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
            className="grimoire-card flex flex-col gap-3 p-5 transition-colors duration-150 hover:border-gilt/40"
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
            <p className="font-serif-italic text-sm leading-snug text-smoke">
              {mod.summary}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              {outdated ? <MonoTag tone="gilt">Update {mod.latestVersion}</MonoTag> : null}
              <MonoTag tone="default">{mod.category}</MonoTag>
              <StatPill value={`#${orderIdx + 1}`} label="load" className="tracking-normal" />
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
            </a>
          );
        })}
      </div>
    );
  }

function ListView({ items, profile, onToggle, onReorder, onUninstall }: RowProps) {
  const [dragId, setDragId] = useState<string | null>(null);

  return (
    <ul className="grimoire-card divide-y divide-border">
      {items.map(({ id, orderIdx }) => {
        const mod = getMod(id);
        if (!mod) return null;
        const enabled = !profile.disabled.has(id);
        const isDragging = dragId === id;
        return (
          <li
            key={id}
            draggable
            onDragStart={(e) => {
              setDragId(id);
              e.dataTransfer.effectAllowed = 'move';
            }}
            onDragEnd={() => setDragId(null)}
            onDragOver={(e) => {
              e.preventDefault();
              e.dataTransfer.dropEffect = 'move';
            }}
            onDrop={(e) => {
              e.preventDefault();
              if (dragId && onReorder) onReorder(dragId, orderIdx);
              setDragId(null);
            }}
            className={`flex items-center gap-4 px-4 py-3 transition-opacity duration-150 ${
              isDragging ? 'opacity-40' : ''
            } ${dragId && !isDragging ? 'opacity-60' : ''} hover:bg-oxblood/10`}
          >
            <GripVertical className="h-4 w-4 cursor-grab text-ash" />
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
            <Button
              type="button"
              onClick={() => onUninstall(id)}
              variant="danger"
              size="sm"
            >
              uninstall
            </Button>
          </li>
        );
      })}
    </ul>
  );
}
