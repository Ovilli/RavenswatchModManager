'use client';
import type { Review } from '@rsmm/schemas';
import type { createApiClient } from '@rsmm/api-client';
import { Button } from './button';
import { Input } from './input';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Star, Trash2 } from 'lucide-react';
import { type ReactNode, useEffect, useState } from 'react';
import { reviewText, type ReviewTextOptions } from '../lib/review-text';
import { ReviewReplyBlock } from './review-reply';

export type ReviewTarget = 'mod' | 'collection';

type ListingReviewsResponse = {
  items: Omit<Review, 'modId'>[];
  total: number;
  averageRating: number | null;
};

export function createReviewSource(
  api: ReturnType<typeof createApiClient>,
  target: ReviewTarget,
  slug: string,
) {
  if (target === 'collection') {
    return {
      queryKey: ['collections', slug, 'reviews'],
      listingKey: ['collections'],
      list: () => api.collections.reviews.list(slug),
      upsert: (input: { rating: number; title: string | null; body: string | null }) =>
        api.collections.reviews.upsert(slug, input),
      remove: () => api.collections.reviews.remove(slug),
      reply: (id: string, body: string) => api.collections.reviews.reply(slug, id, body),
      removeReply: (id: string) => api.collections.reviews.removeReply(slug, id),
    };
  }
  return {
    queryKey: ['mods', slug, 'reviews'],
    listingKey: ['mods'],
    list: () => api.mods.reviews(slug),
    upsert: (input: { rating: number; title: string | null; body: string | null }) =>
      api.mods.upsertReview(slug, input),
    remove: () => api.mods.deleteReview(slug),
    reply: (id: string, body: string) => api.mods.replyToReview(slug, id, body),
    removeReply: (id: string) => api.mods.deleteReviewReply(slug, id),
  };
}

export type ReviewSource = ReturnType<typeof createReviewSource>;

function useListingReviews(source: ReviewSource) {
  return useQuery({
    queryKey: source.queryKey,
    queryFn: async (): Promise<ListingReviewsResponse> => source.list(),
    // Refetch on mount/focus so changes made in the other client are visible.
    staleTime: 0,
  });
}

