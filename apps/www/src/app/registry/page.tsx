'use client';
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Spinner, buttonVariants } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import { Download, ExternalLink, Search } from 'lucide-react';
import type { Route } from 'next';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';
import type { ModCategory } from '@rsmm/schemas';
import { api } from '../../lib/api';
import { getApiUrl } from '../../lib/api-url';

type Sort = 'popular' | 'recent' | 'rating';

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

export default function RegistryPage() {
  const router = useRouter();
  const [q, setQ] = useState('');
  const [cat, setCat] = useState<ModCategory | 'all'>('all');
  const [sort, setSort] = useState<Sort>('popular');

  const list = useQuery({
    queryKey: ['registry', q],
    queryFn: () => api.mods.list({ q: q || undefined, limit: 48 }),
  });

  const items = useMemo(() => {
    const data = list.data?.items ?? [];
    const filtered = data
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
    return [...filtered].sort((a, b) => {
      if (sort === 'popular') return b.downloads - a.downloads;
      if (sort === 'rating') return (b.rating ?? 0) - (a.rating ?? 0);
      return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime();
    });
  }, [list.data, cat, sort, q]);

  return (
    <main className="relative overflow-hidden animate-page-in">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,hsl(var(--crimson)/0.08),transparent_50%)]" />
      <div className="relative container mx-auto space-y-6 px-6 py-12">
        <header>
          <h1 className="text-4xl font-bold tracking-tight">Registry</h1>
          <p className="text-sm text-muted-foreground">Community-published mods.</p>
        </header>

        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-[260px] flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search by name, author, or summary…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="pl-9"
            />
          </div>
          {(['popular', 'recent', 'rating'] as const).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setSort(s)}
              className={buttonVariants({ variant: sort === s ? 'default' : 'outline', size: 'sm' })}
            >
              {s}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap gap-1.5">
          {CATEGORIES.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => setCat(c.id)}
              className={buttonVariants({ variant: cat === c.id ? 'default' : 'outline', size: 'sm' })}
            >
              {c.label}
            </button>
          ))}
        </div>

        {list.isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Spinner />
          </div>
        ) : list.isError ? (
          <p className="text-sm text-destructive">Cannot reach API ({String(list.error)})</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No mods match that search.</p>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {items.map((m) => (
              // biome-ignore lint/a11y/useSemanticElements: card-as-link composite with nested interactive children; wrapping with <a> would invalidate the descendant <a>/<button> tags Next.js Link inserts.
              <div key={m.id} className="grimoire-card cursor-pointer overflow-hidden" tabIndex={0} role="link"
                onClick={(e) => {
                  const el = e.target as HTMLElement;
                  if (el.closest('a, button, input, textarea, select, [role="switch"]')) return;
                  router.push(`/registry/${m.slug}` as Route);
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    router.push(`/registry/${m.slug}` as Route);
                  }
                }}
              >
                {m.imageUrl ? (
                  <div className="aspect-[16/9] w-full overflow-hidden bg-muted">
                    <img
                      src={m.imageUrl}
                      alt={`${m.name} preview`}
                      className="h-full w-full object-cover"
                      loading="lazy"
                    />
                  </div>
                ) : (
                  <div className="aspect-[16/9] w-full bg-muted" />
                )}
                <CardHeader>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <a
                        href={`/registry/${m.slug}`}
                        onClick={(e) => e.stopPropagation()}
                        className="hover:text-gilt transition-colors"
                      >
                        <CardTitle className="text-lg">{m.name}</CardTitle>
                      </a>
                      <CardDescription className="mt-0.5">
                        {m.author ?? 'unknown'}
                        {m.latestVersion ? <Badge variant="outline" className="ml-2 text-[0.6rem]">v{m.latestVersion}</Badge> : null}
                      </CardDescription>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      {m.latestVersion ? (
                        <a
                          href={`${getApiUrl()}/api/mods/${m.slug}/${m.latestVersion}/download`}
                          className={buttonVariants({ variant: 'outline', size: 'sm' })}
                          title="Download mod archive"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Download className="h-3.5 w-3.5" />
                        </a>
                      ) : null}
                      <a
                        href={`rsmm://mods/${m.slug}`}
                        className={buttonVariants({ variant: 'outline', size: 'sm' })}
                        title="Open in RSMM desktop app"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    </div>
                  </div>
                </CardHeader>
                {m.summary ? (
                  <CardContent className="space-y-3">
                    <p className="text-sm text-muted-foreground line-clamp-2">{m.summary}</p>
                    <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                      <div className="flex items-center gap-2">
                        {m.category ? <Badge variant="secondary">{m.category}</Badge> : null}
                        <span>{m.downloads.toLocaleString()} dl</span>
                      </div>
                      <div className="flex items-center gap-1">
                        {m.rating != null ? <span>★ {m.rating.toFixed(1)}</span> : null}
                      </div>
                    </div>
                  </CardContent>
                ) : (
                  <CardContent>
                    <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                      <div className="flex items-center gap-2">
                        {m.category ? <Badge variant="secondary">{m.category}</Badge> : null}
                        <span>{m.downloads.toLocaleString()} dl</span>
                      </div>
                      <div className="flex items-center gap-1">
                        {m.rating != null ? <span>★ {m.rating.toFixed(1)}</span> : null}
                      </div>
                    </div>
                  </CardContent>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
