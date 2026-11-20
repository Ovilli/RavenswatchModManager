import { ApiError } from '@rsmm/api-client';
import { hasPrivateOnlyTag, isPrivateOnlyTag } from '@rsmm/schemas';
import { RegistryDetailLayout, RegistryListingGallery, getRegistryMedia } from '@rsmm/ui';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useCanGoBack, useNavigate, useRouter } from '@tanstack/react-router';
import {
  ArrowLeft,
  ArrowRight,
  ChevronDown,
  Download,
  ExternalLink,
  Plus,
  Trash2,
} from 'lucide-react';
import { type ReactNode, useCallback, useEffect, useState } from 'react';
import { api, describeApiError, logApiError } from '../lib/api';
import { getApiUrl } from '../lib/api-url';
import { useSession } from '../lib/auth-client';
import { LIBRARY_PREVIEW } from '../lib/browser-preview';
import { useT } from '../lib/i18n-react';
import { inTauri } from '../lib/platform';
import { installModIntoProfile, resolveInstallTarget } from '../lib/profile-mods';
import { registryGalleryLabels, registryMediaLabels } from '../lib/registry-labels';
import {
  disableHookWarning,
  installModVersion,
  listLocalMods,
  uninstallLocalMod,
} from '../lib/rsmm';
import { activeProfile, isEnabledIn, useApp } from '../store';
import { Button, CopyButton, InkSwitch, Markdown, MonoTag } from './chrome';
import { useConfirmDisableHook } from './disable-hook-consent';
import { ListingRatingSummary, ListingReviews } from './listing-reviews';
import { OverlayButton } from './overlay-button';
import { PrivateGamesOnlyBadge } from './private-games-only-badge';
import { useDialog, useToast } from './toast';
import { useModToggle } from './use-mod-toggle';

