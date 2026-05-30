'use client';
import { ApiError, isRateLimited } from '@rsmm/api-client';
import { Badge, Button, Input, Spinner, buttonVariants } from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Globe,
  ImageIcon,
  Loader2,
  Lock,
  Pencil,
  Plus,
  Save,
  Star,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import type { Route } from 'next';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { use, useEffect, useState } from 'react';
import { api } from '../../../lib/api';
import { useSession } from '../../../lib/auth-client';

const MDEditor = dynamic(() => import('@uiw/react-md-editor'), { ssr: false });
const MDPreview = dynamic(() => import('@uiw/react-md-editor').then((m) => m.default.Markdown), {
  ssr: false,
});

function describeApiError(err: unknown): string {
  if (isRateLimited(err)) {
    return `Rate limited — try again in ${err.retryAfter}s.`;
  }
  if (err instanceof ApiError) {
    const body = err.body as { error?: string } | null;
    if (body?.error) return body.error;
    if (err.status === 429) return 'Too many requests. Please wait.';
    return `HTTP ${err.status}`;
  }
  return err instanceof Error ? err.message : String(err);
}

async function uploadImage(file: File, slug: string): Promise<string> {
  const contentType = file.type as 'image/png' | 'image/jpeg' | 'image/webp';
  const presign = await api.collections.presignImage(slug, {
    contentType,
    sizeBytes: file.size,
  });
  await fetch(presign.uploadUrl, {
    method: 'PUT',
    body: file,
    headers: { 'Content-Type': contentType },
  });
  return presign.publicUrl;
}

