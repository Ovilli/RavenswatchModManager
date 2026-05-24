'use client';
import { Badge, Button, Spinner, buttonVariants } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { api } from '../../lib/api';
import { useSession } from '../../lib/auth-client';

export default function CollectionsPage() {
  const { data: session } = useSession();
  const list = useQuery({
    queryKey: ['collections', 'public'],
    queryFn: () => api.collections.list(),
  });

  return (
    <main className="relative overflow-hidden animate-page-in">
      <div className="container mx-auto space-y-6 px-6 py-12">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-4xl font-bold tracking-tight">Collections</h1>
            <p className="text-sm text-muted-foreground">
              Curated bundles of mods made by the community.
            </p>
          </div>
          {session?.user ? (
            <Link href={'/c/new' as Route} className={buttonVariants({ size: 'sm' })}>
              <Plus className="mr-1 h-4 w-4" /> New collection
            </Link>
          ) : null}
        </header>

        {list.isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Spinner />
          </div>
        ) : list.isError ? (
          <p className="text-sm text-destructive">Cannot reach API.</p>
        ) : (list.data?.items ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground">No public collections yet.</p>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {list.data?.items.map((c) => (
              <Link
                key={c.id}
                href={`/c/${c.slug}` as Route}
                className="grimoire-card p-5 transition-colors hover:border-gilt/40"
              >
                <div className="flex items-start justify-between gap-3">
                  <h2 className="text-lg font-semibold leading-tight">{c.name}</h2>
                  <Badge variant="outline" className="shrink-0 text-[0.6rem]">
                    {c.modCount} mod{c.modCount === 1 ? '' : 's'}
                  </Badge>
                </div>
                {c.summary ? (
                  <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">{c.summary}</p>
                ) : null}
                <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                  <span>by {c.ownerName ?? 'unknown'}</span>
                  <span>·</span>
                  <span>updated {new Date(c.updatedAt).toLocaleDateString()}</span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
