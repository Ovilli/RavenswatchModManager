'use client';

import { ApiError } from '@rsmm/api-client';
import type { ModCategory } from '@rsmm/schemas';
import { Badge, Button, Input, Spinner } from '@rsmm/ui';

function Label({
  htmlFor,
  className = '',
  children,
}: {
  htmlFor?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <label
      htmlFor={htmlFor}
      className={`text-sm font-medium leading-none ${className}`.trim()}
    >
      {children}
    </label>
  );
}
import { AlertTriangle, ImageIcon, Loader2, Package, Upload } from 'lucide-react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../../lib/api';
import { useSession } from '../../lib/auth-client';

// react-md-editor pulls in `navigator` at module top-level; load it on
// the client only. The non-SSR import keeps the page renderable.
const MDEditor = dynamic(() => import('@uiw/react-md-editor'), { ssr: false });

const CATEGORIES: ModCategory[] = [
  'gameplay',
  'balance',
  'cosmetic',
  'qol',
  'audio',
  'difficulty',
  'speedrun',
  'utility',
];

const SLUG_RE = /^[a-z0-9][a-z0-9-_]*$/;
const SEMVER_RE = /^\d+\.\d+\.\d+(?:[-+][\w.]+)?$/;

type Phase =
  | { kind: 'idle' }
  | { kind: 'hashing' }
  | { kind: 'presigning' }
  | { kind: 'uploading-zip' }
  | { kind: 'uploading-image' }
  | { kind: 'patching' }
  | { kind: 'done'; slug: string }
  | { kind: 'error'; message: string; detail?: string };

