'use client';

import { Button, Spinner, buttonVariants } from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { HeartOff, Loader2 } from 'lucide-react';
import Link from 'next/link';
import { api } from '../../../lib/api';
import { useSession } from '../../../lib/auth-client';
import { ModCard } from '../../components/mod-card';

export default function FollowedModsPage() {
  const { data: session, isPending: sessionLoading } = useSession();
  const qc = useQueryClient();

  const follows = useQuery({
    queryKey: ['me', 'follows'],
    queryFn: () => api.me.follows(),
    enabled: !!session,
  });

  const unfollow = useMutation({
    mutationFn: (slug: string) => api.mods.unfollow(slug),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['me', 'follows'] });
    },
  });

  if (sessionLoading) {
    return (
      <main className="container mx-auto px-6 py-16">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      </main>
    );
  }

  if (!session) {
    return (
      <main className="container mx-auto px-6 py-16">
        <div className="mx-auto max-w-md text-center">
          <h1 className="text-3xl font-bold tracking-tight">Sign in required</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Sign in to see the mods you follow.
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

  const items = follows.data?.items ?? [];

  return (
    <main className="relative overflow-hidden animate-page-in">
      <div className="container mx-auto space-y-6 px-6 py-12">
        <header className="space-y-2">
          <h1 className="text-4xl font-bold tracking-tight">Followed mods</h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            You get a notification whenever one of these mods publishes a new version.
          </p>
        </header>

        {follows.isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Spinner />
          </div>
        ) : follows.isError ? (
          <div className="grimoire-card flex flex-col items-center gap-3 p-10 text-center">
            <p className="text-sm text-muted-foreground">
              Your followed mods could not be loaded. Try again in a moment.
            </p>
            <button
              type="button"
              onClick={() => follows.refetch()}
              className={buttonVariants({ variant: 'outline', size: 'sm' })}
            >
              Try again
            </button>
          </div>
        ) : items.length === 0 ? (
          <div className="grimoire-card flex flex-col items-center gap-3 p-10 text-center">
            <p className="text-sm text-muted-foreground">
              You are not following any mods yet. Follow a mod from its page to get notified about
              new versions.
            </p>
            <Link
              href={{ pathname: '/registry' }}
              className={buttonVariants({ variant: 'outline', size: 'sm' })}
            >
              Browse the registry
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {items.map((f) => (
              <div key={f.slug} className="space-y-2">
                <ModCard
                  mod={{
                    id: f.slug,
                    slug: f.slug,
                    name: f.name,
                    author: f.authorName ?? null,
                    summary: f.summary ?? null,
                    license: null,
                    latestVersion: f.latestVersion ?? null,
                    downloads: f.downloads ?? 0,
                    updatedAt: f.updatedAt ?? f.followedAt,
                    category: (f.category as never) ?? null,
                    imageUrl: f.imageUrl,
                    rating: f.rating ?? null,
                    tags: [],
                    nsfw: f.nsfw,
                  }}
                />
                <div className="flex items-center justify-between px-1 text-xs text-muted-foreground">
                  <span>Followed {new Date(f.followedAt).toLocaleDateString()}</span>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => unfollow.mutate(f.slug)}
                    disabled={unfollow.isPending}
                  >
                    <HeartOff className="mr-1 h-3.5 w-3.5" /> Unfollow
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
