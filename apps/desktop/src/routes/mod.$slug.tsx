import { ApiError } from '@rsmm/api-client';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router';
import { ArrowLeft, ChevronLeft, ChevronRight, ExternalLink, Globe, Plus, Trash2, X } from 'lucide-react';
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
import { api } from '../lib/api';
import { getApiUrl } from '../lib/api-url';
import { inTauri } from '../lib/platform';
import { installModVersion, listLocalMods } from '../lib/rsmm';
import { toEmbedUrl } from '../lib/video-embed';
import { activeProfile, isEnabledIn, useApp } from '../store';

export const Route = createFileRoute('/mod/$slug')({
  component: ModDetailPage,
});

function ModDetailPage() {
  const { slug } = Route.useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data, error, isLoading } = useQuery({
    queryKey: ['mods', 'detail', slug],
    queryFn: () => api.mods.get(slug),
    retry: (count, err) => (err instanceof ApiError && err.status === 404 ? false : count < 1),
    staleTime: 30_000,
    enabled: inTauri(),
  });

  const liveBySlug = useApp((s) => Object.values(s.localMods).find((m) => m.slug === slug));
  const installed = useApp((s) => s.installed);
  const profile = useApp(activeProfile);
  const installMod = useApp((s) => s.installMod);
  const uninstall = useApp((s) => s.uninstallMod);
  const syncLocalMods = useApp((s) => s.syncLocalMods);
  const [versionBusy, setVersionBusy] = useState<string | null>(null);
  const [versionError, setVersionError] = useState<string | null>(null);

  if (isLoading) {
    return (
      <div className="space-y-6 animate-pulse" aria-busy="true">
        <div className="h-8 w-24 bg-oxblood/15 rounded" />
        <div className="aspect-[21/9] w-full bg-oxblood/20 rounded" />
        <div className="h-10 w-2/3 bg-oxblood/25 rounded" />
        <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
          <div className="md:col-span-2 space-y-3">
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
        <Button type="button" size="sm" onClick={() => navigate({ to: '/browse' })}>
          ← back
        </Button>
        <p className="font-serif-italic text-parchment">No mod matches “{slug}”.</p>
      </div>
    );
  }

  const name = apiMod?.name ?? liveBySlug?.name ?? slug;
  const author = apiMod?.author ?? liveBySlug?.author ?? 'unknown';
  const summary = apiMod?.summary ?? liveBySlug?.summary ?? '';
  const description = apiMod?.description ?? liveBySlug?.description ?? '';
  const category = apiMod?.category ?? liveBySlug?.category ?? null;
  const tags = apiMod?.tags ?? liveBySlug?.tags ?? [];
  const rating = apiMod?.rating ?? null;
  const downloads = apiMod?.downloads ?? 0;
  const imageUrl = apiMod?.imageUrl ?? liveBySlug?.image ?? null;
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
  const dependencies = apiMod?.dependencies ?? {};

  const markdown =
    liveBySlug?.markdown ??
    (description ? `# ${name}\n\n${description}` : `# ${name}\n\n${summary || ''}`);
  const sizeBytes = latestVersion?.sizeBytes ?? null;
  const apiBase = getApiUrl().replace(/\/+$/, '');

  const installVersion = useCallback(
    async (version: string) => {
      setVersionBusy(version);
      setVersionError(null);
      try {
        await installModVersion(slug, version);
        const mods = await listLocalMods();
        if (mods) syncLocalMods(mods);
        await queryClient.invalidateQueries({ queryKey: ['mods', 'detail', slug] });
      } catch (err) {
        setVersionError(err instanceof Error ? err.message : 'Failed to install this version.');
      } finally {
        setVersionBusy(null);
      }
    },
    [queryClient, slug, syncLocalMods],
  );

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
        subtitle={`${author}${localVersion ? ` · v${localVersion}` : ''}${
          outdated && apiLatest
            ? ` → ${apiLatest}`
            : apiLatest && !localVersion
              ? ` · v${apiLatest}`
              : ''
        }`}
        right={
          installedHere && liveBySlug ? (
            <div className="flex items-center gap-2">
              <MonoTag tone={enabled ? 'crimson' : 'default'}>
                {enabled ? 'enabled' : 'disabled'}
              </MonoTag>
              <Button type="button" variant="danger" onClick={() => uninstall(liveBySlug.id)}>
                <Trash2 className="h-4 w-4" /> Uninstall
              </Button>
            </div>
          ) : (
            <Button
              type="button"
              variant="primary"
              onClick={() => installMod(apiMod?.id ?? liveBySlug?.id ?? slug)}
            >
              <Plus className="h-4 w-4" /> Install
            </Button>
          )
        }
      />

      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        <div className="space-y-4 md:col-span-2">
          <Panel>
            <h3 className="font-fraktur text-xl text-parchment mb-3">About</h3>
            <Fleuron />
            <Markdown source={markdown} className="mt-4" />
          </Panel>

          {videos.length > 0 || screenshots.length > 0 ? (
            <Panel>
              <h3 className="font-fraktur text-xl text-parchment mb-3">Gallery</h3>
              <Fleuron />
              <div className="mt-4 space-y-4">
                {videos.length > 0 ? (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {videos.map((url) => {
                      const embed = toEmbedUrl(url);
                      return (
                        <div
                          key={url}
                          className="aspect-video overflow-hidden rounded border border-oxblood/30 bg-pitch"
                        >
                          {embed ? (
                            <iframe
                              src={embed}
                              title={`${name} video`}
                              loading="lazy"
                              allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                              allowFullScreen
                              className="h-full w-full"
                            />
                          ) : (
                            <a
                              href={url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="flex h-full w-full items-center justify-center break-all px-3 text-sm text-parchment underline"
                            >
                              {url}
                            </a>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ) : null}
                {screenshots.length > 0 ? (
                  <ScreenshotGallery shots={screenshots} modName={name} />
                ) : null}
              </div>
            </Panel>
          ) : null}

          {liveBySlug?.changelog ? (
            <Panel>
              <h3 className="font-fraktur text-xl text-parchment mb-3">Changelog</h3>
              <Fleuron />
              <pre className="font-mono mt-4 whitespace-pre-wrap text-ash">
                {liveBySlug.changelog}
              </pre>
            </Panel>
          ) : null}

          {data?.versions && data.versions.length > 0 ? (
            <Panel>
              <h3 className="font-fraktur text-xl text-parchment mb-3">Versions</h3>
              <Fleuron />
              {versionError ? (
                <div className="ember-banner mb-3 px-4 py-2 text-sm text-ash">{versionError}</div>
              ) : null}
              <ul className="mt-4 divide-y divide-oxblood/20">
                {data.versions.map((v) => (
                  <li key={v.id} className="flex items-center justify-between gap-4 py-2">
                    <div className="flex items-baseline gap-3">
                      <span className="font-mono text-sm text-parchment">v{v.version}</span>
                      <span className="font-mono text-xs text-ash">
                        {new Date(v.createdAt).toLocaleDateString()}
                      </span>
                      {v.sizeBytes ? (
                        <span className="font-mono text-xs text-ash">
                          {(v.sizeBytes / 1024 / 1024).toFixed(2)} MB
                        </span>
                      ) : null}
                    </div>
                    <div className="flex items-center gap-2">
                      <a
                        href={`${apiBase}/api/mods/${slug}/${v.version}/download`}
                        className="font-mono text-xs text-gilt hover:underline"
                      >
                        download
                      </a>
                      {localVersion === v.version ? (
                        <MonoTag tone="gilt">current</MonoTag>
                      ) : (
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => installVersion(v.version)}
                          disabled={versionBusy === v.version}
                        >
                          {installedHere ? 'downgrade' : 'install'}
                        </Button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}
        </div>

        <aside className="space-y-4">
          <Panel>
            <h4 className="font-mono text-ash mb-3">Facts</h4>
            <dl className="space-y-2 text-sm">
              {category ? <Row k="Category" v={category} /> : null}
              {rating != null ? <Row k="Rating" v={`${rating.toFixed(1)} ★`} /> : null}
              <Row k="Downloads" v={downloads.toLocaleString()} />
              {sizeBytes != null ? (
                <Row k="Size" v={`${(sizeBytes / 1024 / 1024).toFixed(2)} MB`} />
              ) : null}
              {apiLatest ? <Row k="Latest" v={`v${apiLatest}`} /> : null}
              {license ? <Row k="License" v={license} /> : null}
            </dl>
          </Panel>

          {repoUrl || homepageUrl ? (
            <Panel>
              <h4 className="font-mono text-ash mb-3">Links</h4>
              <ul className="space-y-2 text-sm">
                {homepageUrl ? (
                  <li>
                    <a
                      href={homepageUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 text-parchment underline-offset-2 hover:underline"
                    >
                      <Globe className="h-3.5 w-3.5" /> Homepage
                      <ExternalLink className="h-3 w-3 opacity-60" />
                    </a>
                  </li>
                ) : null}
                {repoUrl ? (
                  <li>
                    <a
                      href={repoUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 text-parchment underline-offset-2 hover:underline"
                    >
                      <ExternalLink className="h-3.5 w-3.5" /> Repository
                    </a>
                  </li>
                ) : null}
              </ul>
            </Panel>
          ) : null}

          {tags.length > 0 ? (
            <Panel>
              <h4 className="font-mono text-ash mb-3">Tags</h4>
              <div className="flex flex-wrap gap-1.5">
                {tags.map((t) => (
                  <MonoTag key={t}>{t}</MonoTag>
                ))}
              </div>
            </Panel>
          ) : null}

          {Object.keys(dependencies).length > 0 ? (
            <Panel>
              <h4 className="font-mono text-ash mb-3">Requires</h4>
              <ul className="space-y-1.5 text-sm">
                {Object.entries(dependencies).map(([depSlug, range]) => {
                  const depInstalled = Object.values(useApp.getState().localMods).some(
                    (m) => m.slug === depSlug,
                  );
                  return (
                    <li key={depSlug} className="flex items-baseline justify-between gap-2">
                      <Link
                        to="/mod/$slug"
                        params={{ slug: depSlug }}
                        className="text-parchment hover:text-gilt hover:underline"
                      >
                        {depSlug}
                      </Link>
                      <span className="flex items-center gap-1.5">
                        <code className="font-mono text-xs text-ash">{range}</code>
                        {depInstalled ? (
                          <MonoTag tone="gilt">ok</MonoTag>
                        ) : (
                          <MonoTag tone="crimson">missing</MonoTag>
                        )}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </Panel>
          ) : null}
        </aside>
      </div>
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

interface Screenshot {
  url: string;
  caption?: string;
}

function ScreenshotGallery({ shots, modName }: { shots: Screenshot[]; modName: string }) {
  const [idx, setIdx] = useState<number | null>(null);
  const close = useCallback(() => setIdx(null), []);
  const prev = useCallback(() => {
    setIdx((i) => (i == null ? i : (i - 1 + shots.length) % shots.length));
  }, [shots.length]);
  const next = useCallback(() => {
    setIdx((i) => (i == null ? i : (i + 1) % shots.length));
  }, [shots.length]);
  useEffect(() => {
    if (idx == null) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') close();
      else if (e.key === 'ArrowLeft') prev();
      else if (e.key === 'ArrowRight') next();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [idx, close, prev, next]);

  const active = idx != null ? shots[idx] : null;

  return (
    <>
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {shots.map((shot, i) => (
          <li key={shot.url}>
            <button
              type="button"
              onClick={() => setIdx(i)}
              className="group block w-full text-left"
            >
              <div className="aspect-video overflow-hidden rounded border border-oxblood/30 bg-pitch">
                <img
                  src={shot.url}
                  alt={shot.caption || `${modName} screenshot ${i + 1}`}
                  loading="lazy"
                  className="h-full w-full object-cover transition-opacity group-hover:opacity-90"
                />
              </div>
              {shot.caption ? (
                <p className="mt-1 truncate text-xs text-ash">{shot.caption}</p>
              ) : null}
            </button>
          </li>
        ))}
      </ul>
      {active ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={active.caption || `${modName} screenshot ${(idx ?? 0) + 1}`}
          className="fixed inset-0 z-[90] bg-pitch/95"
        >
          <div className="absolute inset-0 overflow-y-auto">
            <button
              type="button"
              onClick={close}
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
                  alt={active.caption || `${modName} screenshot ${(idx ?? 0) + 1}`}
                  className="max-w-full rounded-md object-contain shadow-2xl"
                />
                <figcaption className="max-w-3xl text-center text-sm text-ash">
                  {active.caption || `Screenshot ${(idx ?? 0) + 1} of ${shots.length}`}
                </figcaption>
                <p className="font-mono text-xs text-ash/70">
                  {(idx ?? 0) + 1} / {shots.length}
                </p>
              </figure>
            </div>
          </div>
          <button
            type="button"
            onClick={close}
            className="fixed right-4 top-4 z-20 rounded-md bg-oxblood/60 p-2 text-parchment hover:bg-oxblood"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
          {shots.length > 1 ? (
            <>
              <button
                type="button"
                onClick={prev}
                className="fixed left-2 sm:left-4 top-1/2 z-20 -translate-y-1/2 rounded-md bg-oxblood/60 p-3 text-parchment hover:bg-oxblood"
                aria-label="Previous"
              >
                <ChevronLeft className="h-6 w-6" />
              </button>
              <button
                type="button"
                onClick={next}
                className="fixed right-2 sm:right-4 top-1/2 z-20 -translate-y-1/2 rounded-md bg-oxblood/60 p-3 text-parchment hover:bg-oxblood"
                aria-label="Next"
              >
                <ChevronRight className="h-6 w-6" />
              </button>
            </>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