export function ListingRatingSummary({
  source,
  fallbackRating = null,
  t = reviewText,
  locale = 'en-US',
}: { source: ReviewSource; fallbackRating?: number | null } & ReviewTextOptions) {
  // Share the reviews section's query so the average and count stay in sync
  // after a review is added, updated, or removed.
  const reviews = useListingReviews(source);
  const average = reviews.data ? reviews.data.averageRating : fallbackRating;
  const count = reviews.data?.total;
  if (average == null) {
    return (
      <a className="mod-rating-summary" href="#reviews">
        {count === 0 ? t('No reviews yet') : t('Read reviews')}
      </a>
    );
  }
  const rating = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(average);
  const countLabel = count == null ? '' : count.toLocaleString(locale);
  return (
    <a
      className="mod-rating-summary"
      href="#reviews"
      aria-label={
        count == null
          ? t('Rated {rating} out of 5. Read reviews', { rating })
          : count === 1
            ? t('Rated {rating} out of 5 from {count} review. Read reviews', {
                rating,
                count: countLabel,
              })
            : t('Rated {rating} out of 5 from {count} reviews. Read reviews', {
                rating,
                count: countLabel,
              })
      }
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
  t = reviewText,
}: {
  value: number;
  onChange?: (n: number) => void;
  size?: 'sm' | 'md';
} & ReviewTextOptions) {
  const cls = size === 'sm' ? 'h-3.5 w-3.5' : 'h-5 w-5';
  return (
    <div
      className="flex items-center gap-0.5"
      role={onChange ? 'group' : 'img'}
      aria-label={onChange ? t('Rating') : t('{n} out of 5 stars', { n: value })}
    >
      {[1, 2, 3, 4, 5].map((n) =>
        onChange ? (
          <button
            key={n}
            type="button"
            onClick={() => onChange(n)}
            aria-label={n === 1 ? t('Rate {n} star', { n }) : t('Rate {n} stars', { n })}
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

export interface ListingReviewsProps extends ReviewTextOptions {
  source: ReviewSource;
  target: ReviewTarget;
  userId?: string;
  isAuthor: boolean;
  authPending?: boolean;
  signInLink: ReactNode;
  profileLink: (userId: string, name: string, className: string) => ReactNode;
  confirmDelete?: () => boolean | Promise<boolean>;
}

/** One review experience for the registry and desktop; hosts supply navigation and session. */
export function ListingReviews(props: ListingReviewsProps) {
  return (
    <ListingReviewsContent
      key={`${props.source.queryKey.join(':')}:${props.userId ?? ''}`}
      {...props}
    />
  );
}

function ListingReviewsContent({
  source,
  target,
  userId,
  isAuthor,
  authPending = false,
  signInLink,
  profileLink,
  t = reviewText,
  locale = 'en-US',
  confirmDelete = () => window.confirm(t('Delete your review?')),
}: ListingReviewsProps) {
  const qc = useQueryClient();
  const reviews = useListingReviews(source);
  const myReview = userId ? reviews.data?.items.find((r) => r.userId === userId) : undefined;

  const [rating, setRating] = useState(5);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [editing, setEditing] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!editing) {
      setRating(myReview?.rating ?? 5);
      setTitle(myReview?.title ?? '');
      setBody(myReview?.body ?? '');
    }
  }, [myReview, editing]);

  const upsert = useMutation({
    mutationFn: async () => {
      setErrorMsg(null);
      await source.upsert({
        rating,
        title: title.trim() || null,
        body: body.trim() || null,
      });
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: source.listingKey });
      setEditing(false);
    },
    onError: (err) => {
      setErrorMsg(err instanceof Error ? err.message : t('Failed to save review'));
    },
  });

  const remove = useMutation({
    mutationFn: async () => {
      await source.remove();
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: source.listingKey });
      setErrorMsg(null);
      upsert.reset();
      setRating(5);
      setTitle('');
      setBody('');
      setEditing(false);
    },
  });

  // Owner or co-author: may reply to reviews, may not review (server-enforced).
  const isOwner = !!userId && isAuthor;
  const items = reviews.data?.items ?? [];
  const avg = reviews.data?.averageRating ?? null;

  return (
    <section id="reviews" className="mod-section mod-reviews" aria-labelledby="reviews-heading">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h2 id="reviews-heading">{t('Player reviews')}</h2>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          {avg != null ? <StarRating t={t} value={Math.round(avg)} size="sm" /> : null}
          <span>
            {avg != null
              ? `${avg.toLocaleString(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} · `
              : ''}
            {reviews.data
              ? reviews.data.total === 1
                ? t('{n} review', { n: reviews.data.total })
                : t('{n} reviews', { n: reviews.data.total })
              : ''}
          </span>
        </div>
      </div>

      {userId && !isOwner && !authPending && reviews.isSuccess ? (
        <fieldset
          disabled={upsert.isPending || remove.isPending}
          className="mb-6 min-w-0 space-y-3 rounded-lg border border-border/40 bg-card p-4"
        >
          <p className="text-sm font-semibold">
            {myReview ? t('Your review') : t('Write a review')}
          </p>
          <div className="flex items-center gap-3">
            <StarRating
              t={t}
              value={rating}
              onChange={(v) => {
                setEditing(true);
                upsert.reset();
                setRating(v);
              }}
            />
            <span className="font-mono text-xs text-muted-foreground">{rating} / 5</span>
          </div>
          <Input
            aria-label={t('Review title (optional)')}
            value={title}
            onChange={(e) => {
              setEditing(true);
              upsert.reset();
              setTitle(e.target.value);
            }}
            placeholder={t('Title (optional)')}
            maxLength={120}
          />
          <textarea
            aria-label={t('Your review')}
            value={body}
            onChange={(e) => {
              setEditing(true);
              upsert.reset();
              setBody(e.target.value);
            }}
            placeholder={t('Share your experience…')}
            maxLength={4000}
            rows={4}
            className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
          {errorMsg || remove.isError ? (
            <p role="alert" className="text-xs text-crimson">
              {errorMsg || t('Your review couldn’t be deleted. Please try again.')}
            </p>
          ) : null}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-mono text-xs text-muted-foreground">
              {body.length}/4000
              {upsert.isSuccess ? (
                <output className="ml-3 text-gilt">{t('Review saved')}</output>
              ) : null}
            </p>
            <div className="flex items-center gap-2">
              {myReview ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={async () => {
                    if (await confirmDelete()) remove.mutate();
                  }}
                  disabled={remove.isPending || upsert.isPending}
                >
                  <Trash2 className="mr-1 h-3.5 w-3.5" /> {t('Delete')}
                </Button>
              ) : null}
              <Button
                type="button"
                size="sm"
                onClick={() => upsert.mutate()}
                disabled={upsert.isPending || remove.isPending}
              >
                {upsert.isPending ? t('Saving…') : myReview ? t('Update review') : t('Post review')}
              </Button>
            </div>
          </div>
        </fieldset>
      ) : !userId && !authPending ? (
        <p className="mb-6 text-sm text-muted-foreground">
          {signInLink} {t('to leave a review.')}
        </p>
      ) : null}

      {isOwner ? (
        <p className="mb-6 text-xs text-muted-foreground">
          {target === 'collection'
            ? t(
                'You curate this collection. You can reply to reviews, but can’t review it yourself.',
              )
            : t(
                'You’re an author of this mod. You can reply to reviews, but can’t review it yourself.',
              )}
        </p>
      ) : null}

      {reviews.isLoading ? (
        <output className="text-sm text-muted-foreground">{t('Loading reviews…')}</output>
      ) : reviews.isError ? (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-sm">
          <p>{t('Reviews couldn’t be loaded.')}</p>
          <button
            type="button"
            className="underline underline-offset-4"
            onClick={() => reviews.refetch()}
          >
            {t('Try again')}
          </button>
        </div>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {t('No reviews yet. Be the first to share!')}
        </p>
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
                      alt={r.userName ?? t('reviewer')}
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <span>{(r.userName ?? '?').slice(0, 2).toUpperCase()}</span>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    {profileLink(
                      r.userId,
                      r.userName ?? t('anonymous'),
                      'text-sm font-medium hover:text-gilt hover:underline underline-offset-2',
                    )}
                    {r.userId === userId ? (
                      <span className="rounded border border-border px-1.5 font-mono text-xs text-muted-foreground">
                        {t('you')}
                      </span>
                    ) : null}
                    <StarRating t={t} value={r.rating} size="sm" />
                    <span className="font-mono text-xs text-muted-foreground">
                      {new Date(r.updatedAt).toLocaleDateString(locale)}
                    </span>
                  </div>
                  {r.title ? <p className="mt-1 text-sm font-semibold">{r.title}</p> : null}
                  {r.body ? (
                    <p className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">
                      {r.body}
                    </p>
                  ) : null}
                  <ReviewReplyBlock
                    t={t}
                    locale={locale}
                    review={r}
                    canReply={!!isOwner}
                    queryKey={source.queryKey}
                    onSave={(text) => source.reply(r.id, text)}
                    onDelete={() => source.removeReply(r.id)}
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
