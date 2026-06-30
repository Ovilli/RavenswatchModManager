'use client';
import { ApiError, isRateLimited } from '@rsmm/api-client';
import { Button, Input, Spinner, buttonVariants } from '@rsmm/ui';
import { useMutation } from '@tanstack/react-query';
import { ArrowLeft, ImagePlus, Loader2, Upload, X } from 'lucide-react';
import type { Route } from 'next';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { api } from '../../../lib/api';
import { useSession } from '../../../lib/auth-client';

const MDEditor = dynamic(() => import('@uiw/react-md-editor'), { ssr: false });

function describeApiError(err: unknown): string {
  if (isRateLimited(err)) return `Rate limited — try again in ${err.retryAfter}s.`;
  if (err instanceof ApiError) {
    const body = err.body as { error?: string } | null;
    if (body?.error) return body.error;
    return `HTTP ${err.status}`;
  }
  return err instanceof Error ? err.message : String(err);
}

async function uploadImage(file: File, slug: string): Promise<string> {
  const contentType = file.type as 'image/png' | 'image/jpeg' | 'image/webp';
  const presign = await api.guides.presignImage(slug, { contentType, sizeBytes: file.size });
  await fetch(presign.uploadUrl, {
    method: 'PUT',
    body: file,
    headers: { 'Content-Type': contentType },
  });
  return presign.publicUrl;
}

export default function NewGuidePage() {
  const router = useRouter();
  const { data: session, isPending } = useSession();
  const [slug, setSlug] = useState('');
  const [title, setTitle] = useState('');
  const [summary, setSummary] = useState('');
  const [body, setBody] = useState('');
  const [coverFile, setCoverFile] = useState<File | null>(null);
  const [coverPreview, setCoverPreview] = useState<string | null>(null);
  const [submitForReview, setSubmitForReview] = useState(true);
  const [inlineUploading, setInlineUploading] = useState(false);

  const create = useMutation({
    mutationFn: async () => {
      // The guide must exist (slug) before we can presign images against it.
      await api.guides.create({ slug, title, summary: summary.trim() || null, body });
      const patch: Record<string, unknown> = {};
      if (coverFile) patch.imageUrl = await uploadImage(coverFile, slug);
      if (submitForReview) patch.status = 'pending';
      if (Object.keys(patch).length > 0) await api.guides.patch(slug, patch);
      router.push(`/guides/${slug}` as Route);
    },
  });

  // Upload an image and append a markdown reference to the body.
  const insertInlineImage = async (file: File) => {
    if (!slug) return;
    setInlineUploading(true);
    try {
      // Ensure the guide exists so the presign has a slug to attach to.
      try {
        await api.guides.create({ slug, title: title || slug, summary: null, body: body || ' ' });
      } catch {
        // already exists — fine, continue to upload.
      }
      const url = await uploadImage(file, slug);
      setBody((b) => `${b}\n\n![](${url})\n`);
    } finally {
      setInlineUploading(false);
    }
  };

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
          to write a guide.
        </p>
      </main>
    );
  }

  return (
    <main className="container mx-auto max-w-2xl space-y-6 px-6 py-12">
      <Link href={'/guides' as Route} className={buttonVariants({ variant: 'outline', size: 'sm' })}>
        <ArrowLeft className="mr-1.5 h-4 w-4" /> Back to Guides
      </Link>
      <h1 className="text-3xl font-bold tracking-tight">Write a guide</h1>
      <p className="text-sm text-muted-foreground">
        Guides are reviewed by a maintainer before they go public. Save a draft anytime.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
        className="space-y-6"
      >
        <div className="space-y-1.5">
          <label htmlFor="g-slug" className="block text-sm font-medium">
            Slug (URL)
          </label>
          <Input
            id="g-slug"
            value={slug}
            onChange={(e) => setSlug(e.target.value.toLowerCase())}
            placeholder="beginners-guide-to-modding"
            pattern="[a-z0-9][a-z0-9_-]{1,79}"
            required
          />
          <p className="text-xs text-muted-foreground">
            Lowercase letters, numbers, dashes/underscores.
          </p>
        </div>

        <div className="space-y-1.5">
          <label htmlFor="g-title" className="block text-sm font-medium">
            Title
          </label>
          <Input
            id="g-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="A beginner's guide to modding Ravenswatch"
            required
            maxLength={160}
          />
        </div>

        <div className="space-y-1.5">
          <label htmlFor="g-summary" className="block text-sm font-medium">
            Summary <span className="text-muted-foreground">(shown in listings + previews)</span>
          </label>
          <textarea
            id="g-summary"
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            placeholder="One or two sentences describing the guide."
            maxLength={512}
            rows={2}
            className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        </div>

        <div className="space-y-1.5">
          <span className="block text-sm font-medium">Cover image</span>
          {coverPreview ? (
            <div className="relative inline-block">
              <img
                src={coverPreview}
                alt="Cover preview"
                className="h-32 w-56 rounded-md object-cover"
              />
              <button
                type="button"
                onClick={() => {
                  setCoverFile(null);
                  setCoverPreview(null);
                }}
                className="absolute -right-2 -top-2 rounded-full border bg-background p-1"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ) : null}
          <label className="flex w-fit cursor-pointer items-center gap-2 rounded-md border border-input px-3 py-2 text-sm hover:bg-accent">
            <Upload className="h-4 w-4" />
            <span>{coverPreview ? 'Replace' : 'Upload cover'}</span>
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) {
                  setCoverFile(f);
                  setCoverPreview(URL.createObjectURL(f));
                }
              }}
            />
          </label>
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="block text-sm font-medium">
              Body <span className="text-muted-foreground">(Markdown)</span>
            </span>
            <label
              className={`flex cursor-pointer items-center gap-1.5 text-xs ${slug ? 'text-foreground hover:text-gilt' : 'pointer-events-none text-muted-foreground'}`}
            >
              {inlineUploading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <ImagePlus className="h-3.5 w-3.5" />
              )}
              Insert image
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="hidden"
                disabled={!slug || inlineUploading}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) insertInlineImage(f);
                }}
              />
            </label>
          </div>
          <div data-color-mode="dark" className="md-editor-themed">
            <MDEditor value={body} onChange={(v) => setBody(v ?? '')} height={420} />
          </div>
          {!slug ? (
            <p className="text-xs text-muted-foreground">Set a slug first to insert images.</p>
          ) : null}
        </div>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={submitForReview}
            onChange={(e) => setSubmitForReview(e.target.checked)}
          />
          <span>Submit for review now (otherwise saved as a private draft)</span>
        </label>

        {create.isError ? (
          <p className="text-sm text-destructive">{describeApiError(create.error)}</p>
        ) : null}

        <Button type="submit" disabled={create.isPending || !slug || !title || !body}>
          {create.isPending ? (
            <>
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> Saving…
            </>
          ) : submitForReview ? (
            'Submit for review'
          ) : (
            'Save draft'
          )}
        </Button>
      </form>
    </main>
  );
}
