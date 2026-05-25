'use client';
import { Badge, Button, Input, Spinner, buttonVariants } from '@rsmm/ui';
import type { ModVersion } from '@rsmm/schemas';
import { ApiError } from '@rsmm/api-client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, ChevronLeft, ChevronRight, Download, ExternalLink, Star, Trash2, X } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { use, useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../../../lib/api';
import { getApiUrl } from '../../../lib/api-url';
import { useSession } from '../../../lib/auth-client';
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
              {mod.ownerId ? (
                <Link
                  href={`/u/${mod.ownerId}` as Route}
                  className="text-foreground hover:text-gilt hover:underline underline-offset-2"
                >
                  {mod.author ?? 'unknown'}
                </Link>
              ) : (
                (mod.author ?? 'unknown')
              )}
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

            <ReviewsSection slug={mod.slug} ownerId={mod.ownerId ?? null} />
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

            {mod.dependencies && Object.keys(mod.dependencies).length > 0 ? (
              <div className="grimoire-card p-6">
                <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wider">
                  Requires
                </h3>
                <ul className="space-y-1.5 text-sm">
                  {Object.entries(mod.dependencies).map(([slug, range]) => (
                    <li key={slug} className="flex items-baseline justify-between gap-2">
                      <Link
                        href={`/registry/${slug}` as Route}
                        className="text-foreground hover:text-gilt hover:underline underline-offset-2"
                      >
                        {slug}
                      </Link>
                      <code className="font-mono text-xs text-muted-foreground">{range}</code>
                    </li>
                  ))}
                </ul>
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
        <dialog
          open
          aria-label={shots[idx].caption || `${modName} screenshot ${idx + 1}`}
          className="fixed inset-0 z-[90] bg-pitch/95 animate-fade-in"
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
                  src={shots[idx].url}
                  alt={shots[idx].caption || `${modName} screenshot ${idx + 1}`}
                  className="max-w-full rounded-md object-contain shadow-2xl"
                />
                <figcaption className="max-w-3xl text-center text-sm text-muted-foreground">
                  {shots[idx].caption || `Screenshot ${idx + 1} of ${shots.length}`}
                </figcaption>
                <p className="font-mono text-xs text-muted-foreground/70">
                  {idx + 1} / {shots.length}
                </p>
              </figure>
            </div>
          </div>
          <button
            type="button"
            onClick={close}
            className="fixed right-4 top-4 z-20 rounded-md bg-background/80 p-2 text-foreground hover:bg-background"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
          {shots.length > 1 ? (
            <>
              <button
                type="button"
                onClick={prev}
                className="fixed left-2 sm:left-4 top-1/2 z-20 -translate-y-1/2 rounded-md bg-background/80 p-3 text-foreground hover:bg-background"
                aria-label="Previous"
              >
                <ChevronLeft className="h-6 w-6" />
              </button>
              <button
                type="button"
                onClick={next}
                className="fixed right-2 sm:right-4 top-1/2 z-20 -translate-y-1/2 rounded-md bg-background/80 p-3 text-foreground hover:bg-background"
                aria-label="Next"
              >
                <ChevronRight className="h-6 w-6" />
              </button>
            </>
          ) : null}
        </dialog>
      ) : null}
    </>
  );
}

function StarRating({
  value,
  onChange,
  size = 'md',
}: {
  value: number;
  onChange?: (n: number) => void;
  size?: 'sm' | 'md';
}) {
  const cls = size === 'sm' ? 'h-3.5 w-3.5' : 'h-5 w-5';
  return (
    <div className="flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((n) =>
        onChange ? (
          <button
            key={n}
            type="button"
            onClick={() => onChange(n)}
            aria-label={`Rate ${n} star${n === 1 ? '' : 's'}`}
            className="text-muted-foreground transition hover:text-gilt"
          >
            <Star
              className={`${cls} ${n <= value ? 'fill-gilt text-gilt' : ''}`}
              aria-hidden
            />
          </button>
        ) : (
          <Star
            key={n}
            className={`${cls} ${n <= value ? 'fill-gilt text-gilt' : 'text-muted-foreground'}`}
            aria-hidden
          />
        ),
      )}
    </div>
  );
}

