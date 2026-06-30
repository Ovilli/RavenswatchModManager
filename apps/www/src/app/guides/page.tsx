'use client';

import { Badge, Spinner, buttonVariants } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import type { Route } from 'next';
import Link from 'next/link';
import { api } from '../../lib/api';
import { useSession } from '../../lib/auth-client';

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
            <p className="mt-1 text-xs text-muted-foreground">
              {g.ownerName ?? 'unknown'}
              {g.reviewCount > 0 && g.rating != null ? ` · ★ ${g.rating.toFixed(1)} (${g.reviewCount})` : ''}
            </p>
            {g.summary ? (
              <p className="mt-1 text-sm text-muted-foreground line-clamp-2">{g.summary}</p>
            ) : null}
          </div>
        </Link>
      ))}
    </div>
  );
}

export default function GuidesIndexPage() {
  const { data: session } = useSession();
  const published = useQuery({ queryKey: ['guides', 'list'], queryFn: () => api.guides.list() });
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
              href={'/guides?review=1' as Route}
              className={buttonVariants({ variant: 'outline', size: 'sm' })}
            >
              Review queue ({pendingCount})
            </Link>
          ) : null}
          <Link href={'/guides/new' as Route} className={buttonVariants({ size: 'sm' })}>
            Write a guide
          </Link>
        </div>
      </div>

      {session?.user && (mine.data?.items.length ?? 0) > 0 ? (
        <section className="space-y-3">
          <h2 className="text-xl font-semibold tracking-tight">Your guides</h2>
          <GuideGrid items={(mine.data?.items ?? []) as GuideCard[]} />
        </section>
      ) : null}

      <section className="space-y-3">
        <h2 className="text-xl font-semibold tracking-tight">Published guides</h2>
        {published.isLoading ? (
          <div className="flex items-center justify-center py-24">
            <Spinner />
          </div>
        ) : !published.data || published.data.items.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-12 text-center">
            <h3 className="text-lg font-semibold">No guides yet</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Be the first to write a guide for the community.
            </p>
            <Link href={'/guides/new' as Route} className={`${buttonVariants()} mt-4`}>
              Write a guide
            </Link>
          </div>
        ) : (
          <GuideGrid items={published.data.items as GuideCard[]} />
        )}
      </section>
    </main>
  );
}
