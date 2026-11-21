'use client';
import { Badge, Button, Spinner, buttonVariants } from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ExternalLink, RotateCcw } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { api } from '../../lib/api';

/**
 * Every hidden or removed mod, report or not. Before this, a takedown made
 * without a report (from the API, or while editing the listing) showed up
 * nowhere here, so admins couldn't tell a hidden mod from a deleted one.
 */
export function TakedownList() {
  const qc = useQueryClient();
  const takedowns = useQuery({
    queryKey: ['admin', 'takedowns'],
    queryFn: () => api.moderation.takedowns(),
    retry: false,
  });
  const restore = useMutation({
    mutationFn: (slug: string) => api.moderation.takedown(slug, { takedownStatus: 'active' }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin'] });
    },
  });

  if (takedowns.isLoading) {
    return (
      <div className="flex justify-center py-6">
        <Spinner />
      </div>
    );
  }
  if (takedowns.isError) {
    return (
      <p className="text-sm text-destructive">
        Couldn’t load taken-down mods:{' '}
        {takedowns.error instanceof Error ? takedowns.error.message : String(takedowns.error)}
      </p>
    );
  }
  const items = takedowns.data?.items ?? [];
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No mods are hidden or removed.</p>;
  }

  return (
    <>
      {restore.error ? (
        <p className="text-sm text-destructive">
          Restore failed:{' '}
          {restore.error instanceof Error ? restore.error.message : String(restore.error)}
        </p>
      ) : null}
      <ul className="space-y-3">
        {items.map((m) => (
          <li
            key={m.slug}
            className="grimoire-card flex flex-col gap-4 p-5 sm:flex-row sm:items-start sm:justify-between"
          >
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <Link
                  href={`/registry/${m.slug}` as Route}
                  className="font-semibold text-parchment underline-offset-4 hover:underline"
                >
                  {m.name}
                </Link>
                <Badge variant="destructive" className="capitalize">
                  {m.takedownStatus}
                </Badge>
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {m.slug} · {m.author ?? 'unknown author'} · changed{' '}
                {new Date(m.updatedAt).toLocaleDateString()}
              </p>
              {m.takedownReason ? (
                <blockquote className="mt-3 border-l-2 border-gilt/40 bg-background/40 px-4 py-2.5 text-sm text-parchment/90">
                  {m.takedownReason}
                </blockquote>
              ) : (
                <p className="mt-2 text-xs text-muted-foreground">No reason recorded.</p>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Link
                href={`/registry/${m.slug}` as Route}
                className={`${buttonVariants({ variant: 'ghost', size: 'sm' })} gap-1.5`}
              >
                <ExternalLink className="h-3.5 w-3.5" aria-hidden /> View page
              </Link>
              <Button
                size="sm"
                variant="outline"
                className="gap-1.5"
                disabled={restore.isPending}
                onClick={() => {
                  if (window.confirm(`Restore “${m.name}”? It goes back on the public registry.`)) {
                    restore.mutate(m.slug);
                  }
                }}
              >
                <RotateCcw className="h-3.5 w-3.5" aria-hidden /> Restore
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
