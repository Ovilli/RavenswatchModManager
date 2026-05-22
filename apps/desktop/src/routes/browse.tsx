import type { ModCategory, ModListItem } from '@rsmm/schemas';
import { useQuery } from '@tanstack/react-query';
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router';
import { AlertTriangle, Check, Plus, Search, WifiOff } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button, CopyButton, Cover, MonoTag, SectionHeader, StatPill } from '../components/chrome';
import { MOCK_MODS } from '../data/mock-mods';
import { api } from '../lib/api';
import { inTauri } from '../lib/platform';
import { useApp } from '../store';

// Adapter so a `MockMod` slots into the same `ModListItem`-shaped grid
// when the API is unreachable. The fields the grid actually reads
// (id/slug/name/author/summary/category/tags/imageUrl/rating/downloads/
// latestVersion/updatedAt) are all present on `MockMod`.
const MOCK_AS_LIST: ModListItem[] = MOCK_MODS.map((m) => ({
  id: m.id,
  slug: m.slug,
  name: m.name,
  author: m.author,
  summary: m.summary,
  category: m.category,
  tags: m.tags,
  imageUrl: m.image ?? null,
  rating: m.rating,
  downloads: m.downloads,
  latestVersion: m.latestVersion,
  license: null,
  updatedAt: new Date().toISOString(),
}));

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

  const { data, error, isLoading } = useQuery({
    queryKey: ['mods', 'list', q],
    queryFn: () => api.mods.list({ q: q.trim() || undefined, limit: 100 }),
    staleTime: 30_000,
    retry: 1,
    enabled: inTauri(),
  });

  const usingFallback = !data?.items && Boolean(error);
  const list = useMemo(() => {
    const items: ModListItem[] = data?.items ?? (usingFallback ? MOCK_AS_LIST : []);
    const filtered = items
      .filter((m) => (cat === 'all' ? true : m.category === cat))
      .filter((m) => {
        const needle = q.trim().toLowerCase();
        if (!needle) return true;
        return (
          m.name.toLowerCase().includes(needle) ||
          (m.summary ?? '').toLowerCase().includes(needle) ||
          (m.author ?? '').toLowerCase().includes(needle)
        );
      });
    const sorted = [...filtered].sort((a, b) => {
      if (sort === 'popular') return b.downloads - a.downloads;
      if (sort === 'rating') return (b.rating ?? 0) - (a.rating ?? 0);
      return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime();
    });
    return sorted;
  }, [data, cat, sort, q, usingFallback]);

  return (
    <div className="space-y-6">
      <SectionHeader title="Browse" subtitle="The remote index. Mods from the community catalog." />

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[260px]">
          <Search
            className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ash"
            aria-hidden
          />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search the index…"
            aria-label="Search mods"
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

      {error ? (
        <div className="ember-banner flex items-center gap-3 px-4 py-3">
          <WifiOff className="h-4 w-4 text-crimson shrink-0" />
          <span className="font-serif-italic text-base">
            Couldn't reach the mod index — showing cached mods.
          </span>
          <CopyButton value={(error as Error).message} />
        </div>
      ) : null}

      {isLoading ? <BrowseSkeleton /> : null}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {list.map((m) => {
          const here = installed.includes(m.id);
          return (
            <article
              key={m.id}
              tabIndex={0}
              role="link"
              aria-label={`${m.name}${m.author ? ` by ${m.author}` : ''}`}
              onClick={(e) => {
                const el = e.target as HTMLElement;
                if (el.closest('button, a, input, textarea, select, [role="switch"]')) return;
                navigate({ to: '/mod/$slug', params: { slug: m.slug } });
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  navigate({ to: '/mod/$slug', params: { slug: m.slug } });
                }
              }}
              className="grimoire-card flex flex-col gap-3 p-5 cursor-pointer transition-colors duration-150 hover:border-gilt/40 focus:border-gilt/60 focus:outline-none"
            >
              {m.imageUrl ? (
                <Cover src={m.imageUrl} alt={`${m.name} cover`} caption={`${m.slug}.png`} />
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
                    {m.author ?? 'unknown'}
                    {m.latestVersion ? ` · v${m.latestVersion}` : ''}
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
              {m.summary ? (
                <p className="font-serif-italic text-sm leading-snug text-smoke">{m.summary}</p>
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
                  label={`${m.downloads.toLocaleString()} dl`}
                />
              </div>
            </article>
          );
        })}
      </div>
      {!isLoading && !error && list.length === 0 ? (
        <p className="font-serif-italic py-10 text-center text-ash">No mods match that search.</p>
      ) : null}
    </div>
  );
}

function BrowseSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" aria-busy="true">
      {Array.from({ length: 6 }).map((_, i) => (
        <div
          // biome-ignore lint/suspicious/noArrayIndexKey: skeleton placeholders have no identity
          key={i}
          className="grimoire-card flex flex-col gap-3 p-5 animate-pulse"
        >
          <div className="aspect-video w-full bg-oxblood/20 rounded" />
          <div className="h-6 w-3/4 bg-oxblood/20 rounded" />
          <div className="h-4 w-1/2 bg-oxblood/15 rounded" />
          <div className="h-4 w-full bg-oxblood/10 rounded" />
        </div>
      ))}
    </div>
  );
}
