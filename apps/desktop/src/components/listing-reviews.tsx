import {
  ListingRatingSummary as SharedRatingSummary,
  ListingReviews as SharedListingReviews,
  createReviewSource,
  type ReviewTarget,
} from '@rsmm/ui/reviews';
import { Link } from '@tanstack/react-router';
import { api } from '../lib/api';
import { useSession } from '../lib/auth-client';
import { useT } from '../lib/i18n-react';
import { useDialog } from './toast';

export function ListingRatingSummary({
  target,
  slug,
  fallbackRating,
}: {
  target: ReviewTarget;
  slug: string;
  fallbackRating?: number | null;
}) {
  const t = useT();
  return (
    <SharedRatingSummary
      t={t}
      locale={t.tag}
      source={createReviewSource(api, target, slug)}
      fallbackRating={fallbackRating}
    />
  );
}

/** Only session, navigation and native dialog integration belong to the desktop. */
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
  const dialog = useDialog();
  const t = useT();
  return (
    <SharedListingReviews
      t={t}
      locale={t.tag}
      source={createReviewSource(api, target, slug)}
      target={target}
      userId={session?.user.id}
      authPending={isPending}
      isAuthor={isAuthor}
      confirmDelete={() => dialog.confirm({ title: t('Delete your review?'), destructive: true })}
      signInLink={
        <Link to="/signin" className="text-foreground underline underline-offset-2 hover:text-gilt">
          {t('Sign in')}
        </Link>
      }
      profileLink={(id, name, className) => (
        <a
          href={`https://rsmm.me/u/${encodeURIComponent(id)}`}
          target="_blank"
          rel="noopener noreferrer"
          className={className}
        >
          {name}
        </a>
      )}
    />
  );
}