function ReviewsSection({ slug, ownerId }: { slug: string; ownerId: string | null }) {
  const { data: session } = useSession();
  const qc = useQueryClient();
  const reviews = useQuery({
    queryKey: ['mods', slug, 'reviews'],
    queryFn: () => api.mods.reviews(slug),
  });
  const myReview = useMemo(() => {
    if (!session?.user) return null;
    return reviews.data?.items.find((r) => r.userId === session.user.id) ?? null;
  }, [reviews.data, session]);

  const [rating, setRating] = useState(5);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [editing, setEditing] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    if (myReview && !editing) {
      setRating(myReview.rating);
      setTitle(myReview.title ?? '');
      setBody(myReview.body ?? '');
    }
  }, [myReview, editing]);

  const upsert = useMutation({
    mutationFn: async () => {
      setErrorMsg(null);
      await api.mods.upsertReview(slug, {
        rating,
        title: title.trim() || null,
        body: body.trim() || null,
      });
    },
    onSuccess: async () => {
      setEditing(false);
      await qc.invalidateQueries({ queryKey: ['mods', slug, 'reviews'] });
      await qc.invalidateQueries({ queryKey: ['mods', 'detail', slug] });
    },
    onError: (err) => {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to save review');
    },
  });

  const remove = useMutation({
    mutationFn: async () => {
      await api.mods.deleteReview(slug);
    },
    onSuccess: async () => {
      setRating(5);
      setTitle('');
      setBody('');
      setEditing(false);
      await qc.invalidateQueries({ queryKey: ['mods', slug, 'reviews'] });
      await qc.invalidateQueries({ queryKey: ['mods', 'detail', slug] });
    },
  });

  const isOwner = session?.user && ownerId === session.user.id;
  const others = (reviews.data?.items ?? []).filter((r) => r.userId !== session?.user?.id);
  const avg = reviews.data?.averageRating ?? null;

  return (
    <div className="grimoire-card p-6">
      <div className="mb-4 flex items-end justify-between gap-3">
        <h2 className="text-xl font-bold tracking-tight">Reviews</h2>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          {avg != null ? <StarRating value={Math.round(avg)} size="sm" /> : null}
          <span>
            {avg != null ? `${avg.toFixed(1)} · ` : ''}
            {reviews.data?.total ?? 0} review{(reviews.data?.total ?? 0) === 1 ? '' : 's'}
          </span>
        </div>
      </div>

      {session?.user && !isOwner ? (
        <div className="mb-6 space-y-3 rounded-lg border border-border/40 bg-card p-4">
          <p className="text-sm font-semibold">{myReview ? 'Your review' : 'Write a review'}</p>
          <div className="flex items-center gap-3">
            <StarRating value={rating} onChange={setRating} />
            <span className="font-mono text-xs text-muted-foreground">{rating} / 5</span>
          </div>
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Title (optional)"
            maxLength={120}
          />
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Share your experience…"
            maxLength={4000}
            rows={4}
            className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
          {errorMsg ? <p className="text-xs text-destructive">{errorMsg}</p> : null}
          <div className="flex items-center justify-between gap-2">
            <p className="font-mono text-[10px] text-muted-foreground">
              {body.length}/4000
            </p>
            <div className="flex items-center gap-2">
              {myReview ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => remove.mutate()}
                  disabled={remove.isPending}
                >
                  <Trash2 className="mr-1 h-3.5 w-3.5" /> Delete
                </Button>
              ) : null}
              <Button
                type="button"
                size="sm"
                onClick={() => upsert.mutate()}
                disabled={upsert.isPending}
              >
                {myReview ? 'Update review' : 'Post review'}
              </Button>
            </div>
          </div>
        </div>
      ) : !session?.user ? (
        <p className="mb-6 text-sm text-muted-foreground">
          <Link href="/auth/signin" className="text-foreground underline underline-offset-2 hover:text-gilt">
            Sign in
          </Link>{' '}
          to leave a review.
        </p>
      ) : null}

      {isOwner ? (
        <p className="mb-6 text-xs text-muted-foreground">
          You own this mod — review collection is disabled for owners.
        </p>
      ) : null}

      {others.length === 0 && !myReview ? (
        <p className="text-sm text-muted-foreground">No reviews yet. Be the first to share!</p>
      ) : (
        <ul className="space-y-4">
          {others.map((r) => (
            <li key={r.id} className="border-t border-border/40 pt-4 first:border-t-0 first:pt-0">
              <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border bg-muted text-xs font-semibold">
                  {r.userImage ? (
                    <img
                      src={r.userImage}
                      alt={r.userName ?? 'reviewer'}
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <span>{(r.userName ?? '?').slice(0, 2).toUpperCase()}</span>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link
                      href={`/u/${r.userId}` as Route}
                      className="text-sm font-medium hover:text-gilt hover:underline underline-offset-2"
                    >
                      {r.userName ?? 'anonymous'}
                    </Link>
                    <StarRating value={r.rating} size="sm" />
                    <span className="font-mono text-[10px] text-muted-foreground">
                      {new Date(r.updatedAt).toLocaleDateString()}
                    </span>
                  </div>
                  {r.title ? <p className="mt-1 text-sm font-semibold">{r.title}</p> : null}
                  {r.body ? (
                    <p className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">
                      {r.body}
                    </p>
                  ) : null}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
