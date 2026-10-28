'use client';

import { Badge } from '@rsmm/ui';
import { Star } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { ModCover } from './mod-cover';

export const STATUS_LABEL: Record<string, string> = {
  draft: 'Draft',
  pending: 'In review',
  approved: 'Published',
  rejected: 'Needs changes',
};

export interface GuideCard {
  id: string;
  slug: string;
  title: string;
  summary: string | null;
  imageUrl: string | null;
  ownerName: string | null;
  status: string;
  rating: number | null;
  reviewCount: number;
}

// Five-star meter; fills to the nearest half based on the average rating.
function Stars({ rating }: { rating: number }) {
  return (
    <span className="inline-flex" aria-label={`${rating.toFixed(1)} out of 5`}>
      {[1, 2, 3, 4, 5].map((s) => (
        <Star
          key={s}
          className={`h-3.5 w-3.5 ${
            rating >= s - 0.25 ? 'fill-yellow-500 text-yellow-500' : 'text-muted-foreground/40'
          }`}
        />
      ))}
    </span>
  );
}

export function GuideGrid({ items }: { items: GuideCard[] }) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      {items.map((g) => (
        <Link
          key={g.id}
          href={`/guides/${g.slug}` as Route}
          className="group block overflow-hidden rounded-lg border border-border bg-card transition-colors hover:border-primary/50"
        >
          {g.imageUrl ? (
            <div className="aspect-[21/9] w-full overflow-hidden bg-muted">
              <img
                src={g.imageUrl}
                alt={`${g.title} cover`}
                className="h-full w-full object-cover transition-opacity group-hover:opacity-90"
                loading="lazy"
              />
            </div>
          ) : (
            <ModCover seed={g.slug} name={g.title} className="aspect-[21/9] w-full" />
          )}
          <div className="p-4">
            <div className="flex items-start justify-between gap-2">
              <h2 className="text-base font-semibold leading-tight">{g.title}</h2>
              {g.status !== 'approved' ? (
                <Badge variant="outline" className="shrink-0 text-[0.6rem]">
                  {STATUS_LABEL[g.status] ?? g.status}
                </Badge>
              ) : null}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{g.ownerName ?? 'unknown'}</p>
            {g.reviewCount > 0 && g.rating != null ? (
              <div className="mt-1.5 flex items-center gap-1.5">
                <Stars rating={g.rating} />
                <span className="text-xs text-muted-foreground">
                  {g.rating.toFixed(1)} ({g.reviewCount})
                </span>
              </div>
            ) : (
              <p className="mt-1.5 text-xs text-muted-foreground/60">No reviews yet</p>
            )}
            {g.summary ? (
              <p className="mt-1.5 text-sm text-muted-foreground line-clamp-2">{g.summary}</p>
            ) : null}
          </div>
        </Link>
      ))}
    </div>
  );
}
