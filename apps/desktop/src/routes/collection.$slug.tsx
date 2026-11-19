import { ApiError, isRateLimited } from '@rsmm/api-client';
import { ProgressBar } from '@rsmm/ui';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createFileRoute, useCanGoBack, useNavigate, useRouter } from '@tanstack/react-router';
import { ArrowLeft, Download, Loader2, Plus, UserPlus } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  CopyButton,
  Cover,
  CoverPlaceholder,
  Fleuron,
  Markdown,
  MonoTag,
  Panel,
  SectionHeader,
  StatPill,
} from '../components/chrome';
import { InstalledState } from '../components/installed-state';
import { ListingRatingSummary, ListingReviews } from '../components/listing-reviews';
import { ScreenshotLightbox } from '../components/screenshot-lightbox';
import { useToast } from '../components/toast';
import { useDialog } from '../components/toast';
import { api, describeApiError, logApiError } from '../lib/api';
import { useSession } from '../lib/auth-client';
import { useT } from '../lib/i18n-react';
import {
  installModIntoProfile,
  modIdsOf,
  resolveInstallTarget,
  syncInstalledMods,
} from '../lib/profile-mods';
import { listLocalModsForProfile } from '../lib/rsmm';
import { activeProfile, useApp } from '../store';

export const Route = createFileRoute('/collection/$slug')({
  component: CollectionDetailPage,
});

