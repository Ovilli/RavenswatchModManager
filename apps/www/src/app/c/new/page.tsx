'use client';
import { ApiError } from '@rsmm/api-client';
import { Button, Input, Spinner, buttonVariants } from '@rsmm/ui';
import { useMutation } from '@tanstack/react-query';
import { ArrowLeft } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { api } from '../../../lib/api';
import { useSession } from '../../../lib/auth-client';

export default function NewCollectionPage() {
  const router = useRouter();
  const { data: session, isPending } = useSession();
  const [slug, setSlug] = useState('');
  const [name, setName] = useState('');
  const [summary, setSummary] = useState('');
  const [isPublic, setIsPublic] = useState(true);

  const create = useMutation({
    mutationFn: () =>
      api.collections.create({
        slug,
        name,
        summary: summary.trim() || null,
        isPublic,
      }),
    onSuccess: () => {
      router.push(`/c/${slug}` as Route);
    },
  });

  if (isPending) {
    return (
      <main className="container mx-auto flex items-center justify-center px-6 py-24">
        <Spinner />
      </main>
    );
  }
  if (!session?.user) {
    return (
      <main className="container mx-auto space-y-4 px-6 py-12">
        <p className="text-muted-foreground">
          You need to{' '}
          <Link href="/auth/signin" className="underline">
            sign in
          </Link>{' '}
          to create a collection.
        </p>
      </main>
    );
  }

  return (
    <main className="container mx-auto max-w-2xl space-y-6 px-6 py-12">
      <Link href={'/c' as Route} className={buttonVariants({ variant: 'outline', size: 'sm' })}>
        <ArrowLeft className="mr-1.5 h-4 w-4" /> Back to Collections
      </Link>
      <h1 className="text-3xl font-bold tracking-tight">New collection</h1>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
        className="space-y-4"
      >
        <div className="space-y-1.5">
          <label htmlFor="col-slug" className="block text-sm font-medium">
            Slug (URL)
          </label>
          <Input
            id="col-slug"
            value={slug}
            onChange={(e) => setSlug(e.target.value.toLowerCase())}
            placeholder="hardcore-overhaul"
            pattern="[a-z0-9][a-z0-9_-]{1,63}"
            required
          />
          <p className="text-xs text-muted-foreground">
            Lowercase letters, numbers, dashes/underscores.
          </p>
        </div>
        <div className="space-y-1.5">
          <label htmlFor="col-name" className="block text-sm font-medium">
            Name
          </label>
          <Input
            id="col-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="My Mod Bundle"
            required
            maxLength={128}
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="col-summary" className="block text-sm font-medium">
            Summary
          </label>
          <textarea
            id="col-summary"
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            placeholder="What's the theme of this collection?"
            maxLength={512}
            rows={3}
            className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={isPublic}
            onChange={(e) => setIsPublic(e.target.checked)}
          />
          <span>Visible to everyone</span>
        </label>

        {create.isError ? (
          <p className="text-sm text-destructive">
            {create.error instanceof ApiError
              ? (create.error.body as { error?: string } | null)?.error ?? `HTTP ${create.error.status}`
              : 'Something went wrong'}
          </p>
        ) : null}

        <Button type="submit" disabled={create.isPending || !slug || !name}>
          {create.isPending ? 'Creating…' : 'Create collection'}
        </Button>
      </form>
    </main>
  );
}
