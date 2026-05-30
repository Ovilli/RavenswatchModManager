'use client';
import { ApiError } from '@rsmm/api-client';
import { Badge, Spinner, buttonVariants } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Star } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { use } from 'react';
import { api } from '../../../lib/api';

function initialsFor(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const first = parts[0];
  if (!first) return '?';
  if (parts.length === 1) return first.slice(0, 2).toUpperCase();
  const second = parts[1];
  return ((first[0] ?? '') + (second?.[0] ?? '')).toUpperCase();
}

export default function AuthorPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  const detail = useQuery({
    queryKey: ['users', 'profile', id],
    queryFn: () => api.users.profile(id),
    retry: (count, err) => (err instanceof ApiError && err.status === 404 ? false : count < 1),
  });

  if (detail.isLoading) {
    return (
      <main className="relative overflow-hidden animate-page-in">
        <div className="container mx-auto flex items-center justify-center px-6 py-24">
          <Spinner />
        </div>
      </main>
    );
  }

  if (detail.isError || !detail.data) {
    const notFound = detail.error instanceof ApiError && detail.error.status === 404;
    return (
      <main className="relative overflow-hidden animate-page-in">
        <div className="container mx-auto space-y-6 px-6 py-12">
          <Link href="/registry" className={buttonVariants({ variant: 'outline', size: 'sm' })}>
            <ArrowLeft className="mr-1.5 h-4 w-4" /> Back to Registry
          </Link>
          <p className="text-muted-foreground">
            {notFound ? `No author matches “${id}”.` : `Cannot reach API (${String(detail.error)})`}
          </p>
        </div>
      </main>
    );
  }

  const { user, mods, totalDownloads } = detail.data;
  const joined = new Date(user.joinedAt).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
  });

  return (
    <main className="relative overflow-hidden animate-page-in">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_right,hsl(var(--gilt)/0.06),transparent_50%)]" />
      <div className="relative container mx-auto space-y-8 px-6 py-12">
        <Link href="/registry" className={buttonVariants({ variant: 'outline', size: 'sm' })}>
          <ArrowLeft className="mr-1.5 h-4 w-4" /> Back to Registry
        </Link>

        <header className="flex flex-col items-start gap-5 sm:flex-row sm:items-center">
          <div className="flex h-20 w-20 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border bg-muted text-xl font-semibold text-foreground">
            {user.image ? (
              <img src={user.image} alt={user.name} className="h-full w-full object-cover" />
            ) : (
              <span>{initialsFor(user.name)}</span>
            )}
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-3xl font-bold tracking-tight">{user.name}</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {user.handle ? `@${user.handle} · ` : ''}joined {joined}
            </p>
            <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
              <Badge variant="outline">
                {mods.length} mod{mods.length === 1 ? '' : 's'}
              </Badge>
              <Badge variant="outline">{totalDownloads.toLocaleString()} total downloads</Badge>
            </div>
          </div>
        </header>

        {mods.length === 0 ? (
          <p className="text-muted-foreground">This author has not published any mods yet.</p>
        ) : (
          <section>
            <h2 className="mb-4 text-xl font-bold tracking-tight">Published mods</h2>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {mods.map((m) => (
                <Link
                  key={m.id}
                  href={`/registry/${m.slug}` as Route}
                  className="grimoire-card overflow-hidden hover:border-gilt/40 transition-colors"
                >
                  <div className="relative">
                    {m.imageUrl ? (
                      <div className="aspect-[16/9] w-full overflow-hidden bg-muted">
                        <img
                          src={m.imageUrl}
                          alt={`${m.name} preview`}
                          className="h-full w-full object-cover"
                          loading="lazy"
                        />
                      </div>
                    ) : (
                      <div className="aspect-[16/9] w-full bg-muted" />
                    )}
                    {m.featured ? (
                      <Badge className="absolute left-2 top-2 bg-gilt/15 text-[0.65rem] text-gilt border-gilt/40 backdrop-blur-sm">
                        <Star className="mr-1 h-3 w-3" /> Featured
                      </Badge>
                    ) : null}
                  </div>
                  <div className="space-y-2 p-4">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <h3 className="text-base font-semibold leading-tight text-foreground truncate">
                          {m.name}
                        </h3>
                        {m.latestVersion ? (
                          <p className="font-mono text-xs text-muted-foreground">
                            v{m.latestVersion}
                          </p>
                        ) : null}
                      </div>
                      {m.category ? (
                        <Badge variant="secondary" className="shrink-0 text-[0.6rem]">
                          {m.category}
                        </Badge>
                      ) : null}
                    </div>
                    {m.summary ? (
                      <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
                        {m.summary}
                      </p>
                    ) : null}
                    <div className="flex items-center gap-3 text-xs text-muted-foreground">
                      <span>{m.downloads.toLocaleString()} dl</span>
                      {m.rating != null ? <span>★ {m.rating.toFixed(1)}</span> : null}
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
