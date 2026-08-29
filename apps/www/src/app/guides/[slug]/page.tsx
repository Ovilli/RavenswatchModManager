'use client';
import { ApiError, isRateLimited } from '@rsmm/api-client';
import { Badge, Button, Input, Spinner, buttonVariants } from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Check, Loader2, Pencil, Star, Trash2, X } from 'lucide-react';
import type { Route } from 'next';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { use, useState } from 'react';
import { AdBanner } from '../../components/ad-banner';
import { api } from '../../../lib/api';
import { useSession } from '../../../lib/auth-client';
import { useEditingFlag } from '../../../lib/use-editing-flag';

const MDEditor = dynamic(() => import('@uiw/react-md-editor'), { ssr: false });
const MDPreview = dynamic(() => import('@uiw/react-md-editor').then((m) => m.default.Markdown), {
  ssr: false,
});

const STATUS_LABEL: Record<string, string> = {
  draft: 'Draft',
  pending: 'In review',
  approved: 'Published',
  rejected: 'Needs changes',
};

function describeApiError(err: unknown): string {
  if (isRateLimited(err)) return `Rate limited — try again in ${err.retryAfter}s.`;
  if (err instanceof ApiError) {
    const body = err.body as { error?: string } | null;
    if (body?.error) return body.error;
    return `HTTP ${err.status}`;
  }
  return err instanceof Error ? err.message : String(err);
}