/** Full mod details, reached from both Browse and Library. */
export function ModDetail({ slug }: { slug: string }) {
  const t = useT();
  const { data: session } = useSession();
  const navigate = useNavigate();
  const router = useRouter();
  const canGoBack = useCanGoBack();

  /**
   * Return the way the user arrived.
   *
   * This used to navigate to /browse unconditionally, which sent anyone who
   * opened a mod from the Library to the store index instead — a page they had
   * never been on. /browse is only the right guess when there is no history to
   * step back through, which happens on a deep link or a fresh window.
   */
  const goBack = () => {
    if (canGoBack) router.history.back();
    else navigate({ to: '/browse' });
  };
  const queryClient = useQueryClient();
  const toast = useToast();
  const dialog = useDialog();

  const { data, error, isLoading } = useQuery({
    queryKey: ['mods', 'detail', slug, session?.user.id ?? null],
    queryFn: () => api.mods.get(slug),
    retry: (count, err) => (err instanceof ApiError && err.status === 404 ? false : count < 1),
    staleTime: 30_000,
    enabled: inTauri() || LIBRARY_PREVIEW,
  });

  const liveBySlug = useApp((s) => Object.values(s.localMods).find((m) => m.slug === slug));
  const installed = useApp((s) => s.installed);
  const profile = useApp(activeProfile);
  const installMod = useApp((s) => s.installMod);
  const syncLocalMods = useApp((s) => s.syncLocalMods);
  const [versionBusy, setVersionBusy] = useState<string | null>(null);
  const [versionError, setVersionError] = useState<string | null>(null);
  const { toggle } = useModToggle();

  // A failed index fetch is not a 404 — without this the page falls
  // through to "No mod matches", hiding network/CSP problems entirely.
  const fetchFailed = Boolean(error) && !(error instanceof ApiError && error.status === 404);
  useEffect(() => {
    if (fetchFailed) logApiError('mod-detail', error);
  }, [fetchFailed, error]);

  const activeProfileId = useApp((s) => s.activeProfileId);
  const refreshLocalMods = useCallback(async () => {
    const mods = await listLocalMods();
    if (mods) {
      syncLocalMods(mods);
      queryClient.setQueryData(['rsmm', 'list', activeProfileId], mods);
    }
  }, [syncLocalMods, queryClient, activeProfileId]);

  const installVersion = useCallback(
    async (version: string, addToProfile = false) => {
      setVersionBusy(version);
      setVersionError(null);
      try {
        if (addToProfile) {
          // Capture the profile before downloading and check the result:
          // a failed install is `ok: false`, not a throw.
          await installModIntoProfile(slug, resolveInstallTarget(), { version });
        } else {
          const result = await installModVersion(slug, version);
          if (!result || !result.ok) {
            throw new Error(result?.error ?? t('Failed to install this version.'));
          }
          const mods = await listLocalMods();
          if (mods) syncLocalMods(mods);
        }
        await queryClient.invalidateQueries({ queryKey: ['mods', 'detail', slug] });
      } catch (err) {
        setVersionError(err instanceof Error ? err.message : t('Failed to install this version.'));
      } finally {
        setVersionBusy(null);
      }
    },
    [queryClient, slug, syncLocalMods, t],
  );

  const uninstallModStore = useApp((s) => s.uninstallMod);
  const confirmDisableHook = useConfirmDisableHook();
  const uninstall = useCallback(
    async (modId: string) => {
      // Deleting the mod from disk has no undo.
      const ok = await dialog.confirm({
        title: t('Uninstall {name}?', { name: liveBySlug?.name ?? modId }),
        body: t('This deletes the mod from disk. There is no undo.'),
        confirmLabel: t('Uninstall'),
        destructive: true,
      });
      if (!ok) return;
      setVersionBusy(modId);
      setVersionError(null);
      try {
        const result = await uninstallLocalMod(modId, confirmDisableHook);
        if (!result || !result.ok) {
          throw new Error(result?.error || t('Failed to uninstall {id}', { id: modId }));
        }
        uninstallModStore(modId);
        await refreshLocalMods();
        await queryClient.invalidateQueries({ queryKey: ['mods', 'detail', slug] });
        const warning = disableHookWarning(result);
        if (warning) toast.push(warning, 'error');
        else toast.push(t('Mod uninstalled.'), 'success');
      } catch (err) {
        const message = err instanceof Error ? err.message : t('Failed to uninstall mod.');
        setVersionError(message);
        toast.push(message, 'error');
      } finally {
        setVersionBusy(null);
      }
    },
    [
      confirmDisableHook,
      dialog,
      liveBySlug?.name,
      queryClient,
      refreshLocalMods,
      slug,
      t,
      toast,
      uninstallModStore,
    ],
  );

  if (isLoading) {
    return (
      <div className="space-y-6 animate-pulse" aria-busy="true">
        <div className="h-8 w-24 bg-oxblood/15 rounded" />
        <div className="aspect-[21/9] w-full bg-oxblood/20 rounded" />
        <div className="h-10 w-2/3 bg-oxblood/25 rounded" />
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2 space-y-3">
            <div className="h-4 w-full bg-oxblood/15 rounded" />
            <div className="h-4 w-5/6 bg-oxblood/15 rounded" />
            <div className="h-4 w-4/6 bg-oxblood/15 rounded" />
          </div>
          <div className="h-40 bg-oxblood/10 rounded" />
        </div>
      </div>
    );
  }

  const apiMod = data?.mod;
  const latestVersion = data?.versions?.[0];

  if (!apiMod && !liveBySlug) {
    return (
      <div className="space-y-4">
        <Button type="button" size="sm" onClick={goBack}>
          ← {t('back')}
        </Button>
        {fetchFailed ? (
          <div className="ember-banner flex flex-col gap-2 px-4 py-3">
            <div className="flex items-center gap-3">
              <span className="font-serif-italic text-base">
                {t('Couldn’t load “{slug}” from the index.', { slug })}
              </span>
              <CopyButton value={describeApiError(error)} />
            </div>
            <p className="font-serif-italic text-sm text-ash">{describeApiError(error)}</p>
          </div>
        ) : (
          <p className="font-serif-italic text-parchment">
            {t('No mod matches “{slug}”.', { slug })}
          </p>
        )}
      </div>
    );
  }

  const name = apiMod?.name ?? liveBySlug?.name ?? slug;
  const author = apiMod?.author ?? liveBySlug?.author ?? t('unknown');
  const summary = apiMod?.summary ?? liveBySlug?.summary ?? '';
  const description = apiMod?.description ?? liveBySlug?.description ?? '';
  const category = apiMod?.category ?? liveBySlug?.category ?? null;
  const tags = apiMod?.tags ?? liveBySlug?.tags ?? [];
  const privateOnly = hasPrivateOnlyTag(tags);
  const ordinaryTags = tags.filter((tag) => !isPrivateOnlyTag(tag));
  const rating = apiMod?.rating ?? null;
  const downloads = apiMod?.downloads ?? 0;
  const imageUrl = apiMod?.imageUrl ?? liveBySlug?.image ?? null;
  const nsfw = apiMod?.nsfw ?? liveBySlug?.nsfw ?? false;
  const apiLatest = apiMod?.latestVersion ?? null;
  const localVersion = liveBySlug?.version ?? null;
  const installedHere = liveBySlug ? installed.includes(liveBySlug.id) : false;
  const enabled = installedHere && liveBySlug ? isEnabledIn(profile, liveBySlug.id) : false;
  const outdated = Boolean(localVersion && apiLatest && localVersion !== apiLatest);
  const license = apiMod?.license ?? null;
  const repoUrl = apiMod?.repoUrl ?? null;
  const homepageUrl = apiMod?.homepageUrl ?? null;
  const screenshots = apiMod?.screenshots ?? [];
  const videos = apiMod?.videos ?? [];
  const media = getRegistryMedia({ name, imageUrl, screenshots, videos }, registryMediaLabels(t));
  const dependencies = apiMod?.dependencies ?? {};

  // The store generates a title + summary when no authored Markdown is known.
  // The detail header already supplies that title; prefer the registry's full copy.
  const generatedMarkdown = liveBySlug
    ? `# ${liveBySlug.name}${liveBySlug.summary ? `\n\n${liveBySlug.summary}` : ''}`
    : '';
  const localMarkdown =
    liveBySlug?.markdown !== generatedMarkdown ? liveBySlug?.markdown : undefined;
  const markdown = apiMod?.description?.trim() || localMarkdown || description || summary;
  const sizeBytes = latestVersion?.sizeBytes ?? null;
  const apiBase = getApiUrl().replace(/\/+$/, '');
  const modFolderId = liveBySlug?.id ?? slug;

  const versions = data?.versions ?? [];

  return (
    <div className="space-y-4">
      {fetchFailed ? (
        <div className="ember-banner flex items-center gap-3 px-4 py-2">
          <span className="font-serif-italic text-sm flex-1">
            {t('Index unreachable — showing locally installed data only.')}
          </span>
          <CopyButton value={describeApiError(error)} />
        </div>
      ) : null}

      <RegistryDetailLayout
        as="div"
        className="desktop-mod-detail"
        name={name}
        summary={summary}
        breadcrumbLabel={t('Breadcrumb')}
        breadcrumb={
          <>
            <button type="button" className="mod-back" onClick={goBack}>
              <ArrowLeft size={16} aria-hidden /> {t('back')}
            </button>
            {category ? (
              <>
                <span aria-hidden>/</span>
                <span className="capitalize">{category}</span>
              </>
            ) : null}
          </>
        }
        labels={
          privateOnly || ordinaryTags.length > 0 || nsfw ? (
            <div className="mod-labels">
              {privateOnly ? <PrivateGamesOnlyBadge /> : null}
              {ordinaryTags.length > 0 ? (
                <ul className="mod-tags" aria-label={t('Tags')}>
                  {ordinaryTags.map((tag) => (
                    <li key={tag}>
                      <span>{tag}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
              {nsfw ? <span className="mod-mature-label">{t('Mature content')}</span> : null}
            </div>
          ) : null
        }
        stats={
          apiMod ? (
            <>
              <span>
                <Download size={16} aria-hidden />
                {t('{n} downloads', { n: downloads.toLocaleString(t.tag) })}
              </span>
              <ListingRatingSummary target="mod" slug={slug} fallbackRating={rating} />
            </>
          ) : null
        }
        media={
          <RegistryListingGallery
            media={media}
            name={name}
            nsfw={nsfw}
            labels={registryGalleryLabels(t, name)}
          />
        }
        navigationLabel={t('On this page')}
        navigation={
          <>
            <a href="#about">{t('About this mod')}</a>
            {apiMod ? <a href="#reviews">{t('Reviews')}</a> : null}
            {liveBySlug?.changelog ? <a href="#changelog">{t('Changelog')}</a> : null}
            {/* biome-ignore lint/a11y/useValidAnchor: expands the section before navigating to it. */}
            <a
              href="#version-history"
              onClick={() => {
                const history = document.getElementById('version-history');
                if (history instanceof HTMLDetailsElement) history.open = true;
              }}
            >
              {t('Version history')}
              <span>{versions.length}</span>
            </a>
          </>
        }
        sidebarLabel={t('Mod actions and details')}
        sidebar={
          <>
            <div className="mod-download-card">
              <h2>{installedHere ? t('Installed mod') : t('Get this mod')}</h2>
              {installedHere && liveBySlug ? (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <InkSwitch
                      on={enabled}
                      onClick={() => toggle(liveBySlug.id)}
                      label={enabled ? t('Disable {name}', { name }) : t('Enable {name}', { name })}
                    />
                    <MonoTag tone={enabled ? 'crimson' : 'default'}>
                      {enabled ? t('enabled') : t('disabled')}
                    </MonoTag>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <OverlayButton modId={liveBySlug.id} />
                    <Button
                      type="button"
                      variant="danger"
                      disabled={versionBusy !== null}
                      onClick={() => void uninstall(liveBySlug.id)}
                    >
                      <Trash2 className="h-4 w-4" aria-hidden />
                      {versionBusy === liveBySlug.id ? t('Uninstalling…') : t('Uninstall')}
                    </Button>
                  </div>
                </div>
              ) : (
                <Button
                  type="button"
                  variant="primary"
                  disabled={versionBusy !== null}
                  onClick={() => {
                    const ver = apiLatest ?? latestVersion?.version;
                    if (!liveBySlug && ver && inTauri()) {
                      void installVersion(ver, true);
                      return;
                    }
                    installMod(modFolderId);
                  }}
                >
                  <Plus className="h-4 w-4" aria-hidden />
                  {versionBusy ? t('Installing…') : t('Install')}
                </Button>
              )}
              {versionError ? (
                <div role="alert" className="ember-banner mt-3 px-4 py-2 text-sm text-ash">
                  {versionError}
                </div>
              ) : null}
              {localVersion || apiLatest || sizeBytes != null || license || apiMod?.updatedAt ? (
                <div className="mod-facts">
                  <dl>
                    {localVersion ? (
                      <Row
                        k={t('Installed version')}
                        v={
                          <>
                            v{localVersion}
                            {outdated && apiLatest ? (
                              <>
                                <ArrowRight className="mx-1 inline-block h-3.5 w-3.5" aria-hidden />
                                v{apiLatest}
                              </>
                            ) : null}
                          </>
                        }
                      />
                    ) : null}
                    {apiLatest ? <Row k={t('Latest')} v={`v${apiLatest}`} /> : null}
                    {apiMod?.updatedAt ? (
                      <Row
                        k={t('Updated')}
                        v={
                          <time dateTime={apiMod.updatedAt}>
                            {new Date(apiMod.updatedAt).toLocaleDateString(t.tag)}
                          </time>
                        }
                      />
                    ) : null}
                    {sizeBytes != null ? (
                      <Row k={t('Size')} v={`${(sizeBytes / 1024 / 1024).toFixed(2)} MB`} />
                    ) : null}
                    {license ? <Row k={t('License')} v={license} /> : null}
                  </dl>
                </div>
              ) : null}
            </div>
            <div className="mod-author-row">
              <span className="mod-author-avatar" aria-hidden>
                {author.slice(0, 2).toUpperCase()}
              </span>
              <div className="mod-author">
                <span>{t('Created by')}</span>
                <strong>{author}</strong>
              </div>
            </div>
          </>
        }
      >
        <section id="about" className="mod-section" aria-labelledby="mod-about-heading">
          <h2 id="mod-about-heading">{t('About this mod')}</h2>
          <Markdown source={markdown} className="mod-description" />
          {Object.keys(dependencies).length > 0 ? (
            <div className="mod-requirements">
              <h3>{t('Requires')}</h3>
              <ul>
                {Object.entries(dependencies).map(([depSlug, range]) => {
                  const depInstalled = Object.values(useApp.getState().localMods).some(
                    (m) => m.slug === depSlug,
                  );
                  return (
                    <li key={depSlug}>
                      <Link to="/mod/$slug" params={{ slug: depSlug }}>
                        {depSlug}
                      </Link>
                      <span>{range}</span>
                      <MonoTag tone={depInstalled ? 'gilt' : 'crimson'}>
                        {depInstalled ? t('ok') : t('missing')}
                      </MonoTag>
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}
          {repoUrl || homepageUrl ? (
            <div className="mod-project-links">
              {repoUrl ? (
                <a href={repoUrl} target="_blank" rel="noopener noreferrer">
                  {t('Repository')}
                  <ExternalLink size={14} aria-hidden />
                </a>
              ) : null}
              {homepageUrl ? (
                <a href={homepageUrl} target="_blank" rel="noopener noreferrer">
                  {t('Homepage')}
                  <ExternalLink size={14} aria-hidden />
                </a>
              ) : null}
            </div>
          ) : null}
        </section>
        {apiMod ? (
          <ListingReviews target="mod" slug={slug} isAuthor={apiMod.isAuthor ?? false} />
        ) : null}
        {liveBySlug?.changelog ? (
          <section id="changelog" className="mod-section" aria-labelledby="mod-changelog-heading">
            <h2 id="mod-changelog-heading">{t('Changelog')}</h2>
            <pre className="font-mono whitespace-pre-wrap text-ash">{liveBySlug.changelog}</pre>
          </section>
        ) : null}
        <details id="version-history" className="mod-version-history">
          <summary>
            <div>
              <h2>{t('Version history')}</h2>
              <p>{t('Release notes and previous downloads')}</p>
            </div>
            <span className="mod-version-count">
              {t.n(versions.length, '{n} release', '{n} releases')}
            </span>
            <ChevronDown className="mod-disclosure-chevron" size={20} aria-hidden />
          </summary>
          {versions.length > 0 ? (
            <div className="mod-version-list">
              {versions.map((v) => (
                <div key={v.id} className="mod-version-row">
                  <div className="mod-version-summary">
                    <div>
                      <div className="mod-version-name">
                        <h3>v{v.version}</h3>
                        {localVersion === v.version ? <span>{t('current')}</span> : null}
                      </div>
                      <p>
                        <time dateTime={v.createdAt}>
                          {new Date(v.createdAt).toLocaleDateString(t.tag)}
                        </time>
                        {v.sizeBytes ? (
                          <span>{(v.sizeBytes / 1024 / 1024).toFixed(2)} MB</span>
                        ) : null}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <a
                        href={`${apiBase}/api/mods/${slug}/${v.version}/download`}
                        className="font-mono text-xs text-gilt hover:underline"
                      >
                        {t('download')}
                      </a>
                      {localVersion !== v.version ? (
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => installVersion(v.version, !installedHere)}
                          disabled={versionBusy !== null}
                        >
                          {installedHere ? t('downgrade') : t('install')}
                        </Button>
                      ) : null}
                    </div>
                  </div>
                  {v.changelog ? (
                    <details className="mod-changelog">
                      <summary>{t('Release notes')}</summary>
                      <Markdown source={v.changelog} className="mod-description" />
                    </details>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <p className="mod-history-empty">{t('No version history is available.')}</p>
          )}
        </details>
      </RegistryDetailLayout>
    </div>
  );
}

function Row({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div>
      <dt>{k}</dt>
      <dd>{v}</dd>
    </div>
  );
}
