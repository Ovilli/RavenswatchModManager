'use client';

import { Spinner } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import { Edit2, ExternalLink, Loader2, PlusCircle } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { api } from '../../lib/api';
import { useSession } from '../../lib/auth-client';
import { ModCard } from '../components/mod-card';

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
    <main className="container mx-auto px-6 py-12">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-5xl text-parchment">My mods</h1>
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
        <ul className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {list.data?.items.map((m) => (
            <li key={m.id} className="flex min-w-0">
              <ModCard
                mod={{ ...m, author: m.authorName }}
                href={`/my-mods/${m.slug}` as Route}
                footer={
                  <>
                    <div className="space-y-1 text-xs text-muted-foreground">
                      {!m.latestVersion ? (
                        <p className="text-amber-500">No version published yet</p>
                      ) : null}
                      <p>Updated {new Date(m.updatedAt).toLocaleDateString()}</p>
                    </div>
                    <div className="flex gap-2">
                      <Link
                        href={`/my-mods/${m.slug}` as Route}
                        className="inline-flex flex-1 items-center justify-center gap-1 rounded-md bg-secondary px-3 py-2 text-sm hover:bg-secondary/80"
                      >
                        <Edit2 className="h-3.5 w-3.5" aria-hidden="true" /> Manage
                      </Link>
                      <Link
                        href={`/registry/${m.slug}` as Route}
                        className="inline-flex items-center justify-center gap-1 rounded-md border border-input bg-background px-3 py-2 text-sm hover:bg-accent"
                        title="View public page"
                        aria-label={`View ${m.name} public page`}
                      >
                        <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                      </Link>
                    </div>
                  </>
                }
              />
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
