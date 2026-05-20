import { createFileRoute, useNavigate } from '@tanstack/react-router';
import { Check, Plus, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button, Cover, MonoTag, SectionHeader, StatPill } from '../components/chrome';
import { MOCK_MODS, type ModCategory } from '../data/mock-mods';
import { useApp } from '../store';

export const Route = createFileRoute('/browse')({
  component: BrowsePage,
});

type Sort = 'recent' | 'popular' | 'rating';

const CATEGORIES: { id: ModCategory | 'all'; label: string }[] = [
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

function BrowsePage() {
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [cat, setCat] = useState<ModCategory | 'all'>('all');
  const [sort, setSort] = useState<Sort>('popular');
  const installed = useApp((s) => s.installed);
  const installMod = useApp((s) => s.installMod);

  const list = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return MOCK_MODS.filter((m) => {
      if (cat !== 'all' && m.category !== cat) return false;
      if (!needle) return true;
      return (
        m.name.toLowerCase().includes(needle) ||
        m.author.toLowerCase().includes(needle) ||
        m.tags.some((t) => t.toLowerCase().includes(needle))
      );
    }).sort((a, b) => {
      if (sort === 'popular') return b.downloads - a.downloads;
      if (sort === 'rating') return b.rating - a.rating;
      return a.id < b.id ? 1 : -1; // pseudo-recent
    });
  }, [q, cat, sort]);

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Browse"
        subtitle="The remote index. Hand-picked mods from the community."
      />

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[260px]">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ash" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search the index…"
            className="input-grim"
          />
        </div>
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
              {s}
            </Button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {CATEGORIES.map((c) => (
          <Button
            key={c.id}
            type="button"
            onClick={() => setCat(c.id)}
            aria-pressed={cat === c.id}
            variant={cat === c.id ? 'danger' : 'default'}
            size="sm"
          >
            {c.label}
          </Button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {list.map((m) => {
          const here = installed.includes(m.id);
          return (
            <a
              key={m.id}
              href={`/mod/${m.slug}`}
              onClick={(e) => {
                const el = e.target as HTMLElement;
                if (el.closest('button, a, input, textarea, select, [role="switch"]')) return;
                e.preventDefault();
                navigate({ to: '/mod/$slug', params: { slug: m.slug } });
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  navigate({ to: '/mod/$slug', params: { slug: m.slug } });
                }
              }}
              className="grimoire-card flex flex-col gap-3 p-5 transition-colors duration-150 hover:border-gilt/40"
            >
              <Cover src={m.image} alt={`${m.name} cover`} caption={`${m.slug}.png`} />
              <header className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-serif-italic text-xl leading-tight text-parchment">
                    {m.name}
                  </p>
                  <p className="font-mono mt-1 text-ash">
                    {m.author} · v{m.latestVersion}
                  </p>
                </div>
                <Button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    installMod(m.id);
                  }}
                  disabled={here}
                  variant={here ? 'default' : 'primary'}
                  size="sm"
                >
                  {here ? (
                    <>
                      <Check className="h-3.5 w-3.5" /> installed
                    </>
                  ) : (
                    <>
                      <Plus className="h-3.5 w-3.5" /> install
                    </>
                  )}
                </Button>
              </header>
              <p className="font-serif-italic text-sm leading-snug text-smoke">
                {m.summary}
              </p>
              <div className="mt-auto flex items-center justify-between gap-2">
                <div className="flex flex-wrap gap-1">
                  <MonoTag tone="default">{m.category}</MonoTag>
                  {m.tags.slice(0, 2).map((t) => (
                    <MonoTag key={t} tone="default">
                      {t}
                    </MonoTag>
                  ))}
                </div>
                <StatPill
                  value={`★ ${m.rating.toFixed(1)}`}
                  label={`${m.downloads.toLocaleString()} dl`}
                />
              </div>
            </a>
          );
        })}
      </div>
      {list.length === 0 ? (
        <p className="font-serif-italic py-10 text-center text-ash">
          No mods match that search.
        </p>
      ) : null}
    </div>
  );
}