export default function GuidePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const router = useRouter();
  const qc = useQueryClient();
  const { data: session } = useSession();

  const guide = useQuery({ queryKey: ['guide', slug], queryFn: () => api.guides.get(slug) });
  const reviews = useQuery({
    queryKey: ['guide', slug, 'reviews'],
    queryFn: () => api.guides.reviews.list(slug),
    enabled: guide.data?.status === 'approved',
  });

  const [editing, setEditing] = useState(false);
  useEditingFlag(editing);
  const [editTitle, setEditTitle] = useState('');
  const [editSummary, setEditSummary] = useState('');
  const [editBody, setEditBody] = useState('');
  const [reviewRating, setReviewRating] = useState(0);
  const [reviewTitle, setReviewTitle] = useState('');
  const [reviewBody, setReviewBody] = useState('');

  const g = guide.data;
  const isOwner = !!session?.user && g?.ownerId === session.user.id;
  const userReview = reviews.data?.items.find((r) => r.userId === session?.user?.id);

  const patch = useMutation({
    mutationFn: (b: Parameters<typeof api.guides.patch>[1]) => api.guides.patch(slug, b),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['guide', slug] }),
  });
  const approve = useMutation({
    mutationFn: () => api.guides.approve(slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['guide', slug] }),
  });
  const reject = useMutation({
    mutationFn: () => api.guides.reject(slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['guide', slug] }),
  });
  const remove = useMutation({
    mutationFn: () => api.guides.remove(slug),
    onSuccess: () => router.push('/guides' as Route),
  });
  const reviewUpsert = useMutation({
    mutationFn: () =>
      api.guides.reviews.upsert(slug, {
        rating: reviewRating,
        title: reviewTitle.trim() || null,
        body: reviewBody.trim() || null,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['guide', slug, 'reviews'] }),
  });

  if (guide.isLoading) {
    return (
      <main className="container mx-auto flex items-center justify-center px-6 py-24">
        <Spinner />
      </main>
    );
  }
  if (guide.isError || !g) {
    return (
      <main className="container mx-auto space-y-4 px-6 py-12">
        <p className="text-muted-foreground">Guide not found.</p>
        <Link href={'/guides' as Route} className={buttonVariants({ variant: 'outline', size: 'sm' })}>
          <ArrowLeft className="mr-1.5 h-4 w-4" /> Back to Guides
        </Link>
      </main>
    );
  }

  const startEditing = () => {
    setEditTitle(g.title);
    setEditSummary(g.summary ?? '');
    setEditBody(g.body);
    setEditing(true);
  };
  const saveEdit = async () => {
    await patch.mutateAsync({
      title: editTitle,
      summary: editSummary.trim() || null,
      body: editBody,
    });
    setEditing(false);
  };

  return (
    <main
      className={`container mx-auto max-w-3xl space-y-6 px-6 pb-12 ${
        g.status === 'approved' ? 'pt-6' : 'pt-12'
      }`}
    >
      <div className="flex items-center justify-between">
        {/* An approved guide gets its back link from the server-rendered block
            in `[slug]/layout.tsx`; a draft has no such block, so it needs one
            here. */}
        {g.status !== 'approved' ? (
          <Link
            href={'/guides' as Route}
            className={buttonVariants({ variant: 'outline', size: 'sm' })}
          >
            <ArrowLeft className="mr-1.5 h-4 w-4" /> Back to Guides
          </Link>
        ) : (
          <span />
        )}
        <div className="flex items-center gap-2">
          {g.status !== 'approved' ? (
            <Badge variant="outline">{STATUS_LABEL[g.status] ?? g.status}</Badge>
          ) : null}
          {isOwner && !editing ? (
            <Button type="button" variant="outline" size="sm" onClick={startEditing}>
              <Pencil className="mr-1 h-3.5 w-3.5" /> Edit
            </Button>
          ) : null}
        </div>
      </div>

      {g.imageUrl && !editing ? (
        <div className="aspect-[21/9] w-full overflow-hidden rounded-lg bg-muted">
          <img src={g.imageUrl} alt={`${g.title} cover`} className="h-full w-full object-cover" />
        </div>
      ) : null}

      {editing ? (
        <div className="space-y-4">
          <Input value={editTitle} onChange={(e) => setEditTitle(e.target.value)} maxLength={160} />
          <textarea
            value={editSummary}
            onChange={(e) => setEditSummary(e.target.value)}
            rows={2}
            maxLength={512}
            placeholder="Summary"
            className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          />
          <div data-color-mode="dark" className="md-editor-themed">
            <MDEditor value={editBody} onChange={(v) => setEditBody(v ?? '')} height={420} />
          </div>
          <div className="flex items-center gap-2">
            <Button type="button" size="sm" onClick={saveEdit} disabled={patch.isPending}>
              {patch.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null} Save
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        // An approved guide has its title and body server-rendered by
        // `[slug]/layout.tsx`, so rendering them again here would duplicate
        // them on the page. A draft or in-review guide is not in that server
        // fetch (it is visible only to its author's session), so it still
        // renders here.
        g.status !== 'approved' ? (
          <>
            <header className="space-y-1">
              <h1 className="text-3xl font-bold tracking-tight">{g.title}</h1>
              <p className="text-sm text-muted-foreground">
                by {g.ownerName ?? 'unknown'}
                {g.reviewCount > 0 && g.rating != null ? ` · ★ ${g.rating.toFixed(1)} (${g.reviewCount})` : ''}
              </p>
            </header>

            <article data-color-mode="dark" className="md-editor-themed prose-invert max-w-none">
              <MDPreview source={g.body} />
            </article>
          </>
        ) : null
      )}

      {/* Owner / admin lifecycle controls */}
      {isOwner && !editing ? (
        <div className="flex flex-wrap items-center gap-2 border-t border-border/40 pt-4">
          {g.status === 'draft' || g.status === 'rejected' ? (
            <Button
              type="button"
              size="sm"
              onClick={() => patch.mutate({ status: 'pending' })}
              disabled={patch.isPending}
            >
              Submit for review
            </Button>
          ) : null}
          {g.status === 'pending' ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => patch.mutate({ status: 'draft' })}
              disabled={patch.isPending}
            >
              Withdraw
            </Button>
          ) : null}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              if (window.confirm('Delete this guide? This cannot be undone.')) remove.mutate();
            }}
            disabled={remove.isPending}
          >
            <Trash2 className="mr-1 h-3.5 w-3.5" /> Delete
          </Button>
        </div>
      ) : null}

      {session?.user && !isOwner && g.status === 'pending' ? (
        // Admin moderation — the API enforces the actual admin check; these
        // buttons just 403 for non-admins.
        <div className="flex flex-wrap items-center gap-2 border-t border-border/40 pt-4">
          <Button type="button" size="sm" onClick={() => approve.mutate()} disabled={approve.isPending}>
            <Check className="mr-1 h-3.5 w-3.5" /> Approve
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => reject.mutate()}
            disabled={reject.isPending}
          >
            <X className="mr-1 h-3.5 w-3.5" /> Reject
          </Button>
          {(approve.isError || reject.isError) && (
            <span className="text-xs text-destructive">Not authorised.</span>
          )}
        </div>
      ) : null}

      {/* Ads only on public (approved) guides. */}
      {g.status === 'approved' ? <AdBanner slot="1934448674" className="rounded-lg" /> : null}

      {/* Reviews — approved guides only */}
      {g.status === 'approved' ? (
        <section className="space-y-4 border-t border-border/40 pt-6">
          <h2 className="text-xl font-bold tracking-tight">
            Reviews
            {reviews.data?.averageRating != null ? (
              <span className="ml-2 text-sm font-normal text-muted-foreground">
                {reviews.data.averageRating.toFixed(1)} ★ ({reviews.data.total})
              </span>
            ) : null}
          </h2>

          {session?.user && !isOwner ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (reviewRating > 0) reviewUpsert.mutate();
              }}
              className="grimoire-card space-y-3 p-4"
            >
              <h3 className="text-sm font-semibold">{userReview ? 'Update your review' : 'Write a review'}</h3>
              <div className="flex items-center gap-1">
                {[1, 2, 3, 4, 5].map((star) => (
                  <button key={star} type="button" onClick={() => setReviewRating(star)}>
                    <Star
                      className={`h-6 w-6 fill-current ${star <= reviewRating ? 'text-yellow-500' : 'text-muted-foreground'}`}
                    />
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
                placeholder="Your thoughts (optional)"
                rows={3}
                className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              />
              {reviewUpsert.isError ? (
                <p className="text-sm text-destructive">{describeApiError(reviewUpsert.error)}</p>
              ) : null}
              <Button type="submit" size="sm" disabled={reviewUpsert.isPending || reviewRating === 0}>
                {reviewUpsert.isPending ? 'Saving…' : userReview ? 'Update' : 'Submit'}
              </Button>
            </form>
          ) : isOwner ? (
            <p className="text-sm text-muted-foreground">Authors cannot review their own guide.</p>
          ) : (
            <p className="text-sm text-muted-foreground">
              <Link href="/auth/signin" className="underline">
                Sign in
              </Link>{' '}
              to leave a review.
            </p>
          )}

          <ul className="space-y-4">
            {(reviews.data?.items ?? []).map((r) => (
              <li key={r.id} className="grimoire-card p-4">
                <div className="flex items-center gap-2">
                  {r.userImage ? (
                    <img src={r.userImage} alt={r.userName ?? ''} className="h-6 w-6 rounded-full" />
                  ) : (
                    <div className="h-6 w-6 rounded-full bg-muted" />
                  )}
                  <span className="text-sm font-medium">{r.userName ?? 'user'}</span>
                  <div className="ml-auto flex">
                    {[1, 2, 3, 4, 5].map((s) => (
                      <Star
                        key={s}
                        className={`h-3.5 w-3.5 fill-current ${s <= r.rating ? 'text-yellow-500' : 'text-muted-foreground'}`}
                      />
                    ))}
                  </div>
                </div>
                {r.title ? <p className="mt-2 text-sm font-semibold">{r.title}</p> : null}
                {r.body ? <p className="mt-1 text-sm text-muted-foreground">{r.body}</p> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </main>
  );
}
