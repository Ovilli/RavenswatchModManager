'use client';
import { Button, Input } from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Star, Trash2 } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../../../lib/api';
import { useSession } from '../../../lib/auth-client';
import { ReviewReplyBlock } from '../../components/review-reply';

function useModReviews(slug: string) {
  return useQuery({
    queryKey: ['mods', slug, 'reviews'],
    queryFn: () => api.mods.reviews(slug),
  });
}

export function ModRatingSummary({
  slug,
  fallbackRating,
}: { slug: string; fallbackRating: number | null }) {
  // Share the reviews section's query so the average and count stay in sync
  // after a review is added, updated, or removed.
  const reviews = useModReviews(slug);
  const average = reviews.data ? reviews.data.averageRating : fallbackRating;
  const count = reviews.data?.total;
  if (average == null) {
    return (
      <a className="mod-rating-summary" href="#reviews">
        {count === 0 ? 'No reviews yet' : 'Read reviews'}
      </a>
    );
  }
  const rating = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(average);
  const countLabel = count == null ? '' : count.toLocaleString('en-US');
  return (
    <a
      className="mod-rating-summary"
      href="#reviews"
      aria-label={`Rated ${rating} out of 5${count != null ? ` from ${countLabel} ${count === 1 ? 'review' : 'reviews'}` : ''}. Read reviews`}
    >
      <Star size={16} fill="currentColor" aria-hidden />
      <span>{rating}</span>
      {count != null ? <span className="mod-rating-count">({countLabel})</span> : null}
    </a>
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
            aria-pressed={value === n}
            className="flex h-11 w-11 items-center justify-center rounded-md text-muted-foreground hover:text-gilt"
          >
            <Star className={`${cls} ${n <= value ? 'fill-gilt text-gilt' : ''}`} aria-hidden />
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

export function ReviewsSection({ slug, isAuthor }: { slug: string; isAuthor: boolean }) {
  const { data: session } = useSession();
  const qc = useQueryClient();
  const reviews = useModReviews(slug);
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

  // Owner or co-author: may reply to reviews, may not review (server-enforced).
  const isOwner = !!session?.user && isAuthor;
  const items = reviews.data?.items ?? [];
  const avg = reviews.data?.averageRating ?? null;

  return (
    <section id="reviews" className="mod-section mod-reviews" aria-labelledby="reviews-heading">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h2 id="reviews-heading">Player reviews</h2>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          {avg != null ? <StarRating value={Math.round(avg)} size="sm" /> : null}
          <span>
            {avg != null ? `${avg.toFixed(1)} · ` : ''}
            {reviews.data
              ? `${reviews.data.total} review${reviews.data.total === 1 ? '' : 's'}`
              : ''}
          </span>
        </div>
      </div>

      {session?.user && !isOwner ? (
        <div className="mb-6 space-y-3 rounded-lg border border-border/40 bg-card p-4">
          <p className="text-sm font-semibold">{myReview ? 'Your review' : 'Write a review'}</p>
          <div className="flex items-center gap-3">
            <StarRating
              value={rating}
              onChange={(v) => {
                upsert.reset();
                setRating(v);
              }}
            />
            <span className="font-mono text-xs text-muted-foreground">{rating} / 5</span>
          </div>
          <Input
            aria-label="Review title (optional)"
            value={title}
            onChange={(e) => {
              upsert.reset();
              setTitle(e.target.value);
            }}
            placeholder="Title (optional)"
            maxLength={120}
          />
          <textarea
            aria-label="Your review"
            value={body}
            onChange={(e) => {
              upsert.reset();
              setBody(e.target.value);
            }}
            placeholder="Share your experience…"
            maxLength={4000}
            rows={4}
            className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
          {errorMsg ? <p className="text-xs text-destructive">{errorMsg}</p> : null}
          <div className="flex items-center justify-between gap-2">
            <p className="font-mono text-[10px] text-muted-foreground">
              {body.length}/4000
              {upsert.isSuccess ? <output className="ml-3 text-gilt">✓ Review saved</output> : null}
            </p>
            <div className="flex items-center gap-2">
              {myReview ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    if (confirm('Delete your review?')) remove.mutate();
                  }}
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
                {upsert.isPending ? 'Saving…' : myReview ? 'Update review' : 'Post review'}
              </Button>
            </div>
          </div>
        </div>
      ) : !session?.user ? (
        <p className="mb-6 text-sm text-muted-foreground">
          <Link
            href="/auth/signin"
            className="text-foreground underline underline-offset-2 hover:text-gilt"
          >
            Sign in
          </Link>{' '}
          to leave a review.
        </p>
      ) : null}

      {isOwner ? (
        <p className="mb-6 text-xs text-muted-foreground">
          You're an author of this mod, so you can't review it — but you can reply to reviews.
        </p>
      ) : null}

      {reviews.isLoading ? (
        <output className="text-sm text-muted-foreground">Loading reviews…</output>
      ) : reviews.isError ? (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-sm">
          <p>Reviews couldn’t be loaded.</p>
          <button
            type="button"
            className="underline underline-offset-4"
            onClick={() => reviews.refetch()}
          >
            Try again
          </button>
        </div>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No reviews yet. Be the first to share!</p>
      ) : (
        <ul className="space-y-4">
          {items.map((r) => (
            <li key={r.id} className="border-t border-border/40 pt-4 first:border-t-0 first:pt-0">
              <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border bg-muted text-xs font-semibold">
                  {r.userImage ? (
                    <img
                      loading="lazy"
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
                    {r.userId === session?.user?.id ? (
                      <span className="rounded border border-border px-1.5 font-mono text-[10px] text-muted-foreground">
                        you
                      </span>
                    ) : null}
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
                  <ReviewReplyBlock
                    review={r}
                    canReply={!!isOwner}
                    queryKey={['mods', slug, 'reviews']}
                    onSave={(text) => api.mods.replyToReview(slug, r.id, text)}
                    onDelete={() => api.mods.deleteReviewReply(slug, r.id)}
                  />
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