async function sha256Hex(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  const digest = await crypto.subtle.digest('SHA-256', buf);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MiB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GiB`;
}

export default function PublishPage() {
  const router = useRouter();
  const { data: session, isPending } = useSession();

  const [zip, setZip] = useState<File | null>(null);
  const [image, setImage] = useState<File | null>(null);
  const [slug, setSlug] = useState('');
  const [version, setVersion] = useState('0.1.0');
  const [name, setName] = useState('');
  const [author, setAuthor] = useState('');
  const [summary, setSummary] = useState('');
  const [description, setDescription] = useState<string | undefined>('');
  const [category, setCategory] = useState<ModCategory>('gameplay');
  const [tags, setTags] = useState('');
  const [license, setLicense] = useState('');
  const [repoUrl, setRepoUrl] = useState('');
  const [homepageUrl, setHomepageUrl] = useState('');
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' });

  // Default the author display name to the signed-in user once the
  // session loads, but let the user override if they want a pen name.
  useEffect(() => {
    if (session?.user && !author) setAuthor(session.user.name ?? '');
  }, [session, author]);

  const slugValid = SLUG_RE.test(slug);
  const versionValid = SEMVER_RE.test(version);
  const nameValid = name.trim().length > 0;
  const canSubmit =
    !!zip &&
    slugValid &&
    versionValid &&
    nameValid &&
    phase.kind !== 'hashing' &&
    phase.kind !== 'presigning' &&
    phase.kind !== 'uploading-zip' &&
    phase.kind !== 'uploading-image' &&
    phase.kind !== 'patching';

  const tagList = useMemo(
    () =>
      tags
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean)
        .slice(0, 16),
    [tags],
  );

  async function publish() {
    if (!zip) return;
    try {
      setPhase({ kind: 'hashing' });
      const sha = await sha256Hex(zip);

      setPhase({ kind: 'presigning' });
      const manifest = {
        id: slug,
        name: name.trim(),
        version,
        author: author.trim() || undefined,
        summary: summary.trim() || undefined,
        description: description?.trim() || undefined,
        license: license.trim() || undefined,
        repo_url: repoUrl.trim() || undefined,
        homepage_url: homepageUrl.trim() || undefined,
        tags: tagList.length > 0 ? tagList : undefined,
      };
      const presigned = await api.mods.upload({
        slug,
        version,
        manifest,
        sha256: sha,
        sizeBytes: zip.size,
      });

      setPhase({ kind: 'uploading-zip' });
      const shaBytes = new Uint8Array(sha.length / 2);
      for (let i = 0; i < shaBytes.length; i++) {
        shaBytes[i] = Number.parseInt(sha.slice(i * 2, i * 2 + 2), 16);
      }
      const putRes = await fetch(presigned.uploadUrl, {
        method: 'PUT',
        body: zip,
        headers: {
          'Content-Type': 'application/zip',
          'x-amz-checksum-sha256': btoa(String.fromCharCode(...shaBytes)),
        },
      });
      if (!putRes.ok) {
        const text = await putRes.text().catch(() => '');
        throw new Error(`object storage rejected the upload (${putRes.status}). ${text}`);
      }

      let imageUrl: string | null = null;
      if (image) {
        setPhase({ kind: 'uploading-image' });
        const imgPresigned = await api.mods.presignImage(slug, {
          contentType: image.type as 'image/png' | 'image/jpeg' | 'image/webp',
          sizeBytes: image.size,
        });
        const imgPut = await fetch(imgPresigned.uploadUrl, {
          method: 'PUT',
          body: image,
          headers: { 'Content-Type': image.type },
        });
        if (!imgPut.ok) {
          const text = await imgPut.text().catch(() => '');
          throw new Error(`image upload failed (${imgPut.status}). ${text}`);
        }
        imageUrl = imgPresigned.publicUrl;
      }

      // The /upload route writes manifest-shaped metadata only; category
      // and imageUrl live on the mod row and require a follow-up PATCH.
      if (imageUrl || category) {
        setPhase({ kind: 'patching' });
        await api.mods.patch(slug, {
          category,
          ...(imageUrl ? { imageUrl } : {}),
        });
      }

      setPhase({ kind: 'done', slug });
      // Give the user a beat to see the success state, then ship them
      // to their new mod's public page.
      setTimeout(() => router.push(`/registry/${slug}`), 1200);
    } catch (err) {
      let message = 'publish failed';
      let detail: string | undefined;
      if (err instanceof ApiError) {
        const body = err.body as { error?: string } | null;
        detail = body?.error;
        if (err.status === 401) message = 'You need to sign in before publishing.';
        else if (err.status === 403) message = 'That slug is owned by another account.';
        else if (err.status === 409) message = 'A version with that number already exists.';
        else if (err.status === 413) message = 'Mod exceeds the 500 MB upload limit.';
        else if (err.status === 503)
          message = 'Object storage is not configured on the server.';
        else message = detail ?? `Server returned HTTP ${err.status}.`;
      } else if (err instanceof Error) {
        message = err.message;
      }
      setPhase({ kind: 'error', message, detail });
    }
  }

  if (isPending) {
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
          <h1 className="text-3xl font-bold tracking-tight">Sign in to publish</h1>
          <p className="mt-3 text-sm text-muted-foreground">
            Publishing a mod requires an account so you can manage it later.
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
    <main className="container mx-auto max-w-3xl px-6 py-12">
      <header className="mb-8">
        <h1 className="text-4xl font-bold tracking-tight">Publish a mod</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Upload a packed mod archive (.zip), describe it, and push it to the registry. You can
          edit metadata and ship new versions later from <em>My Mods</em>.
        </p>
      </header>

      {phase.kind === 'error' ? (
        <div className="mb-6 rounded-md border border-destructive/50 bg-destructive/10 p-4">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 text-destructive" />
            <div className="space-y-1">
              <p className="text-sm font-medium text-destructive">{phase.message}</p>
              {phase.detail ? (
                <p className="text-xs text-muted-foreground">{phase.detail}</p>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {phase.kind === 'done' ? (
        <div className="mb-6 rounded-md border border-emerald-500/40 bg-emerald-500/10 p-4">
          <p className="text-sm">
            Published <span className="font-mono">{phase.slug}</span>. Redirecting…
          </p>
        </div>
      ) : null}

      <div className="space-y-8">
        {/* ─── Files ─── */}
        <section className="grimoire-card space-y-4 p-5">
          <div>
            <h2 className="text-lg font-semibold">Files</h2>
            <p className="text-xs text-muted-foreground">
              Pack your mod with the RSMM CLI (<code>rsmm pack &lt;mod&gt;</code>) and upload the
              resulting <code>.zip</code>. Cover image is optional.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="zip" className="flex items-center gap-2">
              <Package className="h-4 w-4" /> Mod archive (.zip)
            </Label>
            <input
              id="zip"
              type="file"
              accept=".zip,application/zip"
              onChange={(e) => setZip(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-muted-foreground file:mr-4 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-2 file:text-sm file:font-medium file:text-primary-foreground hover:file:bg-primary/90"
            />
            {zip ? (
              <p className="text-xs text-muted-foreground">
                {zip.name} — {fmtBytes(zip.size)}
              </p>
            ) : null}
          </div>
          <div className="space-y-2">
            <Label htmlFor="image" className="flex items-center gap-2">
              <ImageIcon className="h-4 w-4" /> Cover image (optional)
            </Label>
            <input
              id="image"
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={(e) => setImage(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-muted-foreground file:mr-4 file:rounded-md file:border-0 file:bg-secondary file:px-3 file:py-2 file:text-sm file:font-medium hover:file:bg-secondary/80"
            />
            {image ? (
              <p className="text-xs text-muted-foreground">
                {image.name} — {fmtBytes(image.size)}
              </p>
            ) : null}
          </div>
        </section>

        {/* ─── Identity ─── */}
        <section className="grimoire-card space-y-4 p-5">
          <h2 className="text-lg font-semibold">Identity</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="slug">Slug</Label>
              <Input
                id="slug"
                value={slug}
                onChange={(e) => setSlug(e.target.value.toLowerCase())}
                placeholder="my-cool-mod"
                aria-invalid={slug.length > 0 && !slugValid ? true : undefined}
              />
              <p className="text-xs text-muted-foreground">
                Lowercase, letters/digits/<code>-_</code>. Cannot change later.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="version">Version</Label>
              <Input
                id="version"
                value={version}
                onChange={(e) => setVersion(e.target.value)}
                placeholder="0.1.0"
                aria-invalid={!versionValid ? true : undefined}
              />
              <p className="text-xs text-muted-foreground">Semver (x.y.z).</p>
            </div>
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="name">Display name</Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="My Cool Mod"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="author">Author</Label>
              <Input
                id="author"
                value={author}
                onChange={(e) => setAuthor(e.target.value)}
                placeholder="your handle"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="category">Category</Label>
              <select
                id="category"
                value={category}
                onChange={(e) => setCategory(e.target.value as ModCategory)}
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </section>

        {/* ─── Description ─── */}
        <section className="grimoire-card space-y-4 p-5">
          <h2 className="text-lg font-semibold">Description</h2>
          <div className="space-y-2">
            <Label htmlFor="summary">Summary</Label>
            <Input
              id="summary"
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              placeholder="One-line pitch (shown in browse cards)."
              maxLength={512}
            />
          </div>
          <div className="space-y-2">
            <Label>Long description (Markdown)</Label>
            <div data-color-mode="dark" className="md-editor-themed">
              <MDEditor value={description} onChange={setDescription} height={320} />
            </div>
          </div>
        </section>

        {/* ─── Meta ─── */}
        <section className="grimoire-card space-y-4 p-5">
          <h2 className="text-lg font-semibold">Meta</h2>
          <div className="space-y-2">
            <Label htmlFor="tags">Tags (comma-separated, max 16)</Label>
            <Input
              id="tags"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="cosmetic, visual, hud"
            />
            {tagList.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {tagList.map((t) => (
                  <Badge key={t} variant="outline">
                    {t}
                  </Badge>
                ))}
              </div>
            ) : null}
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="license">License</Label>
              <Input
                id="license"
                value={license}
                onChange={(e) => setLicense(e.target.value)}
                placeholder="MIT"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="repo">Repository URL</Label>
              <Input
                id="repo"
                type="url"
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                placeholder="https://github.com/you/mod"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="home">Homepage URL</Label>
              <Input
                id="home"
                type="url"
                value={homepageUrl}
                onChange={(e) => setHomepageUrl(e.target.value)}
                placeholder="https://example.com"
              />
            </div>
          </div>
        </section>

        <div className="flex items-center justify-between gap-3">
          <Link
            href="/registry"
            className="text-sm text-muted-foreground underline-offset-2 hover:underline"
          >
            Cancel
          </Link>
          <Button onClick={publish} disabled={!canSubmit} size="lg">
            {phase.kind === 'hashing' ? (
              <>
                <Spinner /> Hashing
              </>
            ) : phase.kind === 'presigning' ? (
              <>
                <Spinner /> Presigning
              </>
            ) : phase.kind === 'uploading-zip' ? (
              <>
                <Spinner /> Uploading zip
              </>
            ) : phase.kind === 'uploading-image' ? (
              <>
                <Spinner /> Uploading image
              </>
            ) : phase.kind === 'patching' ? (
              <>
                <Spinner /> Saving
              </>
            ) : (
              <>
                <Upload className="h-4 w-4" /> Publish
              </>
            )}
          </Button>
        </div>
      </div>
    </main>
  );
}
