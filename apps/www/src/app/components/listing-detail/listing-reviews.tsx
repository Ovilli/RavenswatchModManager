'use client';
import {
  ListingReviews as SharedListingReviews,
  ListingRatingSummary as SharedListingRatingSummary,
  createReviewSource,
  type ReviewTarget,
} from '@rsmm/ui/reviews';
import type { Route } from 'next';
import Link from 'next/link';
import { api } from '../../../lib/api';
import { useSession } from '../../../lib/auth-client';

export type { ReviewTarget } from '@rsmm/ui/reviews';

export function ListingRatingSummary({
  target,
  slug,
  fallbackRating,
}: {
  target: ReviewTarget;
  slug: string;
  fallbackRating?: number | null;
}) {
  return (
    <SharedListingRatingSummary
      source={createReviewSource(api, target, slug)}
      fallbackRating={fallbackRating}
    />
  );
}

export function ListingReviews({
  target,
  slug,
  isAuthor,
}: {
  target: ReviewTarget;
  slug: string;
  isAuthor: boolean;
}) {
  const { data: session, isPending } = useSession();
  return (
    <SharedListingReviews
      source={createReviewSource(api, target, slug)}
      target={target}
      userId={session?.user.id}
      authPending={isPending}
      isAuthor={isAuthor}
      signInLink={
        <Link
          href="/auth/signin"
          className="text-foreground underline underline-offset-2 hover:text-gilt"
        >
          Sign in
        </Link>
      }
      profileLink={(id, name, className) => (
        <Link href={`/u/${id}` as Route} className={className}>
          {name}
        </Link>
      )}
    />
  );
}
