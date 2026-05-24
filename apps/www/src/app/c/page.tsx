'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import type { Route } from 'next';
import { Spinner } from '@rsmm/ui';
import { api } from '../../lib/api';

export default function CollectionsIndexPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['collections', 'list'],
    queryFn: () => api.collections.list(),
  });

  return (
    <main className="container mx-auto space-y-6 px-6 py-12">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Collections</h1>
          <p className="mt-1 text-muted-foreground">
            Mod bundles curated by the community.
          </p>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-24">
          <Spinner />
        </div>
      ) : !data || data.items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-12 text-center">
          <h2 className="text-lg font-semibold">No collections yet</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Be the first to create a curated bundle of mods.
          </p>
          <Link
            href={'/c/new' as Route}
            className="mt-4 inline-flex h-10 items-center justify-center rounded-md bg-primary px-6 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Create a collection
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.items.map((c) => (
            <Link
              key={c.id}
              href={`/c/${c.slug}` as Route}
              className="group block overflow-hidden rounded-lg border border-border bg-card transition-colors hover:border-primary/50"
            >
              {c.imageUrl ? (
                <div className="aspect-[21/9] w-full overflow-hidden bg-muted">
                  <img
                    src={c.imageUrl}
                    alt={`${c.name} cover`}
                    className="h-full w-full object-cover transition-opacity group-hover:opacity-90"
                    loading="lazy"
                  />
                </div>
              ) : (
                <div className="aspect-[21/9] w-full bg-muted" />
              )}
              <div className="p-4">
                <h2 className="text-base font-semibold leading-tight">{c.name}</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  {c.ownerName ?? 'unknown'} · {c.modCount} mod{c.modCount === 1 ? '' : 's'}
                </p>
                {c.summary ? (
                  <p className="mt-1 text-sm text-muted-foreground line-clamp-2">{c.summary}</p>
                ) : null}
              </div>
            </Link>
          ))}
        </div>
      )}
    </main>
  );
}
