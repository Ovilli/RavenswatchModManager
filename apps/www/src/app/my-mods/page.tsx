'use client';

import { Badge, Spinner } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import { Edit2, ExternalLink, Loader2, PlusCircle } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { api } from '../../lib/api';
import { useSession } from '../../lib/auth-client';

export default function MyModsPage() {
  const { data: session, isPending: sessionLoading } = useSession();

  const list = useQuery({
    queryKey: ['me', 'mods'],
    queryFn: () => api.me.mods(),
    enabled: !!session,
    staleTime: 10_000,
  });

  if (sessionLoading) {
    return (
      <main className="container mx-auto px-6 py-16">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Checking session…
        </div>
      </main>
    );
  }

  if (!session) {
    return (
      <main className="container mx-auto px-6 py-16">
        <div className="mx-auto max-w-md text-center">
          <h1 className="text-3xl font-bold tracking-tight">Sign in to manage your mods</h1>
          <p className="mt-3 text-sm text-muted-foreground">
            <em>My Mods</em> is your dashboard for editing metadata, shipping new versions, and
            managing your published mods.
          </p>
          <Link
            href={{ pathname: '/auth/signin' }}
            className="mt-6 inline-flex h-10 items-center justify-center rounded-md bg-primary px-6 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Sign in
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="container mx-auto max-w-5xl px-6 py-12">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-4xl font-bold tracking-tight">My Mods</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Mods you own. Click one to edit metadata, upload a new version, or manage assets.
          </p>
        </div>
        <Link
          href={{ pathname: '/publish' }}
          className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          <PlusCircle className="h-4 w-4" /> Publish a new mod
        </Link>
      </header>

      {list.isLoading ? (
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      ) : list.isError ? (
        <p className="text-sm text-destructive">Cannot reach API ({String(list.error)})</p>
      ) : (list.data?.items.length ?? 0) === 0 ? (
        <div className="grimoire-card p-10 text-center">
          <p className="text-lg font-semibold">No mods yet.</p>
          <p className="mt-2 text-sm text-muted-foreground">
            Publish your first mod to see it here.
          </p>
          <Link
            href={{ pathname: '/publish' }}
            className="mt-6 inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            <PlusCircle className="h-4 w-4" /> Publish a mod
          </Link>
        </div>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2">
          {list.data?.items.map((m) => (
            <li key={m.id}>
              <div className="grimoire-card overflow-hidden">
                {m.imageUrl ? (
                  <div className="aspect-[16/9] w-full overflow-hidden bg-muted">
                    <img
                      src={m.imageUrl}
                      alt={`${m.name} cover`}
                      className="h-full w-full object-cover"
                      loading="lazy"
                    />
                  </div>
                ) : (
                  <div className="aspect-[16/9] w-full bg-muted" />
                )}
                <div className="space-y-3 p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h2 className="truncate text-lg font-semibold">{m.name}</h2>
                      <p className="font-mono text-xs text-muted-foreground">{m.slug}</p>
                    </div>
                    {m.category ? <Badge variant="outline">{m.category}</Badge> : null}
                  </div>
                  {m.summary ? (
                    <p className="line-clamp-2 text-sm text-muted-foreground">{m.summary}</p>
                  ) : null}
                  <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                    <span>
                      {m.latestVersion ? `v${m.latestVersion}` : 'no versions'} ·{' '}
                      {m.downloads.toLocaleString()} dl
                    </span>
                  </div>
                  <div className="flex gap-2">
                    <Link
                      href={`/my-mods/${m.slug}` as Route}
                      className="inline-flex flex-1 items-center justify-center gap-1 rounded-md bg-secondary px-3 py-2 text-sm hover:bg-secondary/80"
                    >
                      <Edit2 className="h-3.5 w-3.5" /> Manage
                    </Link>
                    <Link
                      href={`/registry/${m.slug}` as Route}
                      className="inline-flex items-center justify-center gap-1 rounded-md border border-input bg-background px-3 py-2 text-sm hover:bg-accent"
                      title="View public page"
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                    </Link>
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
