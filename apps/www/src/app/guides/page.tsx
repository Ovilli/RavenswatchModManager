'use client';

import { Badge, Input, Spinner, buttonVariants } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import { Search, Star } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useState } from 'react';
import { api } from '../../lib/api';
import { useSession } from '../../lib/auth-client';

type GuideSort = 'recent' | 'rating' | 'popular' | 'title';

const SORTS: GuideSort[] = ['recent', 'rating', 'popular', 'title'];
const SORT_LABEL: Record<GuideSort, string> = {
  recent: 'recent',
  rating: 'top rated',
  popular: 'most reviewed',
  title: 'A–Z',
};

const STATUS_LABEL: Record<string, string> = {
  draft: 'Draft',
  pending: 'In review',
  approved: 'Published',
  rejected: 'Needs changes',
};

interface GuideCard {
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

function GuideGrid({ items }: { items: GuideCard[] }) {
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
            <div className="aspect-[21/9] w-full bg-muted" />
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

function GuidesIndex() {
  const { data: session } = useSession();
  const router = useRouter();
  const search = useSearchParams();

  // Seed state from the URL so search/sort are shareable and survive the
  // back button (and Google's sitelinks search box lands on `?q=`).
  const reviewMode = search.get('review') === '1';
  const initialSort = (search.get('sort') as GuideSort) ?? 'recent';
  const [q, setQ] = useState(() => search.get('q') ?? '');
  const [sort, setSort] = useState<GuideSort>(SORTS.includes(initialSort) ? initialSort : 'recent');

  // Debounce the search box so we don't refetch on every keystroke.
  const [debouncedQ, setDebouncedQ] = useState(q.trim());
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);

  // Mirror the debounced query + sort back into the URL (replace, no history
  // spam) so the address bar reflects what's on screen.
  useEffect(() => {
    const params = new URLSearchParams();
    if (debouncedQ) params.set('q', debouncedQ);
    if (sort !== 'recent') params.set('sort', sort);
    if (reviewMode) params.set('review', '1');
    const qs = params.toString();
    router.replace((qs ? `/guides?${qs}` : '/guides') as Route, { scroll: false });
  }, [debouncedQ, sort, reviewMode, router]);

  const published = useQuery({
    queryKey: ['guides', 'list', debouncedQ, sort],
    queryFn: () => api.guides.list({ q: debouncedQ || undefined, sort }),
  });
  const mine = useQuery({
    queryKey: ['guides', 'mine'],
    queryFn: () => api.guides.mine(),
    enabled: !!session?.user,
  });
  const pending = useQuery({
    queryKey: ['guides', 'pending'],
    queryFn: () => api.guides.pending(),
    enabled: !!session?.user,
    retry: false,
  });

  const pendingCount = pending.data?.items.length ?? 0;

  return (
    <main className="container mx-auto space-y-10 px-6 py-12">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Guides</h1>
          <p className="mt-1 text-muted-foreground">
            Community tutorials and how-tos for Ravenswatch — modding, strategies, and more.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {pendingCount > 0 ? (
            <Link
              href={(reviewMode ? '/guides' : '/guides?review=1') as Route}
              className={buttonVariants({
                variant: reviewMode ? 'default' : 'outline',
                size: 'sm',
              })}
            >
              Review queue ({pendingCount})
            </Link>
          ) : null}
          <Link href={'/guides/new' as Route} className={buttonVariants({ size: 'sm' })}>
            Write a guide
          </Link>
        </div>
      </div>

      {/* Moderation queue — only when toggled and there's something to review. */}
      {reviewMode && pendingCount > 0 ? (
        <section className="space-y-3">
          <h2 className="text-xl font-semibold tracking-tight">Awaiting review</h2>
          <GuideGrid items={(pending.data?.items ?? []) as GuideCard[]} />
        </section>
      ) : null}

      {session?.user && (mine.data?.items.length ?? 0) > 0 ? (
        <section className="space-y-3">
          <h2 className="text-xl font-semibold tracking-tight">Your guides</h2>
          <GuideGrid items={(mine.data?.items ?? []) as GuideCard[]} />
        </section>
      ) : null}

      <section className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight">Published guides</h2>

        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-[260px] flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search guides by title, summary, or content…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="pl-9"
            />
          </div>
          {SORTS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setSort(s)}
              className={buttonVariants({
                variant: sort === s ? 'default' : 'outline',
                size: 'sm',
              })}
            >
              {SORT_LABEL[s]}
            </button>
          ))}
        </div>

        {published.isLoading ? (
          <div className="flex items-center justify-center py-24">
            <Spinner />
          </div>
        ) : !published.data || published.data.items.length === 0 ? (
          debouncedQ ? (
            <div className="rounded-lg border border-dashed border-border p-12 text-center">
              <h3 className="text-lg font-semibold">No guides match “{debouncedQ}”</h3>
              <p className="mt-1 text-sm text-muted-foreground">Try a different search term.</p>
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-border p-12 text-center">
              <h3 className="text-lg font-semibold">No guides yet</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                Be the first to write a guide for the community.
              </p>
              <Link href={'/guides/new' as Route} className={`${buttonVariants()} mt-4`}>
                Write a guide
              </Link>
            </div>
          )
        ) : (
          <GuideGrid items={published.data.items as GuideCard[]} />
        )}
      </section>
    </main>
  );
}

export default function GuidesIndexPage() {
  return (
    <Suspense
      fallback={
        <main className="container mx-auto flex items-center justify-center px-6 py-24">
          <Spinner />
        </main>
      }
    >
      <GuidesIndex />
    </Suspense>
  );
}
