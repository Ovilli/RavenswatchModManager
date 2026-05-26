import { ApiError, isRateLimited } from '@rsmm/api-client';
import { ProgressBar } from '@rsmm/ui';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createFileRoute, useNavigate } from '@tanstack/react-router';
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Download,
  Loader2,
  Plus,
  UserPlus,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Cover,
  CoverPlaceholder,
  Fleuron,
  Markdown,
  MonoTag,
  Panel,
  SectionHeader,
  StatPill,
} from '../components/chrome';
import { CheckIcon } from '../components/icons/CheckIcon';
import { useToast } from '../components/toast';
import { useDialog } from '../components/toast';
import { api } from '../lib/api';
import { installModFromIndex, listLocalMods } from '../lib/rsmm';
import { activeProfile, useApp } from '../store';

export const Route = createFileRoute('/collection/$slug')({
  component: CollectionDetailPage,
});

function CollectionDetailPage() {
  const { slug } = Route.useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const dialog = useDialog();
  const installed = useApp((s) => s.installed);
  const profile = useApp(activeProfile);
  const installMod = useApp((s) => s.installMod);
  const createProfile = useApp((s) => s.createProfile);
  const syncLocalMods = useApp((s) => s.syncLocalMods);
  const [installing, setInstalling] = useState<Record<string, boolean>>({});
  const [installAllRunning, setInstallAllRunning] = useState(false);
  const [installProgress, setInstallProgress] = useState({ value: 0, max: 0 });
  const [installError, setInstallError] = useState<string | null>(null);
  const [lightboxIdx, setLightboxIdx] = useState<number | null>(null);

  const { data, error, isLoading } = useQuery({
    queryKey: ['collections', 'detail', slug],
    queryFn: () => api.collections.get(slug),
    retry: (count, err) => (err instanceof ApiError && err.status === 404 ? false : count < 1),
    staleTime: 30_000,
  });

  async function installOne(modSlug: string) {
    setInstallError(null);
    setInstalling((m) => ({ ...m, [modSlug]: true }));
    try {
      if (!installed.includes(modSlug)) {
        const result = await installModFromIndex(modSlug);
        if (!result || !result.ok) {
          throw new Error(result?.error ?? 'install failed');
        }
        const local = await listLocalMods();
        if (local) syncLocalMods(local);
      }
      installMod(modSlug, profile.id === 'default' ? undefined : profile.id);
      await queryClient.invalidateQueries({ queryKey: ['mods', 'list'] });
      toast.push(`Added ${modSlug} to profile`, 'success');
    } catch (err) {
      if (isRateLimited(err)) {
        toast.push(`Rate limited — try again in ${err.retryAfter ?? 60}s`, 'error');
      } else {
        setInstallError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setInstalling((m) => ({ ...m, [modSlug]: false }));
    }
  }

  async function downloadAndAddMod(modSlug: string, targetProfileId: string | undefined) {
    const currentInstalled = useApp.getState().installed;
    if (!currentInstalled.includes(modSlug)) {
      const result = await installModFromIndex(modSlug);
      if (!result || !result.ok) {
        throw new Error(result?.error ?? `failed to install ${modSlug}`);
      }
    }
    installMod(modSlug, targetProfileId);
  }

  async function installAll() {
    if (!data?.mods) return;
    setInstallAllRunning(true);
    setInstallError(null);
    setInstallProgress({ value: 0, max: data.mods.length });
    const targetProfileId = profile.id === 'default' ? undefined : profile.id;
    for (const [idx, m] of data.mods.entries()) {
      setInstalling((prev) => ({ ...prev, [m.slug]: true }));
      try {
        await downloadAndAddMod(m.slug, targetProfileId);
      } catch (err) {
        setInstallError(err instanceof Error ? err.message : String(err));
        setInstalling((prev) => ({ ...prev, [m.slug]: false }));
        setInstallAllRunning(false);
        setInstallProgress({ value: 0, max: 0 });
        return;
      }
      setInstalling((prev) => ({ ...prev, [m.slug]: false }));
      setInstallProgress({ value: idx + 1, max: data.mods.length });
    }
    const local = await listLocalMods();
    if (local) syncLocalMods(local);
    await queryClient.invalidateQueries({ queryKey: ['mods', 'list'] });
    setInstallAllRunning(false);
    setInstallProgress({ value: 0, max: 0 });
    toast.push(`Installed ${data.mods.length} mods to current profile`, 'success');
  }

  async function installAsProfile() {
    if (!data?.mods || data.mods.length === 0) {
      toast.push('This collection has no mods to install.', 'error');
      return;
    }
    const name = await dialog.prompt({
      title: 'New profile from collection',
      initialValue: `Collection: ${data.name}`,
      placeholder: 'Profile name',
    });
    if (!name) return;
    setInstallAllRunning(true);
    setInstallError(null);
    setInstallProgress({ value: 0, max: data.mods.length });
    const newProfileId = createProfile(name);
    try {
      for (const [idx, m] of data.mods.entries()) {
        setInstalling((prev) => ({ ...prev, [m.slug]: true }));
        await downloadAndAddMod(m.slug, newProfileId);
        setInstalling((prev) => ({ ...prev, [m.slug]: false }));
        setInstallProgress({ value: idx + 1, max: data.mods.length });
      }
    } catch (err) {
      setInstallError(err instanceof Error ? err.message : String(err));
      setInstallAllRunning(false);
      setInstallProgress({ value: 0, max: 0 });
      return;
    }
    const local = await listLocalMods();
    if (local) syncLocalMods(local);
    await queryClient.invalidateQueries({ queryKey: ['mods', 'list'] });
    setInstallAllRunning(false);
    setInstallProgress({ value: 0, max: 0 });
    toast.push(`Created profile "${name}" with ${data.mods.length} mods`, 'success');
  }

  const allInstalled = data?.mods?.every((m) => profile.loadOrder.includes(m.slug)) ?? false;
  const someInstalled = data?.mods?.some((m) => profile.loadOrder.includes(m.slug)) ?? false;

  if (isLoading) {
    return (
      <div className="space-y-6 animate-pulse" aria-busy="true">
        <div className="h-8 w-24 bg-oxblood/15 rounded" />
        <div className="aspect-[21/9] w-full bg-oxblood/20 rounded" />
        <div className="h-10 w-2/3 bg-oxblood/25 rounded" />
        <div className="h-4 w-full bg-oxblood/15 rounded" />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="h-32 bg-oxblood/10 rounded" />
          <div className="h-32 bg-oxblood/10 rounded" />
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="space-y-4">
        <Button type="button" size="sm" onClick={() => navigate({ to: '/browse' })}>
          ← back
        </Button>
        <p className="font-serif-italic text-parchment">
          {error ? 'Could not load this collection.' : `No collection matches "${slug}".`}
        </p>
      </div>
    );
  }

  const {
    name,
    summary,
    description,
    imageUrl,
    ownerName,
    modCount,
    updatedAt,
    screenshots,
    mods,
  } = data;

  const markdownBody = description || summary || undefined;

  return (
    <div className="space-y-6">
      <Button type="button" size="sm" onClick={() => navigate({ to: '/browse' })}>
        <ArrowLeft className="h-3.5 w-3.5" /> back
      </Button>

      {imageUrl ? (
        <Cover
          src={imageUrl}
          alt={`${name} cover art`}
          caption={`${slug}-hero.png`}
          className="aspect-[21/9]"
        />
      ) : (
        <CoverPlaceholder caption={`${slug}-hero.png`} className="aspect-[21/9]" />
      )}

      <SectionHeader
        title={name}
        subtitle={`${ownerName ?? 'unknown'} · ${modCount} mod${modCount === 1 ? '' : 's'} · ${new Date(updatedAt).toLocaleDateString()}`}
        right={
          <div className="flex items-center gap-2">
            {allInstalled ? (
              <MonoTag tone="gilt">all installed</MonoTag>
            ) : mods.length > 0 ? (
              <>
                <Button
                  type="button"
                  variant="primary"
                  onClick={installAll}
                  disabled={installAllRunning}
                >
                  {installAllRunning ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" /> installing…
                    </>
                  ) : someInstalled ? (
                    <>
                      <Plus className="h-4 w-4" /> install rest
                    </>
                  ) : (
                    <>
                      <Download className="h-4 w-4" /> install all
                    </>
                  )}
                </Button>
                <Button
                  type="button"
                  variant="default"
                  onClick={installAsProfile}
                  disabled={installAllRunning}
                >
                  <UserPlus className="h-4 w-4" /> new profile
                </Button>
              </>
            ) : null}
          </div>
        }
      />

      {installAllRunning && installProgress.max > 0 ? (
        <ProgressBar
          value={installProgress.value}
          max={installProgress.max}
          label={`Installing ${installProgress.value}/${installProgress.max}…`}
        />
      ) : null}

      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        <div className="space-y-4 md:col-span-2">
          {markdownBody ? (
            <Panel>
              <h3 className="font-fraktur text-xl text-parchment mb-3">About</h3>
              <Fleuron />
              <Markdown source={markdownBody} className="mt-4" />
            </Panel>
          ) : null}

          {screenshots && screenshots.length > 0 ? (
            <Panel>
              <h3 className="font-fraktur text-xl text-parchment mb-3">Gallery</h3>
              <Fleuron />
              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
                {screenshots.map((shot, i) => (
                  <button
                    key={shot.url}
                    type="button"
                    onClick={() => setLightboxIdx(i)}
                    className="group block w-full text-left"
                  >
                    <div className="aspect-video overflow-hidden rounded border border-oxblood/30 bg-pitch">
                      <img
                        src={shot.url}
                        alt={shot.caption || `Screenshot ${i + 1}`}
                        loading="lazy"
                        className="h-full w-full object-cover transition-opacity group-hover:opacity-90"
                      />
                    </div>
                    {shot.caption ? (
                      <p className="mt-1 truncate text-xs text-ash">{shot.caption}</p>
                    ) : null}
                  </button>
                ))}
              </div>
            </Panel>
          ) : null}

          {mods.length > 0 ? (
            <Panel>
              <h3 className="font-fraktur text-xl text-parchment mb-3">Mods</h3>
              <Fleuron />
              <ul className="mt-4 divide-y divide-oxblood/20">
                {mods.map((m) => {
                  const inProfile = profile.loadOrder.includes(m.slug);
                  return (
                    <li key={m.id} className="flex items-center justify-between gap-4 py-3">
                      <div className="min-w-0 flex-1">
                        <button
                          type="button"
                          onClick={() => navigate({ to: '/mod/$slug', params: { slug: m.slug } })}
                          className="font-serif-italic text-lg text-parchment hover:text-gilt text-left"
                        >
                          {m.name}
                        </button>
                        <p className="font-mono text-xs text-ash">
                          {m.author ?? 'unknown'}
                          {m.latestVersion ? ` · v${m.latestVersion}` : ''}
                        </p>
                        {m.summary ? (
                          <p className="font-serif-italic text-sm text-smoke mt-1 line-clamp-1">
                            {m.summary}
                          </p>
                        ) : null}
                      </div>
                      <Button
                        type="button"
                        size="sm"
                        variant={inProfile ? 'default' : 'primary'}
                        onClick={() => installOne(m.slug)}
                        disabled={inProfile || installing[m.slug]}
                      >
                        {installing[m.slug] ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : inProfile ? (
                          <CheckIcon className="h-4 w-4" />
                        ) : (
                          <Plus className="h-3.5 w-3.5" />
                        )}
                      </Button>
                    </li>
                  );
                })}
              </ul>
            </Panel>
          ) : mods.length === 0 ? (
            <Panel>
              <h3 className="font-fraktur text-xl text-parchment mb-3">Mods</h3>
              <Fleuron />
              <p className="mt-4 font-serif-italic text-ash">This collection has no mods yet.</p>
            </Panel>
          ) : null}
        </div>

        <aside className="space-y-4">
          <Panel>
            <h4 className="font-mono text-ash mb-3">Facts</h4>
            <dl className="space-y-2 text-sm">
              <Row k="Mods" v={String(modCount)} />
              <Row k="Updated" v={new Date(updatedAt).toLocaleDateString()} />
              {ownerName ? <Row k="Author" v={ownerName} /> : null}
            </dl>
          </Panel>
        </aside>
      </div>

      {installError ? (
        <div className="ember-banner flex items-center gap-3 px-4 py-3">
          <span className="font-serif-italic text-base text-crimson flex-1">{installError}</span>
          <Button type="button" size="sm" onClick={() => setInstallError(null)}>
            dismiss
          </Button>
        </div>
      ) : null}

      {lightboxIdx != null && screenshots ? (
        <ScreenshotLightbox
          shots={screenshots}
          idx={lightboxIdx}
          onClose={() => setLightboxIdx(null)}
          onPrev={() => setLightboxIdx((lightboxIdx - 1 + screenshots.length) % screenshots.length)}
          onNext={() => setLightboxIdx((lightboxIdx + 1) % screenshots.length)}
        />
      ) : null}
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="font-mono text-ash">{k}</dt>
      <dd>
        <StatPill value={v} className="tracking-normal" />
      </dd>
    </div>
  );
}

