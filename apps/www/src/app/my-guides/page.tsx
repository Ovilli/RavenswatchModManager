'use client';

import { Spinner } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import { Loader2, PlusCircle } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { api } from '../../lib/api';
import { useSession } from '../../lib/auth-client';
import { type GuideCard, GuideGrid } from '../components/guide-grid';

export default function MyGuidesPage() {
  const { data: session, isPending: sessionLoading } = useSession();

  const list = useQuery({
    queryKey: ['guides', 'mine'],
    queryFn: () => api.guides.mine(),
    enabled: !!session,
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
          <h1 className="text-3xl font-bold tracking-tight">Sign in to see your guides</h1>
          <p className="mt-3 text-sm text-muted-foreground">
            <em>My Guides</em> lists every guide you wrote, published or not.
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

  const newGuide = (
    <Link
      href={'/guides/new' as Route}
      className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
    >
      <PlusCircle className="h-4 w-4" /> Write a guide
    </Link>
  );

  return (
    <main className="container mx-auto px-6 py-12">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-5xl text-parchment">My guides</h1>
          <p className="mt-2 text-muted-foreground">
            Every guide you wrote, including drafts and ones still in review. Open one to edit it.
          </p>
        </div>
        {newGuide}
      </header>

      {list.isLoading ? (
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      ) : list.isError ? (
        <p className="text-sm text-destructive">Cannot reach API ({String(list.error)})</p>
      ) : (list.data?.items.length ?? 0) === 0 ? (
        <div className="grimoire-card flex flex-col items-center gap-3 p-10 text-center">
          <p className="text-lg font-semibold">No guides yet.</p>
          <p className="text-sm text-muted-foreground">Write your first guide to see it here.</p>
          {newGuide}
        </div>
      ) : (
        <GuideGrid items={(list.data?.items ?? []) as GuideCard[]} />
      )}
    </main>
  );
}
