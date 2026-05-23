'use client';
import { Badge, Spinner, buttonVariants } from '@rsmm/ui';
import type { ModVersion } from '@rsmm/schemas';
import { ApiError } from '@rsmm/api-client';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, ChevronLeft, ChevronRight, Download, ExternalLink, X } from 'lucide-react';
import Link from 'next/link';
import { use, useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../../../lib/api';
import { getApiUrl } from '../../../lib/api-url';
import { toEmbedUrl } from '../../../lib/video-embed';

function getClientOS(): 'windows' | 'macos' | 'linux' {
  if (typeof window === 'undefined') return 'linux';
  const p = navigator.platform.toLowerCase();
  const ua = navigator.userAgent.toLowerCase();
  if (p.includes('win') || ua.includes('windows')) return 'windows';
  if (p.includes('mac') || ua.includes('mac os')) return 'macos';
  return 'linux';
}

const OS_LABELS: Record<string, string> = {
  windows: 'Windows',
  macos: 'macOS',
  linux: 'Linux',
};

export default function ModDetailPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);

  const detail = useQuery({
    queryKey: ['mods', 'detail', slug],
    queryFn: () => api.mods.get(slug),
    retry: (count, err) => (err instanceof ApiError && err.status === 404 ? false : count < 1),
  });

  const os = useMemo(() => getClientOS(), []);

  if (detail.isLoading) {
    return (
      <main className="relative overflow-hidden animate-page-in">
        <div className="container mx-auto flex items-center justify-center px-6 py-24">
          <Spinner />
        </div>
      </main>
    );
  }

  if (detail.isError || !detail.data) {
    const notFound = detail.error instanceof ApiError && detail.error.status === 404;
    return (
      <main className="relative overflow-hidden animate-page-in">
        <div className="container mx-auto space-y-6 px-6 py-12">
          <Link href="/registry" className={buttonVariants({ variant: 'outline', size: 'sm' })}>
            <ArrowLeft className="mr-1.5 h-4 w-4" /> Back to Registry
          </Link>
          <p className="text-muted-foreground">
            {notFound
              ? `No mod matches “${slug}”.`
              : `Cannot reach API (${String(detail.error)})`}
          </p>
        </div>
      </main>
    );
  }

  const { mod, versions } = detail.data;
  const latestVersion = versions[0];
  const apiBase = getApiUrl().replace(/\/+$/, '');
  const downloadUrl = latestVersion ? `${apiBase}/api/mods/${mod.slug}/${latestVersion.version}/download` : null;
  const sizeBytes = latestVersion?.sizeBytes ?? null;

  return (
    <main className="relative overflow-hidden animate-page-in">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,hsl(var(--crimson)/0.08),transparent_50%)]" />
      <div className="relative container mx-auto space-y-6 px-6 py-12">
        <Link href="/registry" className={buttonVariants({ variant: 'outline', size: 'sm' })}>
          <ArrowLeft className="mr-1.5 h-4 w-4" /> Back to Registry
        </Link>

        {mod.imageUrl ? (
          <div className="aspect-[21/9] w-full overflow-hidden rounded-xl border border-border/50 bg-muted">
            <img
              src={mod.imageUrl}
              alt={`${mod.name} cover`}
              className="h-full w-full object-cover"
            />
          </div>
        ) : (
          <div className="aspect-[21/9] w-full rounded-xl border border-border/50 bg-muted" />
        )}

        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-4xl font-bold tracking-tight">{mod.name}</h1>
            <p className="text-sm text-muted-foreground mt-1">
              {mod.author ?? 'unknown'}
              {mod.latestVersion ? ` · v${mod.latestVersion}` : ''}
              {mod.updatedAt ? ` · updated ${new Date(mod.updatedAt).toLocaleDateString()}` : ''}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {downloadUrl ? (
              <a
                href={downloadUrl}
                className={buttonVariants({ variant: 'default', size: 'sm' })}
              >
                <Download className="mr-1.5 h-4 w-4" />
                Download for {OS_LABELS[os]}
              </a>
            ) : null}
            <a
              href={`rsmm://mods/${mod.slug}`}
              className={buttonVariants({ variant: 'outline', size: 'sm' })}
              title="Open in RSMM desktop app"
            >
              <ExternalLink className="mr-1.5 h-4 w-4" />
              Open in App
            </a>
          </div>
        </header>

        {mod.summary ? (
          <p className="text-lg text-muted-foreground max-w-3xl">{mod.summary}</p>
        ) : null}

        <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
          <div className="space-y-4 md:col-span-2">
            <div className="grimoire-card p-6">
              <h2 className="text-xl font-bold tracking-tight mb-4">About</h2>
              <div className="prose prose-sm prose-invert max-w-none text-muted-foreground">
                {mod.summary ?? 'No description available.'}
              </div>
            </div>

            {(mod.screenshots?.length ?? 0) > 0 || (mod.videos?.length ?? 0) > 0 ? (
              <div className="grimoire-card space-y-4 p-6">
                <h2 className="text-xl font-bold tracking-tight">Gallery</h2>
                {(mod.videos?.length ?? 0) > 0 ? (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {mod.videos?.map((url) => {
                      const embed = toEmbedUrl(url);
                      return (
                        <div key={url} className="aspect-video overflow-hidden rounded-md bg-muted">
                          {embed ? (
                            <iframe
                              src={embed}
                              title={`${mod.name} video`}
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
                              className="flex h-full w-full items-center justify-center text-sm underline"
                            >
                              {url}
                            </a>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ) : null}
                {(mod.screenshots?.length ?? 0) > 0 ? (
                  <PublicGallery shots={mod.screenshots ?? []} modName={mod.name} />
                ) : null}
              </div>
            ) : null}

            {versions.length > 0 ? (
              <div className="grimoire-card p-6">
                <h2 className="text-xl font-bold tracking-tight mb-4">Versions</h2>
                <div className="divide-y divide-border/40">
                  {versions.map((v) => (
                    <VersionRow key={v.id} version={v} slug={mod.slug} />
                  ))}
                </div>
              </div>
            ) : null}
          </div>

          <aside className="space-y-4">
            <div className="grimoire-card p-6">
              <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wider">Details</h3>
              <dl className="space-y-2 text-sm">
                {mod.category ? <Row k="Category" v={mod.category} /> : null}
                {mod.rating != null ? <Row k="Rating" v={`${mod.rating.toFixed(1)} ★`} /> : null}
                <Row k="Downloads" v={mod.downloads.toLocaleString()} />
                {sizeBytes != null ? <Row k="Size" v={`${(sizeBytes / 1024 / 1024).toFixed(2)} MB`} /> : null}
                {mod.latestVersion ? <Row k="Latest" v={`v${mod.latestVersion}`} /> : null}
                {mod.license ? <Row k="License" v={mod.license} /> : null}
              </dl>
            </div>

            {mod.tags.length > 0 ? (
              <div className="grimoire-card p-6">
                <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wider">Tags</h3>
                <div className="flex flex-wrap gap-1.5">
                  {mod.tags.map((t) => (
                    <Badge key={t} variant="secondary">{t}</Badge>
                  ))}
                </div>
              </div>
            ) : null}
          </aside>
        </div>
      </div>
    </main>
  );
}

function VersionRow({ version, slug }: { version: ModVersion; slug: string }) {
  const apiBase = (typeof window !== 'undefined' ? getApiUrl() : '').replace(/\/+$/, '');
  const downloadUrl = `${apiBase}/api/mods/${slug}/${version.version}/download`;
  return (
    <div className="flex items-center justify-between gap-4 py-3">
      <div>
        <span className="font-mono text-sm font-medium">v{version.version}</span>
        <span className="ml-3 text-xs text-muted-foreground">
          {new Date(version.createdAt).toLocaleDateString()}
        </span>
        {version.sizeBytes ? (
          <span className="ml-3 text-xs text-muted-foreground">
            {(version.sizeBytes / 1024 / 1024).toFixed(2)} MB
          </span>
        ) : null}
      </div>
      <div className="flex items-center gap-2">
        <a
          href={downloadUrl}
          className={buttonVariants({ variant: 'outline', size: 'sm' })}
        >
          <Download className="mr-1 h-3.5 w-3.5" />
          Download
        </a>
        <a
          href={`rsmm://mods/${slug}/versions/${version.version}`}
          className={buttonVariants({ variant: 'outline', size: 'sm' })}
          title="Open in RSMM desktop app"
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="font-medium">{v}</dd>
    </div>
  );
}

interface PublicShot {
  url: string;
  caption?: string;
}

function PublicGallery({ shots, modName }: { shots: PublicShot[]; modName: string }) {
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
              <div className="aspect-video overflow-hidden rounded-md bg-muted">
                <img
                  src={shot.url}
                  alt={shot.caption || `${modName} screenshot ${i + 1}`}
                  loading="lazy"
                  className="h-full w-full object-cover transition-opacity group-hover:opacity-90"
                />
              </div>
              {shot.caption ? (
                <p className="mt-1 truncate text-xs text-muted-foreground">{shot.caption}</p>
              ) : null}
            </button>
          </li>
        ))}
      </ul>
      {idx != null && shots[idx] ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={shots[idx].caption || `${modName} screenshot ${idx + 1}`}
          className="fixed inset-0 z-[90] flex items-center justify-center bg-pitch/95 p-4 animate-fade-in"
        >
          <button type="button" onClick={close} className="absolute inset-0" aria-label="Close" />
          <button
            type="button"
            onClick={close}
            className="absolute right-4 top-4 z-10 rounded-md bg-background/80 p-2 text-foreground hover:bg-background"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
          {shots.length > 1 ? (
            <>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  prev();
                }}
                className="absolute left-4 top-1/2 z-10 -translate-y-1/2 rounded-md bg-background/80 p-3 text-foreground hover:bg-background"
                aria-label="Previous"
              >
                <ChevronLeft className="h-6 w-6" />
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  next();
                }}
                className="absolute right-4 top-1/2 z-10 -translate-y-1/2 rounded-md bg-background/80 p-3 text-foreground hover:bg-background"
                aria-label="Next"
              >
                <ChevronRight className="h-6 w-6" />
              </button>
            </>
          ) : null}
          <figure
            onClick={(e) => e.stopPropagation()}
            className="relative z-[1] flex max-h-full max-w-5xl flex-col items-center gap-3"
          >
            <img
              src={shots[idx].url}
              alt={shots[idx].caption || `${modName} screenshot ${idx + 1}`}
              className="max-h-[78vh] max-w-full rounded-md object-contain"
            />
            <figcaption className="max-w-3xl text-center text-sm text-muted-foreground">
              {shots[idx].caption || `Screenshot ${idx + 1} of ${shots.length}`}
            </figcaption>
            <p className="font-mono text-xs text-muted-foreground/70">
              {idx + 1} / {shots.length}
            </p>
          </figure>
        </div>
      ) : null}
    </>
  );
}
