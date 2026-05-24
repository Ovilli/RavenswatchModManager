'use client';
import { ApiError } from '@rsmm/api-client';
import { Button, Input, Spinner, buttonVariants } from '@rsmm/ui';
import { useMutation } from '@tanstack/react-query';
import { ArrowLeft, ImageIcon, Loader2, Upload, X } from 'lucide-react';
import type { Route } from 'next';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { api } from '../../../lib/api';
import { useSession } from '../../../lib/auth-client';

const MDEditor = dynamic(() => import('@uiw/react-md-editor'), { ssr: false });

function describeApiError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { error?: string } | null;
    if (body?.error) return body.error;
    return `HTTP ${err.status}`;
  }
  return err instanceof Error ? err.message : String(err);
}

async function uploadImage(file: File, slug: string): Promise<string> {
  const contentType = file.type as 'image/png' | 'image/jpeg' | 'image/webp';
  const presign = await api.collections.presignImage(slug, {
    contentType,
    sizeBytes: file.size,
  });
  await fetch(presign.uploadUrl, {
    method: 'PUT',
    body: file,
    headers: { 'Content-Type': contentType },
  });
  return presign.publicUrl;
}

export default function NewCollectionPage() {
  const router = useRouter();
  const { data: session, isPending } = useSession();
  const [slug, setSlug] = useState('');
  const [name, setName] = useState('');
  const [summary, setSummary] = useState('');
  const [description, setDescription] = useState('');
  const [isPublic, setIsPublic] = useState(true);
  const [iconFile, setIconFile] = useState<File | null>(null);
  const [iconPreview, setIconPreview] = useState<string | null>(null);
  const [iconUploading, setIconUploading] = useState(false);
  const [screenshots, setScreenshots] = useState<{ file: File; preview: string; caption: string }[]>([]);

  const create = useMutation({
    mutationFn: async () => {
      const result = await api.collections.create({
        slug,
        name,
        summary: summary.trim() || null,
        description: description || undefined,
        isPublic,
      });
      const collection = (result as { collection: { slug: string } }).collection;
      let imageUrl: string | null = null;

      if (iconFile) {
        setIconUploading(true);
        try {
          imageUrl = await uploadImage(iconFile, slug);
          await api.collections.patch(slug, { imageUrl });
        } finally {
          setIconUploading(false);
        }
      }

      if (screenshots.length > 0) {
        const shots: { url: string; caption?: string }[] = [];
        for (const s of screenshots) {
          const url = await uploadImage(s.file, slug);
          shots.push({ url, caption: s.caption || undefined });
        }
        await api.collections.patch(slug, { screenshots: shots });
      }

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
        className="space-y-6"
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

        <div className="space-y-1.5">
          <span className="block text-sm font-medium">Icon / Cover image</span>
          {iconPreview ? (
            <div className="relative inline-block">
              <img
                src={iconPreview}
                alt="Icon preview"
                className="h-32 w-32 rounded-md object-cover"
              />
              <button
                type="button"
                onClick={() => { setIconFile(null); setIconPreview(null); }}
                className="absolute -right-2 -top-2 rounded-full bg-background border p-1"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ) : null}
          <label className="flex cursor-pointer items-center gap-2 rounded-md border border-input px-3 py-2 text-sm hover:bg-accent">
            <Upload className="h-4 w-4" />
            <span>{iconPreview ? 'Replace' : 'Upload icon'}</span>
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) {
                  setIconFile(f);
                  setIconPreview(URL.createObjectURL(f));
                }
              }}
            />
          </label>
        </div>

        <div className="space-y-1.5">
          <span className="block text-sm font-medium">Screenshots (gallery)</span>
          <div className="grid grid-cols-3 gap-3">
            {screenshots.map((s, i) => (
              <div key={s.preview} className="relative">
                <img
                  src={s.preview}
                  alt={`Screenshot ${i + 1}`}
                  className="aspect-video w-full rounded-md object-cover"
                />
                <button
                  type="button"
                  onClick={() => setScreenshots((prev) => prev.filter((_, j) => j !== i))}
                  className="absolute -right-2 -top-2 rounded-full bg-background border p-1"
                >
                  <X className="h-3 w-3" />
                </button>
                <input
                  value={s.caption}
                  onChange={(e) =>
                    setScreenshots((prev) =>
                      prev.map((x, j) => (j === i ? { ...x, caption: e.target.value } : x)),
                    )
                  }
                  placeholder="Caption"
                  className="mt-1 w-full rounded border border-input bg-background px-1.5 py-0.5 text-xs"
                />
              </div>
            ))}
            {screenshots.length < 12 ? (
              <label className="flex aspect-video cursor-pointer items-center justify-center rounded-md border border-dashed border-input text-muted-foreground hover:bg-accent">
                <ImageIcon className="h-5 w-5" />
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) {
                      setScreenshots((prev) => [
                        ...prev,
                        { file: f, preview: URL.createObjectURL(f), caption: '' },
                      ]);
                    }
                  }}
                />
              </label>
            ) : null}
          </div>
          <p className="text-xs text-muted-foreground">Up to 12 images.</p>
        </div>

        <div className="space-y-1.5">
          <span className="block text-sm font-medium">
            Description <span className="text-muted-foreground">(Markdown)</span>
          </span>
          <div data-color-mode="light">
            <MDEditor
              value={description}
              onChange={(v) => setDescription(v ?? '')}
              preview="edit"
              height={300}
            />
          </div>
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
          <p className="text-sm text-destructive">{describeApiError(create.error)}</p>
        ) : null}

        <Button type="submit" disabled={create.isPending || iconUploading || !slug || !name}>
          {create.isPending || iconUploading ? (
            <>
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />{' '}
              {iconUploading ? 'Uploading images…' : 'Creating…'}
            </>
          ) : (
            'Create collection'
          )}
        </Button>
      </form>
    </main>
  );
}