function ScreenshotLightbox({
  shots,
  idx,
  onClose,
  onPrev,
  onNext,
}: {
  shots: { url: string; caption?: string }[];
  idx: number;
  onClose: () => void;
  onPrev: () => void;
  onNext: () => void;
}) {
  const active = shots[idx];
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
      else if (e.key === 'ArrowLeft') onPrev();
      else if (e.key === 'ArrowRight') onNext();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, onPrev, onNext]);

  if (!active) return null;

  return (
    <dialog
      open
      aria-label={active.caption || `Screenshot ${idx + 1}`}
      className="fixed inset-0 z-[90] bg-pitch/95"
    >
      <div className="absolute inset-0 overflow-y-auto">
        <button
          type="button"
          onClick={onClose}
          className="absolute inset-0 h-full w-full cursor-default"
          aria-label="Close preview"
        />
        <div className="pointer-events-none relative flex min-h-full items-center justify-center px-4 py-16 sm:px-20">
          <figure
            onClick={(e) => e.stopPropagation()}
            className="pointer-events-auto flex w-full max-w-6xl flex-col items-center gap-4"
          >
            <img
              src={active.url}
              alt={active.caption || `Screenshot ${idx + 1}`}
              className="max-w-full rounded-md object-contain shadow-2xl"
            />
            <figcaption className="max-w-3xl text-center text-sm text-ash">
              {active.caption || `Screenshot ${idx + 1} of ${shots.length}`}
            </figcaption>
            <p className="font-mono text-xs text-ash/70">
              {idx + 1} / {shots.length}
            </p>
          </figure>
        </div>
      </div>
      <button
        type="button"
        onClick={onClose}
        className="fixed right-4 top-4 z-20 rounded-md bg-oxblood/60 p-2 text-parchment hover:bg-oxblood"
        aria-label="Close"
      >
        <X className="h-5 w-5" />
      </button>
      {shots.length > 1 ? (
        <>
          <button
            type="button"
            onClick={onPrev}
            className="fixed left-2 sm:left-4 top-1/2 z-20 -translate-y-1/2 rounded-md bg-oxblood/60 p-3 text-parchment hover:bg-oxblood"
            aria-label="Previous"
          >
            <ChevronLeft className="h-6 w-6" />
          </button>
          <button
            type="button"
            onClick={onNext}
            className="fixed right-2 sm:right-4 top-1/2 z-20 -translate-y-1/2 rounded-md bg-oxblood/60 p-3 text-parchment hover:bg-oxblood"
            aria-label="Next"
          >
            <ChevronRight className="h-6 w-6" />
          </button>
        </>
      ) : null}
    </dialog>
  );
}
