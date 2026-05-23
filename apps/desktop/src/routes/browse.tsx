import type { ModListItem } from '@rsmm/schemas';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router';
import { Check, Loader2, Plus, Search, WifiOff } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button, CopyButton, Cover, MonoTag, SectionHeader, StatPill } from '../components/chrome';
import { api } from '../lib/api';
import { installModFromIndex, listLocalMods } from '../lib/rsmm';
import { activeProfile, useApp } from '../store';

export const Route = createFileRoute('/browse')({
  component: BrowsePage,
});

type Sort = 'recent' | 'popular' | 'rating';

function BrowsePage() {
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<Sort>('popular');
  const installed = useApp((s) => s.installed);
  const installMod = useApp((s) => s.installMod);
  const syncLocalMods = useApp((s) => s.syncLocalMods);
  const profile = useApp(activeProfile);
  const queryClient = useQueryClient();
  // Per-slug install state so each card spins independently.
  const [installing, setInstalling] = useState<Record<string, boolean>>({});
  const [installError, setInstallError] = useState<string | null>(null);

  async function handleInstall(slug: string) {
    setInstallError(null);
    setInstalling((m) => ({ ...m, [slug]: true }));
    try {
      const result = await installModFromIndex(slug);
      if (!result || !result.ok) {
        throw new Error(result?.error ?? 'install failed');
      }
      // Re-scan disk so `installed[]` / `localMods` pick the new
      // folder up, then add the slug to the active profile.
      const local = await listLocalMods();
      if (local) syncLocalMods(local);
      installMod(slug);
      // Bust the list cache so download counts refresh.
      await queryClient.invalidateQueries({ queryKey: ['mods', 'list'] });
    } catch (err) {
      setInstallError(err instanceof Error ? err.message : String(err));
    } finally {
      setInstalling((m) => ({ ...m, [slug]: false }));
    }
  }

  // Always talk to the real index. Dev runs against prod via the
  // Vite proxy (see `vite.config.ts`); Tauri prod talks to the API
  // directly. There is no offline mock — if the API is down the page
  // shows the error banner and an empty grid.
  const { data, error, isLoading } = useQuery({
    queryKey: ['mods', 'list', q],
    queryFn: () => api.mods.list({ q: q.trim() || undefined, limit: 100 }),
    staleTime: 30_000,
    retry: 1,
  });

  const list = useMemo(() => {
    const items: ModListItem[] = data?.items ?? [];
    const needle = q.trim().toLowerCase();
    const filtered = needle
      ? items.filter(
          (m) =>
            m.name.toLowerCase().includes(needle) ||
            (m.summary ?? '').toLowerCase().includes(needle) ||
            (m.author ?? '').toLowerCase().includes(needle),
        )
      : items;
    return [...filtered].sort((a, b) => {
      if (sort === 'popular') return b.downloads - a.downloads;
      if (sort === 'rating') return (b.rating ?? 0) - (a.rating ?? 0);
      return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime();
    });
  }, [data, sort, q]);

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

      {error ? (
        <div className="ember-banner flex items-center gap-3 px-4 py-3">
          <WifiOff className="h-4 w-4 text-crimson shrink-0" />
          <span className="font-serif-italic text-base">
            Couldn't reach the mod index.
          </span>
          <CopyButton value={(error as Error).message} />
        </div>
      ) : null}

      {installError ? (
        <div className="ember-banner flex items-center gap-3 px-4 py-3">
          <span className="font-serif-italic text-base text-crimson flex-1">
            Install failed: {installError}
          </span>
          <CopyButton value={installError} />
          <Button type="button" size="sm" onClick={() => setInstallError(null)}>
            dismiss
          </Button>
        </div>
      ) : null}

      {isLoading ? <BrowseSkeleton /> : null}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {list.map((m) => {
          // Slug is the canonical id post-install — `rsmm install-mod`
          // extracts to `mods/<slug>/`, so `LocalMod.id` after the
          // sync matches `m.slug` (not the API's internal UUID).
          const onDisk = installed.includes(m.slug);
          const inProfile = profile.loadOrder.includes(m.slug);
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
                    if (onDisk) {
                      // Already downloaded — adding to the profile is
                      // a state-only flip, no CLI work needed.
                      installMod(m.slug);
                    } else {
                      void handleInstall(m.slug);
                    }
                  }}
                  disabled={inProfile || installing[m.slug]}
                  variant={inProfile ? 'default' : 'primary'}
                  size="sm"
                  title={
                    inProfile
                      ? `Already in “${profile.name}”`
                      : onDisk
                        ? `On disk — click to add to “${profile.name}”`
                        : `Download from index + add to “${profile.name}”`
                  }
                >
                  {installing[m.slug] ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" /> downloading
                    </>
                  ) : inProfile ? (
                    <>
                      <Check className="h-3.5 w-3.5" /> in profile
                    </>
                  ) : onDisk ? (
                    <>
                      <Plus className="h-3.5 w-3.5" /> add
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
        <p className="font-serif-italic py-10 text-center text-ash">
          {q.trim() ? 'No mods match that search.' : 'No mods published to the index yet.'}
        </p>
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