export default function CollectionDetailPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  const { data: session } = useSession();
  const qc = useQueryClient();
  const [addSlug, setAddSlug] = useState('');
  const [addError, setAddError] = useState<string | null>(null);

  // Edit mode state
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState('');
  const [editSummary, setEditSummary] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editIsPublic, setEditIsPublic] = useState(true);
  const [editIconFile, setEditIconFile] = useState<File | null>(null);
  const [editIconPreview, setEditIconPreview] = useState<string | null>(null);
  const [editScreenshots, setEditScreenshots] = useState<{ url: string; caption?: string }[]>([]);
  const [newScreenshots, setNewScreenshots] = useState<
    { file: File; preview: string; caption: string }[]
  >([]);
  const [saving, setSaving] = useState(false);

  // Review state
  const [reviewRating, setReviewRating] = useState(5);
  const [reviewTitle, setReviewTitle] = useState('');
  const [reviewBody, setReviewBody] = useState('');

  // Gallery lightbox
  const [lightboxIdx, setLightboxIdx] = useState<number | null>(null);

  const detail = useQuery({
    queryKey: ['collections', slug],
    queryFn: () => api.collections.get(slug),
    retry: (count, err) => (err instanceof ApiError && err.status === 404 ? false : count < 1),
  });

  const reviews = useQuery({
    queryKey: ['collections', slug, 'reviews'],
    queryFn: () => api.collections.reviews.list(slug),
    enabled: !!detail.data,
  });

  const addMod = useMutation({
    mutationFn: (modSlug: string) => api.collections.addMod(slug, modSlug),
    onSuccess: async () => {
      setAddSlug('');
      setAddError(null);
      await qc.invalidateQueries({ queryKey: ['collections', slug] });
    },
    onError: (err) => {
      setAddError(describeApiError(err));
    },
  });

  const removeMod = useMutation({
    mutationFn: (modSlug: string) => api.collections.removeMod(slug, modSlug),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['collections', slug] });
    },
  });

  const remove = useMutation({
    mutationFn: () => api.collections.remove(slug),
    onSuccess: () => {
      window.location.href = '/c';
    },
  });

  const reviewUpsert = useMutation({
    mutationFn: () =>
      api.collections.reviews.upsert(slug, {
        rating: reviewRating,
        title: reviewTitle.trim() || null,
        body: reviewBody.trim() || null,
      }),
    onSuccess: async () => {
      setReviewTitle('');
      setReviewBody('');
      setReviewRating(5);
      await qc.invalidateQueries({ queryKey: ['collections', slug, 'reviews'] });
    },
  });

  const reviewDelete = useMutation({
    mutationFn: () => api.collections.reviews.remove(slug),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['collections', slug, 'reviews'] });
    },
  });

  useEffect(() => {
    if (detail.data && !editing) {
      setEditName(detail.data.name);
      setEditSummary(detail.data.summary ?? '');
      setEditDescription(detail.data.description ?? '');
      setEditIsPublic(detail.data.isPublic);
      setEditScreenshots(detail.data.screenshots ?? []);
    }
  }, [detail.data, editing]);

  const startEditing = () => {
    setEditing(true);
    setEditIconFile(null);
    setEditIconPreview(null);
    setNewScreenshots([]);
  };

  const cancelEditing = () => {
    setEditing(false);
    setEditIconFile(null);
    setEditIconPreview(null);
    setNewScreenshots([]);
    if (detail.data) {
      setEditName(detail.data.name);
      setEditSummary(detail.data.summary ?? '');
      setEditDescription(detail.data.description ?? '');
      setEditIsPublic(detail.data.isPublic);
      setEditScreenshots(detail.data.screenshots ?? []);
    }
  };

  const saveEditing = async () => {
    setSaving(true);
    try {
      let imageUrl: string | null = detail.data?.imageUrl ?? null;
      if (editIconFile) {
        imageUrl = await uploadImage(editIconFile, slug);
      }

      const shots = [...editScreenshots];
      for (const ns of newScreenshots) {
        const url = await uploadImage(ns.file, slug);
        shots.push({ url, caption: ns.caption || undefined });
      }

      await api.collections.patch(slug, {
        name: editName,
        summary: editSummary.trim() || null,
        description: editDescription || null,
        imageUrl,
        screenshots: shots,
        isPublic: editIsPublic,
      });
      setEditing(false);
      await qc.invalidateQueries({ queryKey: ['collections', slug] });
    } finally {
      setSaving(false);
    }
  };

  if (detail.isLoading) {
    return (
      <main className="container mx-auto flex items-center justify-center px-6 py-24">
        <Spinner />
      </main>
    );
  }

  if (detail.isError || !detail.data) {
    return (
      <main className="container mx-auto space-y-6 px-6 py-12">
        <Link href={'/c' as Route} className={buttonVariants({ variant: 'outline', size: 'sm' })}>
          <ArrowLeft className="mr-1.5 h-4 w-4" /> Back to Collections
        </Link>
        <p className="text-muted-foreground">Collection not found.</p>
      </main>
    );
  }

  const c = detail.data;
  const isOwner = session?.user?.id === c.ownerId;
  const userReview = reviews.data?.items.find((r) => r.userId === session?.user?.id);

  return (
    <main className="container mx-auto space-y-6 px-6 py-12">
      <div className="flex items-center justify-between">
        <Link href={'/c' as Route} className={buttonVariants({ variant: 'outline', size: 'sm' })}>
          <ArrowLeft className="mr-1.5 h-4 w-4" /> Back to Collections
        </Link>
        {isOwner && !editing ? (
          <Button type="button" variant="outline" size="sm" onClick={startEditing}>
            <Pencil className="mr-1 h-3.5 w-3.5" /> Edit
          </Button>
        ) : null}
      </div>

      {c.imageUrl && !editing ? (
        <div className="aspect-[21/9] w-full overflow-hidden rounded-lg bg-muted">
          <img src={c.imageUrl} alt={`${c.name} cover`} className="h-full w-full object-cover" />
        </div>
      ) : null}

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          {editing ? (
            <Input
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              className="text-3xl font-bold tracking-tight"
              maxLength={128}
            />
          ) : (
            <h1 className="text-3xl font-bold tracking-tight">{c.name}</h1>
          )}
          <p className="mt-1 text-sm text-muted-foreground">
            by{' '}
            <Link
              href={`/u/${c.ownerId}` as Route}
              className="text-foreground hover:text-gilt hover:underline underline-offset-2"
            >
              {c.ownerName ?? 'unknown'}
            </Link>{' '}
            · updated {new Date(c.updatedAt).toLocaleDateString()}
            {reviews.data?.averageRating != null ? (
              <>
                {' '}
                · {reviews.data.averageRating.toFixed(1)} ★ ({reviews.data.total})
              </>
            ) : null}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {editing ? (
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={editIsPublic}
                onChange={(e) => setEditIsPublic(e.target.checked)}
              />
              <span>Public</span>
            </label>
          ) : (
            <Badge variant="outline">
              {c.isPublic ? (
                <>
                  <Globe className="mr-1 h-3 w-3" /> Public
                </>
              ) : (
                <>
                  <Lock className="mr-1 h-3 w-3" /> Private
                </>
              )}
            </Badge>
          )}
          <Badge variant="outline">
            {c.modCount} mod{c.modCount === 1 ? '' : 's'}
          </Badge>
          {isOwner && !editing ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                if (confirm('Delete this collection?')) remove.mutate();
              }}
            >
              <Trash2 className="mr-1 h-3.5 w-3.5" /> Delete
            </Button>
          ) : null}
        </div>
      </header>

      {/* Edit mode: icon upload */}
      {editing ? (
        <div className="space-y-1.5">
          <span className="block text-sm font-medium">Icon / Cover image</span>
          <div className="flex items-center gap-3">
            {editIconPreview || c.imageUrl ? (
              <img
                src={editIconPreview ?? c.imageUrl ?? ''}
                alt="Icon preview"
                className="h-24 w-24 rounded-md object-cover"
              />
            ) : null}
            <label className="flex cursor-pointer items-center gap-2 rounded-md border border-input px-3 py-2 text-sm hover:bg-accent">
              <Upload className="h-4 w-4" />
              <span>{editIconPreview || c.imageUrl ? 'Replace' : 'Upload'}</span>
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) {
                    setEditIconFile(f);
                    setEditIconPreview(URL.createObjectURL(f));
                  }
                }}
              />
            </label>
            {editIconPreview || c.imageUrl ? (
              <button
                type="button"
                onClick={() => {
                  setEditIconFile(null);
                  setEditIconPreview(null);
                }}
                className="text-sm text-destructive hover:underline"
              >
                Remove
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

      {/* Summary */}
      {editing ? (
        <textarea
          value={editSummary}
          onChange={(e) => setEditSummary(e.target.value)}
          maxLength={512}
          rows={2}
          className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          placeholder="Summary"
        />
      ) : c.summary ? (
        <p className="max-w-3xl text-muted-foreground">{c.summary}</p>
      ) : null}

      {/* Description */}
      {editing ? (
        <div className="space-y-1.5">
          <span className="block text-sm font-medium">
            Description <span className="text-muted-foreground">(Markdown)</span>
          </span>
          <div data-color-mode="dark" className="md-editor-themed">
            <MDEditor
              value={editDescription}
              onChange={(v) => setEditDescription(v ?? '')}
              preview="edit"
              height={300}
            />
          </div>
        </div>
      ) : c.description ? (
        <div className="grimoire-card space-y-3 p-6">
          <h2 className="text-xl font-bold tracking-tight">About</h2>
          <div data-color-mode="dark" className="prose prose-sm prose-invert max-w-none">
            <MDPreview source={c.description} style={{ background: 'transparent' }} />
          </div>
        </div>
      ) : null}

      {/* Edit mode: screenshots */}
      {editing ? (
        <div className="space-y-1.5">
          <span className="block text-sm font-medium">Screenshots (gallery)</span>
          <div className="grid grid-cols-3 gap-3 sm:grid-cols-4">
            {editScreenshots.map((shot, i) => (
              <div key={shot.url} className="relative">
                <img
                  src={shot.url}
                  alt={shot.caption || `Screenshot ${i + 1}`}
                  className="aspect-video w-full rounded-md object-cover"
                />
                <button
                  type="button"
                  onClick={() => setEditScreenshots((prev) => prev.filter((_, j) => j !== i))}
                  className="absolute -right-2 -top-2 rounded-full bg-background border p-1"
                >
                  <X className="h-3 w-3" />
                </button>
                <input
                  value={shot.caption ?? ''}
                  onChange={(e) =>
                    setEditScreenshots((prev) =>
                      prev.map((x, j) => (j === i ? { ...x, caption: e.target.value } : x)),
                    )
                  }
                  placeholder="Caption"
                  className="mt-1 w-full rounded border border-input bg-background px-1.5 py-0.5 text-xs"
                />
              </div>
            ))}
            {newScreenshots.map((ns, i) => (
              <div key={ns.preview} className="relative">
                <img
                  src={ns.preview}
                  alt={`New screenshot ${i + 1}`}
                  className="aspect-video w-full rounded-md object-cover"
                />
                <button
                  type="button"
                  onClick={() => setNewScreenshots((prev) => prev.filter((_, j) => j !== i))}
                  className="absolute -right-2 -top-2 rounded-full bg-background border p-1"
                >
                  <X className="h-3 w-3" />
                </button>
                <input
                  value={ns.caption}
                  onChange={(e) =>
                    setNewScreenshots((prev) =>
                      prev.map((x, j) => (j === i ? { ...x, caption: e.target.value } : x)),
                    )
                  }
                  placeholder="Caption"
                  className="mt-1 w-full rounded border border-input bg-background px-1.5 py-0.5 text-xs"
                />
              </div>
            ))}
            {editScreenshots.length + newScreenshots.length < 12 ? (
              <label className="flex aspect-video cursor-pointer items-center justify-center rounded-md border border-dashed border-input text-muted-foreground hover:bg-accent">
                <ImageIcon className="h-5 w-5" />
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) {
                      setNewScreenshots((prev) => [
                        ...prev,
                        { file: f, preview: URL.createObjectURL(f), caption: '' },
                      ]);
                    }
                  }}
                />
              </label>
            ) : null}
          </div>
          <p className="text-xs text-muted-foreground">Up to 12 images.</p>
        </div>
      ) : c.screenshots && c.screenshots.length > 0 ? (
        <div className="space-y-1.5">
          <h2 className="text-sm font-semibold">Gallery</h2>
          <div className="grid grid-cols-3 gap-3 sm:grid-cols-4">
            {c.screenshots.map((shot, i) => (
              <button
                key={shot.url}
                type="button"
                onClick={() => setLightboxIdx(i)}
                className="group block text-left"
              >
                <div className="aspect-video overflow-hidden rounded-md bg-muted">
                  <img
                    src={shot.url}
                    alt={shot.caption || `Screenshot ${i + 1}`}
                    loading="lazy"
                    className="h-full w-full object-cover transition-opacity group-hover:opacity-90"
                  />
                </div>
                {shot.caption ? (
                  <p className="mt-1 truncate text-xs text-muted-foreground">{shot.caption}</p>
                ) : null}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {/* Lightbox */}
      {lightboxIdx != null && c.screenshots
        ? (() => {
            const shots = c.screenshots;
            const active = shots[lightboxIdx];
            if (!active) return null;
            const close = () => setLightboxIdx(null);
            const prev = () => setLightboxIdx((lightboxIdx - 1 + shots.length) % shots.length);
            const next = () => setLightboxIdx((lightboxIdx + 1) % shots.length);
            return (
              <dialog
                open
                className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center"
                onClick={close}
                aria-label="Screenshot preview"
                onKeyDown={(e) => {
                  if (e.key === 'Escape') close();
                  else if (e.key === 'ArrowLeft') prev();
                  else if (e.key === 'ArrowRight') next();
                }}
              >
                <img
                  src={active.url}
                  alt={active.caption || `Screenshot ${lightboxIdx + 1}`}
                  className="max-h-[90vh] max-w-[90vw] object-contain rounded-lg"
                  onClick={(e) => e.stopPropagation()}
                />
                {shots.length > 1 ? (
                  <>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        prev();
                      }}
                      className="absolute left-4 top-1/2 -translate-y-1/2 rounded-full bg-background/80 p-2 hover:bg-background"
                    >
                      <ChevronLeft className="h-6 w-6" />
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        next();
                      }}
                      className="absolute right-4 top-1/2 -translate-y-1/2 rounded-full bg-background/80 p-2 hover:bg-background"
                    >
                      <ChevronRight className="h-6 w-6" />
                    </button>
                  </>
                ) : null}
                <button
                  type="button"
                  onClick={close}
                  className="absolute right-4 top-4 rounded-full bg-background/80 p-2 hover:bg-background"
                >
                  <X className="h-5 w-5" />
                </button>
              </dialog>
            );
          })()
        : null}

      {/* Edit action buttons */}
      {editing ? (
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={cancelEditing}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={saveEditing}
            disabled={saving || !editName.trim()}
          >
            {saving ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-1 h-4 w-4" />
            )}
            Save
          </Button>
        </div>
      ) : null}

      {/* Add mod (owner only) */}
      {isOwner ? (
        <section className="grimoire-card space-y-3 p-4">
          <h2 className="text-sm font-semibold">Add a mod by slug</h2>
          <div className="flex flex-wrap gap-2">
            <Input
              value={addSlug}
              onChange={(e) => setAddSlug(e.target.value.toLowerCase())}
              placeholder="mod-slug"
              className="max-w-sm"
            />
            <Button
              type="button"
              onClick={() => {
                if (addSlug) addMod.mutate(addSlug);
              }}
              disabled={!addSlug || addMod.isPending}
            >
              <Plus className="mr-1 h-4 w-4" /> Add
            </Button>
          </div>
          {addError ? <p className="text-xs text-destructive">{addError}</p> : null}
        </section>
      ) : null}

      {/* Mods list */}
      {c.mods.length === 0 ? (
        <p className="text-sm text-muted-foreground">This collection has no mods yet.</p>
      ) : (
        <ul className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {c.mods.map((m) => (
            <li key={m.id} className="grimoire-card overflow-hidden">
              <Link href={`/registry/${m.slug}` as Route} className="block">
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
                <div className="space-y-1.5 p-4">
                  <h3 className="text-base font-semibold leading-tight">{m.name}</h3>
                  <p className="text-xs text-muted-foreground">{m.author ?? 'unknown'}</p>
                  {m.summary ? (
                    <p className="text-xs text-muted-foreground line-clamp-2">{m.summary}</p>
                  ) : null}
                </div>
              </Link>
              {isOwner ? (
                <div className="border-t border-border/40 px-4 py-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => removeMod.mutate(m.slug)}
                  >
                    <Trash2 className="mr-1 h-3.5 w-3.5" /> Remove
                  </Button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {/* ─── Reviews ─── */}
      <section className="space-y-4">
        <h2 className="text-xl font-bold tracking-tight">
          Reviews
          {reviews.data?.averageRating != null ? (
            <span className="ml-2 text-sm font-normal text-muted-foreground">
              {reviews.data.averageRating.toFixed(1)} ★ ({reviews.data.total})
            </span>
          ) : null}
        </h2>

        {session?.user ? (
          isOwner ? (
            <p className="text-sm text-muted-foreground">
              Owners cannot review their own collection.
            </p>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                reviewUpsert.mutate();
              }}
              className="grimoire-card space-y-3 p-4"
            >
              <h3 className="text-sm font-semibold">
                {userReview ? 'Update your review' : 'Write a review'}
              </h3>
              <div className="flex items-center gap-1">
                {[1, 2, 3, 4, 5].map((star) => (
                  <button
                    key={star}
                    type="button"
                    onClick={() => setReviewRating(star)}
                    className={`h-6 w-6 ${star <= reviewRating ? 'text-yellow-500' : 'text-muted-foreground'}`}
                  >
                    <Star className="h-full w-full fill-current" />
                  </button>
                ))}
              </div>
              <Input
                value={reviewTitle}
                onChange={(e) => setReviewTitle(e.target.value)}
                placeholder="Title (optional)"
                maxLength={120}
              />
              <textarea
                value={reviewBody}
                onChange={(e) => setReviewBody(e.target.value)}
                placeholder="Your thoughts…"
                rows={3}
                className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
              <div className="flex items-center gap-2">
                <Button type="submit" disabled={reviewUpsert.isPending} size="sm">
                  {reviewUpsert.isPending ? 'Submitting…' : userReview ? 'Update' : 'Submit'}
                </Button>
                {userReview ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => reviewDelete.mutate()}
                  >
                    <Trash2 className="mr-1 h-3.5 w-3.5" /> Delete
                  </Button>
                ) : null}
              </div>
              {reviewUpsert.isError ? (
                <p className="text-xs text-destructive">{describeApiError(reviewUpsert.error)}</p>
              ) : null}
            </form>
          )
        ) : (
          <p className="text-sm text-muted-foreground">
            <Link href="/auth/signin" className="underline">
              Sign in
            </Link>{' '}
            to leave a review.
          </p>
        )}

        {reviews.isLoading ? (
          <Spinner />
        ) : reviews.data?.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No reviews yet.</p>
        ) : (
          <div className="space-y-3">
            {reviews.data?.items.map((r) => (
              <div key={r.id} className="grimoire-card p-4">
                <div className="flex items-center gap-2">
                  {r.userImage ? (
                    <img
                      src={r.userImage}
                      alt={r.userName ?? 'User'}
                      className="h-6 w-6 rounded-full"
                    />
                  ) : (
                    <div className="h-6 w-6 rounded-full bg-muted" />
                  )}
                  <span className="text-sm font-medium">{r.userName ?? 'Anonymous'}</span>
                  <span className="ml-auto flex items-center gap-0.5">
                    {Array.from({ length: 5 }).map((_, i) => (
                      <Star
                        // biome-ignore lint/suspicious/noArrayIndexKey: static 5 stars, no reordering
                        key={i}
                        className={`h-3 w-3 ${i < r.rating ? 'fill-yellow-500 text-yellow-500' : 'text-muted-foreground'}`}
                      />
                    ))}
                  </span>
                </div>
                {r.title ? <p className="mt-2 text-sm font-semibold">{r.title}</p> : null}
                {r.body ? <p className="mt-1 text-sm text-muted-foreground">{r.body}</p> : null}
                <p className="mt-1 text-xs text-muted-foreground">
                  {new Date(r.updatedAt).toLocaleDateString()}
                </p>
              </div>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
