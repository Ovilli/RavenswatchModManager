'use client';
import { ApiError } from '@rsmm/api-client';
import { Badge, Button, Input, Spinner, buttonVariants } from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Globe, Lock, Plus, Trash2 } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { use, useState } from 'react';
import { api } from '../../../lib/api';
import { useSession } from '../../../lib/auth-client';

export default function CollectionDetailPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  const { data: session } = useSession();
  const qc = useQueryClient();
  const [addSlug, setAddSlug] = useState('');
  const [addError, setAddError] = useState<string | null>(null);

  const detail = useQuery({
    queryKey: ['collections', slug],
    queryFn: () => api.collections.get(slug),
    retry: (count, err) => (err instanceof ApiError && err.status === 404 ? false : count < 1),
  });

  const addMod = useMutation({
    mutationFn: (modSlug: string) => api.collections.addMod(slug, modSlug),
    onSuccess: async () => {
      setAddSlug('');
      setAddError(null);
      await qc.invalidateQueries({ queryKey: ['collections', slug] });
    },
    onError: (err) => {
      setAddError(
        err instanceof ApiError
          ? (err.body as { error?: string } | null)?.error ?? `HTTP ${err.status}`
          : 'Failed to add',
      );
    },
  });

  const removeMod = useMutation({
    mutationFn: (modSlug: string) => api.collections.removeMod(slug, modSlug),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['collections', slug] });
    },
  });

  const remove = useMutation({
    mutationFn: () => api.collections.remove(slug),
    onSuccess: () => {
      window.location.href = '/c';
    },
  });

  if (detail.isLoading) {
    return (
      <main className="container mx-auto flex items-center justify-center px-6 py-24">
        <Spinner />
      </main>
    );
  }

  if (detail.isError || !detail.data) {
    return (
      <main className="container mx-auto space-y-6 px-6 py-12">
        <Link href={'/c' as Route} className={buttonVariants({ variant: 'outline', size: 'sm' })}>
          <ArrowLeft className="mr-1.5 h-4 w-4" /> Back to Collections
        </Link>
        <p className="text-muted-foreground">Collection not found.</p>
      </main>
    );
  }

  const c = detail.data;
  const isOwner = session?.user?.id === c.ownerId;

  return (
    <main className="container mx-auto space-y-6 px-6 py-12">
      <Link href={'/c' as Route} className={buttonVariants({ variant: 'outline', size: 'sm' })}>
        <ArrowLeft className="mr-1.5 h-4 w-4" /> Back to Collections
      </Link>

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-3xl font-bold tracking-tight">{c.name}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            by{' '}
            <Link
              href={`/u/${c.ownerId}` as Route}
              className="text-foreground hover:text-gilt hover:underline underline-offset-2"
            >
              {c.ownerName ?? 'unknown'}
            </Link>{' '}
            · updated {new Date(c.updatedAt).toLocaleDateString()}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline">
            {c.isPublic ? (
              <>
                <Globe className="mr-1 h-3 w-3" /> Public
              </>
            ) : (
              <>
                <Lock className="mr-1 h-3 w-3" /> Private
              </>
            )}
          </Badge>
          <Badge variant="outline">{c.modCount} mod{c.modCount === 1 ? '' : 's'}</Badge>
          {isOwner ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                if (confirm('Delete this collection?')) remove.mutate();
              }}
            >
              <Trash2 className="mr-1 h-3.5 w-3.5" /> Delete
            </Button>
          ) : null}
        </div>
      </header>

      {c.summary ? (
        <p className="max-w-3xl text-muted-foreground">{c.summary}</p>
      ) : null}

      {isOwner ? (
        <section className="grimoire-card space-y-3 p-4">
          <h2 className="text-sm font-semibold">Add a mod by slug</h2>
          <div className="flex flex-wrap gap-2">
            <Input
              value={addSlug}
              onChange={(e) => setAddSlug(e.target.value.toLowerCase())}
              placeholder="mod-slug"
              className="max-w-sm"
            />
            <Button
              type="button"
              onClick={() => {
                if (addSlug) addMod.mutate(addSlug);
              }}
              disabled={!addSlug || addMod.isPending}
            >
              <Plus className="mr-1 h-4 w-4" /> Add
            </Button>
          </div>
          {addError ? <p className="text-xs text-destructive">{addError}</p> : null}
        </section>
      ) : null}

      {c.mods.length === 0 ? (
        <p className="text-sm text-muted-foreground">This collection has no mods yet.</p>
      ) : (
        <ul className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {c.mods.map((m) => (
            <li key={m.id} className="grimoire-card overflow-hidden">
              <Link href={`/registry/${m.slug}` as Route} className="block">
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
                <div className="space-y-1.5 p-4">
                  <h3 className="text-base font-semibold leading-tight">{m.name}</h3>
                  <p className="text-xs text-muted-foreground">{m.author ?? 'unknown'}</p>
                  {m.summary ? (
                    <p className="text-xs text-muted-foreground line-clamp-2">{m.summary}</p>
                  ) : null}
                </div>
              </Link>
              {isOwner ? (
                <div className="border-t border-border/40 px-4 py-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => removeMod.mutate(m.slug)}
                  >
                    <Trash2 className="mr-1 h-3.5 w-3.5" /> Remove
                  </Button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
