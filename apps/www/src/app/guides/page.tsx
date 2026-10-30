'use client';

import { Input, Spinner, buttonVariants } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import { BookOpen, Search } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useState } from 'react';
import { api } from '../../lib/api';
import { useSession } from '../../lib/auth-client';
import { type GuideCard, GuideGrid } from '../components/guide-grid';

type GuideSort = 'recent' | 'rating' | 'popular' | 'title';

const SORTS: GuideSort[] = ['recent', 'rating', 'popular', 'title'];
const SORT_LABEL: Record<GuideSort, string> = {
  recent: 'recent',
  rating: 'top rated',
  popular: 'most reviewed',
  title: 'A–Z',
};

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
          <h1 className="font-display text-5xl text-parchment">Guides</h1>
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
          {session?.user ? (
            <Link
              href={'/my-guides' as Route}
              className={buttonVariants({ variant: 'outline', size: 'sm' })}
            >
              My guides
            </Link>
          ) : null}
          <Link href={'/guides/new' as Route} className={buttonVariants({ size: 'sm' })}>
            Write a guide
          </Link>
        </div>
      </div>

      {/* The first-party modding guide. It came out of the top bar, and this is
          where someone after how-to material already is — but it is framed
          separately from the grid below on purpose: it is maintained
          documentation, not a community submission, and listing it as one more
          card would misrepresent both. */}
      <Link
        href="/modding"
        className="grimoire-card flex flex-col items-start gap-3 p-5 transition-colors hover:border-gilt/40 sm:flex-row sm:items-center sm:justify-between"
      >
        <div className="flex items-start gap-3">
          <BookOpen className="mt-0.5 h-5 w-5 shrink-0 text-gilt" aria-hidden="true" />
          <div>
            <h2 className="font-semibold">Modding Guide</h2>
            <p className="mt-0.5 text-sm text-muted-foreground">
              The official walkthrough for building a mod — assets, manifests, the SDK, and getting
              your first change into the game.
            </p>
          </div>
        </div>
        <span
          className={`${buttonVariants({ variant: 'outline', size: 'sm' })} shrink-0`}
          aria-hidden="true"
        >
          Read it
        </span>
      </Link>

      {/* Moderation queue — only when toggled and there's something to review. */}
      {reviewMode && pendingCount > 0 ? (
        <section className="space-y-3">
          <h2 className="text-xl font-semibold tracking-tight">Awaiting review</h2>
          <GuideGrid items={(pending.data?.items ?? []) as GuideCard[]} />
        </section>
      ) : null}

      <section className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight">Published guides</h2>

        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-[260px] flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              type="search"
              aria-label="Search guides"
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
        ) : published.isError ? (
          // Not "No guides yet": an outage must not read as an empty library.
          <div className="grimoire-card flex flex-col items-center gap-3 p-10 text-center">
            <p className="text-sm text-muted-foreground">
              Guides could not be loaded. Check your connection and try again.
            </p>
            <button
              type="button"
              onClick={() => published.refetch()}
              className={buttonVariants({ variant: 'outline', size: 'sm' })}
            >
              Try again
            </button>
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