function CollectionDetailPage() {
  const t = useT();
  const { data: session } = useSession();
  const { slug } = Route.useParams();
  const navigate = useNavigate();
  const router = useRouter();
  const canGoBack = useCanGoBack();

  /**
   * Return the way the user arrived. /browse is only correct when there is no
   * history to step back through (a deep link, a fresh window) — navigating
   * there unconditionally sent anyone who opened this from elsewhere to a page
   * they had never been on.
   */
  const goBack = () => {
    if (canGoBack) router.history.back();
    else navigate({ to: '/browse' });
  };
  const queryClient = useQueryClient();
  const toast = useToast();
  const dialog = useDialog();
  const profile = useApp(activeProfile);
  const createProfile = useApp((s) => s.createProfile);
  const [installing, setInstalling] = useState<Record<string, boolean>>({});
  const [installAllRunning, setInstallAllRunning] = useState(false);
  const [installProgress, setInstallProgress] = useState({ value: 0, max: 0 });
  const [installError, setInstallError] = useState<string | null>(null);
  const [lightboxIdx, setLightboxIdx] = useState<number | null>(null);

  const { data, error, isLoading } = useQuery({
    queryKey: ['collections', 'detail', slug, session?.user.id ?? null],
    queryFn: () => api.collections.get(slug),
    retry: (count, err) => (err instanceof ApiError && err.status === 404 ? false : count < 1),
    staleTime: 30_000,
  });

  // A failed fetch is not a 404 — distinguish "collection does not
  // exist" from "the index could not be reached" so network/CSP
  // problems are not reported as a missing collection.
  const fetchFailed = Boolean(error) && !(error instanceof ApiError && error.status === 404);
  useEffect(() => {
    if (fetchFailed) logApiError('collection-detail', error);
  }, [fetchFailed, error]);

  async function installOne(modSlug: string) {
    setInstallError(null);
    setInstalling((m) => ({ ...m, [modSlug]: true }));
    try {
      // Capture the target so the download and profile entry use one folder.
      await installModIntoProfile(modSlug, resolveInstallTarget(profile.id));
      await queryClient.invalidateQueries({ queryKey: ['mods', 'list'] });
      toast.push(t('Added {slug} to profile', { slug: modSlug }), 'success');
    } catch (err) {
      if (isRateLimited(err)) {
        toast.push(
          t('Rate limited — try again in {seconds}s', { seconds: err.retryAfter ?? 60 }),
          'error',
        );
      } else {
        setInstallError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setInstalling((m) => ({ ...m, [modSlug]: false }));
    }
  }

  async function installAll() {
    if (!data?.mods) return;
    setInstallAllRunning(true);
    setInstallError(null);
    setInstallProgress({ value: 0, max: data.mods.length });
    const targetProfileId = resolveInstallTarget(profile.id);
    // List the target's own folder once and keep the whole batch in it.
    let onDisk: Map<string, string>;
    try {
      onDisk = modIdsOf(await listLocalModsForProfile(targetProfileId));
    } catch (err) {
      setInstallError(err instanceof Error ? err.message : String(err));
      setInstallAllRunning(false);
      setInstallProgress({ value: 0, max: 0 });
      return;
    }
    const completedSlugs: string[] = [];
    for (const [idx, m] of data.mods.entries()) {
      setInstalling((prev) => ({ ...prev, [m.slug]: true }));
      try {
        await installModIntoProfile(m.slug, targetProfileId, { onDisk });
        completedSlugs.push(m.slug);
      } catch (err) {
        // Earlier downloads still succeeded. Resolve their folder ids even
        // when a later item failed, while preserving the original error.
        if (completedSlugs.length > 0) {
          const local = await listLocalModsForProfile(targetProfileId).catch(() => null);
          if (local) syncInstalledMods(local, targetProfileId, completedSlugs);
        }
        setInstallError(err instanceof Error ? err.message : String(err));
        setInstalling((prev) => ({ ...prev, [m.slug]: false }));
        setInstallAllRunning(false);
        setInstallProgress({ value: 0, max: 0 });
        return;
      }
      setInstalling((prev) => ({ ...prev, [m.slug]: false }));
      setInstallProgress({ value: idx + 1, max: data.mods.length });
    }
    const local = await listLocalModsForProfile(targetProfileId);
    if (local) syncInstalledMods(local, targetProfileId, completedSlugs);
    await queryClient.invalidateQueries({ queryKey: ['mods', 'list'] });
    setInstallAllRunning(false);
    setInstallProgress({ value: 0, max: 0 });
    toast.push(
      t.n(
        data.mods.length,
        'Installed {n} mod to current profile',
        'Installed {n} mods to current profile',
      ),
      'success',
    );
  }

  async function installAsProfile() {
    if (!data?.mods || data.mods.length === 0) {
      toast.push(t('This collection has no mods to install.'), 'error');
      return;
    }
    const name = await dialog.prompt({
      title: t('New profile from collection'),
      initialValue: data.name,
      placeholder: t('Profile name'),
    });
    if (!name) return;
    setInstallAllRunning(true);
    setInstallError(null);
    setInstallProgress({ value: 0, max: data.mods.length });
    const newProfileId = createProfile(name);
    const completedSlugs: string[] = [];
    try {
      // A new profile's folder starts empty (or does not exist yet).
      const onDisk = modIdsOf(await listLocalModsForProfile(newProfileId));
      for (const [idx, m] of data.mods.entries()) {
        setInstalling((prev) => ({ ...prev, [m.slug]: true }));
        await installModIntoProfile(m.slug, newProfileId, { onDisk });
        completedSlugs.push(m.slug);
        setInstalling((prev) => ({ ...prev, [m.slug]: false }));
        setInstallProgress({ value: idx + 1, max: data.mods.length });
      }
    } catch (err) {
      if (completedSlugs.length > 0) {
        const local = await listLocalModsForProfile(newProfileId).catch(() => null);
        if (local) syncInstalledMods(local, newProfileId, completedSlugs);
      }
      setInstallError(err instanceof Error ? err.message : String(err));
      setInstallAllRunning(false);
      setInstallProgress({ value: 0, max: 0 });
      return;
    }
    const local = await listLocalModsForProfile(newProfileId);
    if (local) syncInstalledMods(local, newProfileId, completedSlugs);
    await queryClient.invalidateQueries({ queryKey: ['mods', 'list'] });
    setInstallAllRunning(false);
    setInstallProgress({ value: 0, max: 0 });
    toast.push(
      t.n(
        data.mods.length,
        'Created profile "{name}" with {n} mod',
        'Created profile "{name}" with {n} mods',
        { name },
      ),
      'success',
    );
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
        <Button type="button" size="sm" onClick={goBack}>
          ← {t('back')}
        </Button>
        {fetchFailed ? (
          <div className="ember-banner flex flex-col gap-2 px-4 py-3">
            <div className="flex items-center gap-3">
              <span className="font-serif-italic text-base">
                {t('Could not load this collection.')}
              </span>
              <CopyButton value={describeApiError(error)} />
            </div>
            <p className="font-serif-italic text-sm text-ash">{describeApiError(error)}</p>
          </div>
        ) : (
          <p className="font-serif-italic text-parchment">
            {t('No collection matches "{slug}".', { slug })}
          </p>
        )}
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
      <Button type="button" size="sm" onClick={goBack}>
        <ArrowLeft className="h-3.5 w-3.5" /> {t('back')}
      </Button>

      {imageUrl ? (
        <Cover
          src={imageUrl}
          alt={t('{name} cover art', { name })}
          caption={`${slug}-hero.png`}
          className="aspect-[21/9]"
        />
      ) : (
        <CoverPlaceholder caption={`${slug}-hero.png`} className="aspect-[21/9]" />
      )}

      <SectionHeader
        title={name}
        subtitle={`${ownerName ?? t('unknown')} · ${t.n(
          modCount,
          '{n} mod',
          '{n} mods',
        )} · ${new Date(updatedAt).toLocaleDateString(t.tag)}`}
        right={
          <div className="flex flex-wrap items-center justify-end gap-2">
            {allInstalled ? (
              <MonoTag tone="gilt">{t('all installed')}</MonoTag>
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
                      <Loader2 className="h-4 w-4 animate-spin" /> {t('installing…')}
                    </>
                  ) : someInstalled ? (
                    <>
                      <Plus className="h-4 w-4" /> {t('install rest')}
                    </>
                  ) : (
                    <>
                      <Download className="h-4 w-4" /> {t('install all')}
                    </>
                  )}
                </Button>
                <Button
                  type="button"
                  variant="default"
                  onClick={installAsProfile}
                  disabled={installAllRunning}
                >
                  <UserPlus className="h-4 w-4" /> {t('new profile')}
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
          label={t('Installing {done}/{total}…', {
            done: installProgress.value,
            total: installProgress.max,
          })}
        />
      ) : null}

      <ListingRatingSummary target="collection" slug={slug} />

      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        <div className="space-y-4 md:col-span-2">
          {markdownBody ? (
            <Panel>
              <h3 className="font-fraktur text-xl text-parchment mb-3">{t('About')}</h3>
              <Fleuron />
              <Markdown source={markdownBody} className="mt-4" />
            </Panel>
          ) : null}

          {screenshots && screenshots.length > 0 ? (
            <Panel>
              <h3 className="font-fraktur text-xl text-parchment mb-3">{t('Gallery')}</h3>
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
                        alt={shot.caption || t('Screenshot {n}', { n: i + 1 })}
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
              <h3 className="font-fraktur text-xl text-parchment mb-3">{t('Mods')}</h3>
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
                          {m.author ?? t('unknown')}
                          {m.latestVersion ? ` · v${m.latestVersion}` : ''}
                        </p>
                        {m.summary ? (
                          <p className="font-serif-italic text-sm text-smoke mt-1 line-clamp-1">
                            {m.summary}
                          </p>
                        ) : null}
                      </div>
                      {inProfile && !installing[m.slug] ? (
                        <InstalledState />
                      ) : (
                        <Button
                          type="button"
                          size="sm"
                          variant="primary"
                          onClick={() => installOne(m.slug)}
                          disabled={installing[m.slug]}
                          aria-label={t('Install')}
                        >
                          {installing[m.slug] ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Plus className="h-3.5 w-3.5" />
                          )}
                        </Button>
                      )}
                    </li>
                  );
                })}
              </ul>
            </Panel>
          ) : mods.length === 0 ? (
            <Panel>
              <h3 className="font-fraktur text-xl text-parchment mb-3">{t('Mods')}</h3>
              <Fleuron />
              <p className="mt-4 font-serif-italic text-ash">
                {t('This collection has no mods yet.')}
              </p>
            </Panel>
          ) : null}
          <ListingReviews
            target="collection"
            slug={slug}
            isAuthor={data.ownerId === session?.user.id}
          />
        </div>

        <aside className="space-y-4">
          <Panel>
            <h4 className="font-mono text-ash mb-3">{t('Facts')}</h4>
            <dl className="space-y-2 text-sm">
              <Row k={t('Mods')} v={String(modCount)} />
              <Row k={t('Updated')} v={new Date(updatedAt).toLocaleDateString(t.tag)} />
              {ownerName ? <Row k={t('Author')} v={ownerName} /> : null}
            </dl>
          </Panel>
        </aside>
      </div>

      {installError ? (
        <div className="ember-banner flex items-center gap-3 px-4 py-3">
          <span className="font-serif-italic text-base text-crimson flex-1">{installError}</span>
          <Button type="button" size="sm" onClick={() => setInstallError(null)}>
            {t('dismiss')}
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
