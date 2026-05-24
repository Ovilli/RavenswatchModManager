import type { Collection, ModListItem } from '@rsmm/schemas';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router';
import { Check, ExternalLink, Loader2, Plus, Search, WifiOff } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button, CopyButton, Cover, MonoTag, SectionHeader, StatPill } from '../components/chrome';
import { useToast } from '../components/toast';
import { api, getApiBaseUrl } from '../lib/api';
import { validateProfileName } from '../lib/profile-name';
import { installModFromIndex, listLocalMods } from '../lib/rsmm';
import { activeProfile, useApp } from '../store';
import type { Profile } from '../store';

export const Route = createFileRoute('/browse')({
  component: BrowsePage,
});

type Sort = 'recent' | 'popular' | 'rating';
type Tab = 'mods' | 'collections';

function BrowsePage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>('mods');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<Sort>('popular');
  const installed = useApp((s) => s.installed);
  const profiles = useApp((s) => s.profiles);
  const installMod = useApp((s) => s.installMod);
  const createProfile = useApp((s) => s.createProfile);
  const syncLocalMods = useApp((s) => s.syncLocalMods);
  const profile = useApp(activeProfile);
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
      // Already-on-disk path skips the network round-trip.
      if (!installed.includes(slug)) {
        const result = await installModFromIndex(slug);
        if (!result || !result.ok) {
          throw new Error(result?.error ?? 'install failed');
        }
        const local = await listLocalMods();
        if (local) syncLocalMods(local);
      }
      installMod(slug, targetProfileId);
      // Default profile installs create a new "My Mods" profile — read the
      // active profile after installMod, not the requested id.
      const { profiles, activeProfileId } = useApp.getState();
      const profileName =
        profiles.find((p) => p.id === activeProfileId)?.name ?? 'profile';
      toast.push(`Added ${slug} to “${profileName}”.`, 'success');
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
  const { data: modData, error: modError, isLoading: modLoading } = useQuery({
    queryKey: ['mods', 'list', q],
    queryFn: () => api.mods.list({ q: q.trim() || undefined, limit: 100 }),
    staleTime: 30_000,
    retry: 1,
    enabled: tab === 'mods',
  });

  // Collections query
  const { data: colData, error: colError, isLoading: colLoading } = useQuery({
    queryKey: ['collections', 'public'],
    queryFn: () => api.collections.list(),
    staleTime: 30_000,
    retry: 1,
    enabled: tab === 'collections',
  });

  const list = useMemo(() => {
    if (tab === 'collections') return [];
    const items: ModListItem[] = modData?.items ?? [];
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
  }, [modData, sort, q, tab]);

  const collections = useMemo(() => {
    if (tab === 'mods') return [];
    const items: Collection[] = colData?.items ?? [];
    const needle = q.trim().toLowerCase();
    return needle
      ? items.filter(
          (c) =>
            c.name.toLowerCase().includes(needle) ||
            (c.summary ?? '').toLowerCase().includes(needle),
        )
      : items;
  }, [colData, q, tab]);

  const isLoading = tab === 'mods' ? modLoading : colLoading;
  const error = tab === 'mods' ? modError : colError;

  return (
    <div className="space-y-6">
      <SectionHeader
        title={tab === 'mods' ? 'Browse' : 'Collections'}
        subtitle={
          tab === 'mods'
            ? 'The remote index. Mods from the community catalog.'
            : 'Curated bundles of mods made by the community.'
        }
      />

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant={tab === 'mods' ? 'primary' : 'default'}
            onClick={() => setTab('mods')}
          >
            Mods
          </Button>
          <Button
            type="button"
            size="sm"
            variant={tab === 'collections' ? 'primary' : 'default'}
            onClick={() => setTab('collections')}
          >
            Collections
          </Button>
        </div>
        <div className="relative flex-1 min-w-[260px]">
          <Search
            className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ash"
            aria-hidden
          />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={tab === 'mods' ? 'Search the index…' : 'Search collections…'}
            aria-label={tab === 'mods' ? 'Search mods' : 'Search collections'}
            className="input-grim"
          />
        </div>
        {tab === 'mods' ? (
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
        ) : null}
      </div>

      {error ? (
        <div className="ember-banner flex flex-col gap-2 px-4 py-3">
          <div className="flex items-center gap-3">
            <WifiOff className="h-4 w-4 text-crimson shrink-0" />
            <span className="font-serif-italic text-base">API unreachable.</span>
            <CopyButton value={(error as Error).message} />
            <button
              type="button"
              onClick={() => window.open(getApiBaseUrl(), '_blank')}
              className="font-mono text-xs text-ash underline-offset-2 hover:text-parchment hover:underline flex items-center gap-1"
            >
              <ExternalLink className="h-3 w-3" /> open in browser
            </button>
          </div>
          <div className="font-mono text-xs text-ash bg-pitch/30 px-2 py-1 rounded">
            {getApiBaseUrl()} <span className="text-oxblood/60">|</span> origin: {window.location.origin}
          </div>
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

      {tab === 'collections' ? (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {collections.map((c) => (
              <article
                key={c.id}
                tabIndex={0}
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
                className="grimoire-card flex flex-col gap-3 p-5 cursor-pointer transition-colors duration-150 hover:border-gilt/40 focus:border-gilt/60 focus:outline-none"
              >
                {c.imageUrl ? (
                  <Cover src={c.imageUrl} alt={`${c.name} cover`} caption={`${c.slug}.png`} />
                ) : null}
                <header className="flex items-start justify-between gap-3">
                  <div>
                    <Link
                      to="/collection/$slug"
                      params={{ slug: c.slug }}
                      onClick={(e) => e.stopPropagation()}
                      className="font-serif-italic text-xl leading-tight text-parchment hover:text-gilt"
                    >
                      {c.name}
                    </Link>
                    <p className="font-mono mt-1 text-ash">
                      {c.ownerName ?? 'unknown'} · {c.modCount} mod{c.modCount === 1 ? '' : 's'}
                    </p>
                  </div>
                </header>
                {c.summary ? (
                  <p className="font-serif-italic text-sm leading-snug text-smoke">{c.summary}</p>
                ) : null}
                <div className="mt-auto flex items-center justify-between gap-2">
                  <span className="font-mono text-xs text-ash">
                    updated {new Date(c.updatedAt).toLocaleDateString()}
                  </span>
                </div>
              </article>
            ))}
          </div>
          {!isLoading && !error && collections.length === 0 ? (
            <p className="font-serif-italic py-10 text-center text-ash">
              {q.trim()
                ? 'No collections match that search.'
                : 'No public collections yet.'}
            </p>
          ) : null}
        </>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {list.map((m) => {
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
                        openPicker(m.slug);
                      }}
                      disabled={inProfile || installing[m.slug]}
                      variant={inProfile ? 'default' : 'primary'}
                      size="sm"
                      title={
                        inProfile
                          ? `Already in "${profile.name}"`
                          : onDisk
                            ? `On disk — click to add to "${profile.name}"`
                            : `Download from index + add to "${profile.name}"`
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
        </>
      )}
      {pickerSlug ? (
        <ProfilePicker
          slug={pickerSlug}
          profiles={profiles}
          onPick={pickProfile}
          onCreate={pickNewProfile}
          onCancel={() => setPickerSlug(null)}
        />
      ) : null}
    </div>
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
  const selectable = profiles.filter((p) => p.id !== 'default');
  const [creating, setCreating] = useState(selectable.length === 0);
  const [name, setName] = useState('');

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Choose profile"
      className="fixed inset-0 z-[70] flex items-center justify-center p-4 animate-fade-in"
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.preventDefault();
          onCancel();
        }
      }}
    >
      <div className="absolute inset-0 bg-pitch/80" onClick={onCancel} />
      <div className="grimoire-card relative w-[min(480px,92vw)] p-5">
        <h3 className="font-fraktur text-xl text-parchment">Install to profile</h3>
        <p className="font-serif-italic text-ash mt-2">
          Pick which profile receives <span className="font-mono">{slug}</span>.
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
                    {p.loadOrder.length} mod{p.loadOrder.length === 1 ? '' : 's'}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        {creating ? (
          <div className="mt-4 space-y-2">
            <label htmlFor="new-profile-name" className="font-mono block text-ash">
              New profile name
            </label>
            <input
              id="new-profile-name"
              ref={(el) => el?.focus()}
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  if (name.trim()) onCreate(name);
                }
              }}
              placeholder="My Mods"
              className="input-grim w-full"
            />
          </div>
        ) : null}
        <div className="mt-5 flex items-center justify-between gap-2">
          {selectable.length > 0 ? (
            <Button type="button" size="sm" onClick={() => setCreating((c) => !c)}>
              {creating ? 'pick existing' : 'create new'}
            </Button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button type="button" size="sm" onClick={onCancel}>
              cancel
            </Button>
            {creating ? (
              <Button
                type="button"
                size="sm"
                variant="primary"
                onClick={() => onCreate(name)}
                disabled={!name.trim()}
              >
                create + install
              </Button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function BrowseSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" aria-busy="true">
      {Array.from({ length: 6 }).map((_, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: static skeleton elements, no reordering
        <div key={i}
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
