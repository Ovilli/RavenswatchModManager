'use client';

import { ApiError } from '@rsmm/api-client';
import type { ModCategory } from '@rsmm/schemas';
import { Badge, Button, Input, Spinner } from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Eye,
  ImageIcon,
  Loader2,
  Pencil,
  Save,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import { api } from '../../../lib/api';
import { useSession } from '../../../lib/auth-client';
import { toEmbedUrl } from '../../../lib/video-embed';

const MDEditor = dynamic(() => import('@uiw/react-md-editor'), { ssr: false });
const MDPreview = dynamic(
  () => import('@uiw/react-md-editor').then((m) => m.default.Markdown),
  { ssr: false },
);

interface Screenshot {
  url: string;
  caption?: string;
}

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

const SEMVER_RE = /^\d+\.\d+\.\d+(?:[-+][\w.]+)?$/;

function Label({
  htmlFor,
  children,
}: {
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <label htmlFor={htmlFor} className="text-sm font-medium leading-none">
      {children}
    </label>
  );
}

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

function describeApiError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { error?: string } | null;
    if (body?.error) return body.error;
    return `HTTP ${err.status}`;
  }
  return err instanceof Error ? err.message : String(err);
}

export default function ManageModPage() {
  const router = useRouter();
  const params = useParams<{ slug: string }>();
  const slug = params.slug;
  const qc = useQueryClient();
  const { data: session, isPending: sessionLoading } = useSession();

  const detail = useQuery({
    queryKey: ['my-mod', slug],
    queryFn: () => api.mods.get(slug),
    enabled: !!slug,
  });

  // Form state for metadata edit
  const [name, setName] = useState('');
  const [summary, setSummary] = useState('');
  const [description, setDescription] = useState<string | undefined>('');
  const [category, setCategory] = useState<ModCategory>('gameplay');
  const [tags, setTags] = useState('');
  const [license, setLicense] = useState('');
  const [repoUrl, setRepoUrl] = useState('');
  const [homepageUrl, setHomepageUrl] = useState('');
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [nsfw, setNsfw] = useState(false);
  const [screenshots, setScreenshots] = useState<Screenshot[]>([]);
  const [videos, setVideos] = useState<string[]>([]);
  const [videoInput, setVideoInput] = useState('');
  const [lightboxIdx, setLightboxIdx] = useState<number | null>(null);
  const [previewMode, setPreviewMode] = useState(false);

  // Hydrate the form whenever the underlying detail row changes — this
  // also covers the post-mutation refetch so the inputs reflect what
  // the server actually persisted.
  useEffect(() => {
    const mod = detail.data?.mod;
    if (!mod) return;
    setName(mod.name);
    setSummary(mod.summary ?? '');
    // The detail endpoint returns ModListItem-shaped data, which does
    // not include the long markdown description. Fetch it lazily from
    // the latest version's manifest as a sensible default.
    const latestDesc =
      typeof detail.data?.versions[0]?.manifestJson === 'object'
        ? ((detail.data.versions[0].manifestJson as { description?: string })?.description ?? '')
        : '';
    setDescription(latestDesc);
    setCategory((mod.category as ModCategory) ?? 'gameplay');
    setTags(mod.tags.join(', '));
    setLicense(mod.license ?? '');
    setNsfw(mod.nsfw ?? false);
    // repoUrl / homepageUrl are not on ModListItem; leave blank and
    // let the user fill them on first save.
    setRepoUrl('');
    setHomepageUrl('');
    setScreenshots(mod.screenshots ?? []);
    setVideos(mod.videos ?? []);
  }, [detail.data]);

  const saveMeta = useMutation({
    mutationFn: async () => {
      const tagList = tags
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean)
        .slice(0, 16);
      await api.mods.patch(slug, {
        name: name.trim() || undefined,
        summary: summary.trim() || null,
        description: description?.trim() || null,
        category,
        tags: tagList,
        license: license.trim() || null,
        repoUrl: repoUrl.trim() || null,
        homepageUrl: homepageUrl.trim() || null,
        screenshots,
        videos,
        nsfw,
      });
    },
    onSuccess: () => {
      setSaveMessage('Saved.');
      qc.invalidateQueries({ queryKey: ['my-mod', slug] });
      qc.invalidateQueries({ queryKey: ['me', 'mods'] });
    },
  });

  const [coverFile, setCoverFile] = useState<File | null>(null);
  const uploadCover = useMutation({
    mutationFn: async () => {
      if (!coverFile) throw new Error('no file picked');
      const presigned = await api.mods.presignImage(slug, {
        contentType: coverFile.type as 'image/png' | 'image/jpeg' | 'image/webp',
        sizeBytes: coverFile.size,
      });
      const put = await fetch(presigned.uploadUrl, {
        method: 'PUT',
        body: coverFile,
        headers: { 'Content-Type': coverFile.type },
      });
      if (!put.ok) throw new Error(`image upload failed (${put.status})`);
      await api.mods.patch(slug, { imageUrl: presigned.publicUrl });
    },
    onSuccess: () => {
      setCoverFile(null);
      qc.invalidateQueries({ queryKey: ['my-mod', slug] });
      qc.invalidateQueries({ queryKey: ['me', 'mods'] });
    },
  });

  const uploadScreenshot = useMutation({
    mutationFn: async (file: File) => {
      const presigned = await api.mods.presignImage(slug, {
        contentType: file.type as 'image/png' | 'image/jpeg' | 'image/webp',
        sizeBytes: file.size,
      });
      const put = await fetch(presigned.uploadUrl, {
        method: 'PUT',
        body: file,
        headers: { 'Content-Type': file.type },
      });
      if (!put.ok) throw new Error(`upload failed (${put.status})`);
      const next: Screenshot[] = [...screenshots, { url: presigned.publicUrl }].slice(0, 12);
      setScreenshots(next);
      await api.mods.patch(slug, { screenshots: next });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['my-mod', slug] });
    },
  });

  function removeScreenshot(idx: number) {
    const next = screenshots.filter((_, i) => i !== idx);
    setScreenshots(next);
    api.mods.patch(slug, { screenshots: next }).catch((err) => {
      console.error('screenshot remove failed', err);
    });
  }

  // Debounced caption save — typing on every keystroke would hammer
  // the API and race the user. Save on blur instead, plus a fallback
  // commit if the user re-orders or removes anything.
  function setCaption(idx: number, caption: string) {
    setScreenshots((prev) => {
      const next = prev.map((s, i) => (i === idx ? { ...s, caption } : s));
      return next;
    });
  }
  function commitCaption(idx: number) {
    const next = screenshots.map((s, i) =>
      i === idx ? { url: s.url, caption: s.caption?.trim() || undefined } : s,
    );
    setScreenshots(next);
    api.mods.patch(slug, { screenshots: next }).catch((err) => {
      console.error('caption save failed', err);
    });
  }

  function addVideo() {
    const trimmed = videoInput.trim();
    if (!trimmed) return;
    if (videos.length >= 8) return;
    const next = [...videos, trimmed];
    setVideos(next);
    setVideoInput('');
    api.mods.patch(slug, { videos: next }).catch((err) => {
      console.error('video add failed', err);
    });
  }

  function removeVideo(idx: number) {
    const next = videos.filter((_, i) => i !== idx);
    setVideos(next);
    api.mods.patch(slug, { videos: next }).catch((err) => {
      console.error('video remove failed', err);
    });
  }

  // Lightbox keyboard nav — Esc closes, ←/→ paginate. Wired via
  // useEffect so we don't leak listeners between mods.
  const closeLightbox = useCallback(() => setLightboxIdx(null), []);
  const prevImage = useCallback(() => {
    setLightboxIdx((i) => {
      if (i == null || screenshots.length === 0) return i;
      return (i - 1 + screenshots.length) % screenshots.length;
    });
  }, [screenshots.length]);
  const nextImage = useCallback(() => {
    setLightboxIdx((i) => {
      if (i == null || screenshots.length === 0) return i;
      return (i + 1) % screenshots.length;
    });
  }, [screenshots.length]);
  useEffect(() => {
    if (lightboxIdx == null) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') closeLightbox();
      else if (e.key === 'ArrowLeft') prevImage();
      else if (e.key === 'ArrowRight') nextImage();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [lightboxIdx, closeLightbox, prevImage, nextImage]);

  // New version section
  const [newVersion, setNewVersion] = useState('');
  const [newZip, setNewZip] = useState<File | null>(null);
  const [changelog, setChangelog] = useState<string | undefined>('');
  const newVersionMut = useMutation({
    mutationFn: async () => {
      if (!newZip) throw new Error('no zip selected');
      if (!SEMVER_RE.test(newVersion)) throw new Error('version must be semver x.y.z');
      const sha = await sha256Hex(newZip);
      const mod = detail.data?.mod;
      if (!mod) throw new Error('mod not loaded');
      const manifest = {
        id: slug,
        name: mod.name,
        version: newVersion,
        author: mod.author ?? undefined,
        summary: mod.summary ?? undefined,
        description: description?.trim() || undefined,
        license: mod.license ?? undefined,
        tags: mod.tags,
      };
      const presigned = await api.mods.createVersion(slug, {
        version: newVersion,
        sha256: sha,
        sizeBytes: newZip.size,
        manifest,
        changelog: changelog?.trim() || undefined,
      });
      const shaBytes = new Uint8Array(sha.length / 2);
      for (let i = 0; i < shaBytes.length; i++) {
        shaBytes[i] = Number.parseInt(sha.slice(i * 2, i * 2 + 2), 16);
      }
      const put = await fetch(presigned.uploadUrl, {
        method: 'PUT',
        body: newZip,
        headers: {
          'Content-Type': 'application/zip',
          'x-amz-checksum-sha256': btoa(String.fromCharCode(...shaBytes)),
        },
      });
      if (!put.ok) {
        const text = await put.text().catch(() => '');
        throw new Error(`object storage rejected the upload (${put.status}). ${text}`);
      }
    },
    onSuccess: () => {
      setNewZip(null);
      setNewVersion('');
      setChangelog('');
      qc.invalidateQueries({ queryKey: ['my-mod', slug] });
    },
  });

  const remove = useMutation({
    mutationFn: () => api.mods.remove(slug),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['me', 'mods'] });
      router.push('/my-mods');
    },
  });

  if (sessionLoading || detail.isLoading) {
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

  if (detail.isError || !detail.data) {
    return (
      <main className="container mx-auto px-6 py-16">
        <p className="text-sm text-destructive">
          Cannot load mod {slug} ({String(detail.error)})
        </p>
      </main>
    );
  }

  const mod = detail.data.mod;
  const versions = detail.data.versions;

  if (previewMode) {
    return (
      <main className="container mx-auto max-w-3xl space-y-8 px-6 py-12">
        <PreviewHeader
          modName={mod.name}
          slug={mod.slug}
          onExit={() => setPreviewMode(false)}
        />
        <PreviewBody
          mod={{
            name: name || mod.name,
            summary: summary || mod.summary || '',
            author: mod.author,
            latestVersion: mod.latestVersion,
            updatedAt: mod.updatedAt,
            category,
            tags: tags
              .split(',')
              .map((t) => t.trim())
              .filter(Boolean),
            license: license || mod.license,
            imageUrl: mod.imageUrl,
            downloads: mod.downloads,
          }}
          description={description}
          screenshots={screenshots}
          videos={videos}
          onLightbox={(i) => setLightboxIdx(i)}
        />
        {lightboxIdx != null && screenshots[lightboxIdx] ? (
          <Lightbox
            shot={screenshots[lightboxIdx]}
            index={lightboxIdx}
            total={screenshots.length}
            onClose={closeLightbox}
            onPrev={prevImage}
            onNext={nextImage}
          />
        ) : null}
      </main>
    );
  }

  return (
    <main className="container mx-auto max-w-3xl space-y-8 px-6 py-12">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-mono text-xs text-muted-foreground">{mod.slug}</p>
          <h1 className="text-3xl font-bold tracking-tight">{mod.name}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            v{mod.latestVersion ?? '—'} · {mod.downloads.toLocaleString()} downloads ·
            {mod.category ? ` ${mod.category} · ` : ' '}updated {new Date(mod.updatedAt).toLocaleDateString()}
          </p>
          <div className="mt-3 flex gap-2 text-sm">
            <Link
              href={`/registry/${mod.slug}` as never}
              className="underline-offset-2 hover:underline"
            >
              View public page →
            </Link>
          </div>
        </div>
        <Button type="button" variant="outline" onClick={() => setPreviewMode(true)}>
          <Eye className="h-4 w-4" /> Preview
        </Button>
      </header>

      {/* ─── Cover ─── */}
      <section className="grimoire-card space-y-4 p-5">
        <h2 className="text-lg font-semibold">Cover image</h2>
        {mod.imageUrl ? (
          <div className="aspect-[16/9] w-full overflow-hidden rounded-md bg-muted">
            <img
              src={mod.imageUrl}
              alt={`${mod.name} cover`}
              className="h-full w-full object-cover"
            />
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No cover image yet.</p>
        )}
        <div className="space-y-2">
          <Label htmlFor="cover">
            <span className="inline-flex items-center gap-2">
              <ImageIcon className="h-4 w-4" /> Upload new cover (png/jpeg/webp, ≤ 8 MB)
            </span>
          </Label>
          <input
            id="cover"
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={(e) => setCoverFile(e.target.files?.[0] ?? null)}
            className="block w-full text-sm text-muted-foreground file:mr-4 file:rounded-md file:border-0 file:bg-secondary file:px-3 file:py-2 file:text-sm file:font-medium hover:file:bg-secondary/80"
          />
          {coverFile ? (
            <p className="text-xs text-muted-foreground">
              {coverFile.name} — {fmtBytes(coverFile.size)}
            </p>
          ) : null}
          <Button
            onClick={() => uploadCover.mutate()}
            disabled={!coverFile || uploadCover.isPending}
            size="sm"
          >
            {uploadCover.isPending ? <Spinner /> : null} Upload cover
          </Button>
          {uploadCover.isError ? (
            <p className="text-xs text-destructive">{describeApiError(uploadCover.error)}</p>
          ) : null}
        </div>
      </section>

      {/* ─── Metadata edit ─── */}
      <section className="grimoire-card space-y-4 p-5">
        <h2 className="text-lg font-semibold">Metadata</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2 sm:col-span-2">
            <Label htmlFor="name">Display name</Label>
            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-2 sm:col-span-2">
            <Label htmlFor="summary">Summary</Label>
            <Input
              id="summary"
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              maxLength={512}
            />
          </div>
          <div className="space-y-2 sm:col-span-2">
            <Label>Description (Markdown)</Label>
            <div data-color-mode="dark" className="md-editor-themed">
              <MDEditor value={description} onChange={setDescription} height={320} />
            </div>
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
          <div className="space-y-2">
            <Label htmlFor="license">License</Label>
            <Input id="license" value={license} onChange={(e) => setLicense(e.target.value)} />
          </div>
          <div className="space-y-2 sm:col-span-2">
            <Label htmlFor="tags">Tags (comma-separated)</Label>
            <Input id="tags" value={tags} onChange={(e) => setTags(e.target.value)} />
          </div>
          <div className="space-y-2 sm:col-span-2">
            <label className="flex cursor-pointer items-center gap-3 text-sm">
              <input
                type="checkbox"
                checked={nsfw}
                onChange={(e) => setNsfw(e.target.checked)}
                className="h-4 w-4 rounded border-border accent-crimson"
              />
              <span className="text-sm font-medium leading-none">
                <strong>NSFW / mature content</strong>
              </span>
            </label>
            <p className="text-xs text-muted-foreground">
              If checked, the mod will be hidden behind a blur by default.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="repo">Repository URL</Label>
            <Input
              id="repo"
              type="url"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="home">Homepage URL</Label>
            <Input
              id="home"
              type="url"
              value={homepageUrl}
              onChange={(e) => setHomepageUrl(e.target.value)}
            />
          </div>
        </div>
        <div className="flex items-center justify-end gap-3">
          {saveMessage ? <span className="text-xs text-muted-foreground">{saveMessage}</span> : null}
          {saveMeta.isError ? (
            <span className="text-xs text-destructive">{describeApiError(saveMeta.error)}</span>
          ) : null}
          <Button onClick={() => saveMeta.mutate()} disabled={saveMeta.isPending}>
            {saveMeta.isPending ? <Spinner /> : <Save className="h-4 w-4" />} Save metadata
          </Button>
        </div>
      </section>

      {/* ─── Gallery ─── */}
      <section className="grimoire-card space-y-4 p-5">
        <div>
          <h2 className="text-lg font-semibold">Gallery</h2>
          <p className="text-xs text-muted-foreground">
            Up to 12 screenshots and 8 YouTube/Vimeo links.
          </p>
        </div>

        {/* Screenshots */}
        <div className="space-y-2">
          <Label>Screenshots</Label>
          {screenshots.length > 0 ? (
            <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {screenshots.map((shot, idx) => (
                <li
                  key={shot.url}
                  className="space-y-2 rounded-md border border-border/40 p-2"
                >
                  <button
                    type="button"
                    onClick={() => setLightboxIdx(idx)}
                    className="group relative block aspect-video w-full overflow-hidden rounded bg-muted"
                  >
                    <img
                      src={shot.url}
                      alt={shot.caption || `Screenshot ${idx + 1}`}
                      className="h-full w-full object-cover transition-opacity group-hover:opacity-90"
                    />
                    <span className="absolute bottom-1 left-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-white">
                      click to preview
                    </span>
                  </button>
                  <Input
                    value={shot.caption ?? ''}
                    onChange={(e) =>
                      setCaption(idx, (e.target as HTMLInputElement).value)
                    }
                    onBlur={() => commitCaption(idx)}
                    placeholder="Caption (optional, max 200 chars)"
                    maxLength={200}
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => removeScreenshot(idx)}
                  >
                    <Trash2 className="h-3.5 w-3.5" /> Remove
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">No screenshots yet.</p>
          )}
          {screenshots.length < 12 ? (
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) uploadScreenshot.mutate(f);
                e.target.value = '';
              }}
              disabled={uploadScreenshot.isPending}
              className="block w-full text-sm text-muted-foreground file:mr-4 file:rounded-md file:border-0 file:bg-secondary file:px-3 file:py-2 file:text-sm file:font-medium hover:file:bg-secondary/80"
            />
          ) : null}
          {uploadScreenshot.isPending ? (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Spinner /> Uploading…
            </p>
          ) : null}
          {uploadScreenshot.isError ? (
            <p className="text-xs text-destructive">{describeApiError(uploadScreenshot.error)}</p>
          ) : null}
        </div>

        {/* Videos */}
        <div className="space-y-2">
          <Label>Videos (YouTube or Vimeo URLs)</Label>
          {videos.length > 0 ? (
            <ul className="space-y-2">
              {videos.map((url, idx) => (
                <li key={url} className="flex items-center gap-2 rounded-md border border-border/40 px-3 py-2">
                  <span className="flex-1 truncate font-mono text-xs">{url}</span>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => removeVideo(idx)}
                  >
                    remove
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">No videos yet.</p>
          )}
          {videos.length < 8 ? (
            <div className="flex gap-2">
              <Input
                value={videoInput}
                onChange={(e) => setVideoInput((e.target as HTMLInputElement).value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    addVideo();
                  }
                }}
                placeholder="https://www.youtube.com/watch?v=…"
              />
              <Button type="button" onClick={addVideo} disabled={!videoInput.trim()}>
                Add
              </Button>
            </div>
          ) : null}
        </div>
      </section>

      {/* ─── Versions ─── */}
      <section className="grimoire-card space-y-4 p-5">
        <h2 className="text-lg font-semibold">Versions</h2>
        {versions.length === 0 ? (
          <p className="text-sm text-muted-foreground">No versions published yet.</p>
        ) : (
          <ul className="space-y-3">
            {versions
              .slice()
              .sort(
                (a, b) =>
                  new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
              )
              .map((v) => {
                // changelog isn't on the published ModVersion schema yet
                // because the public detail endpoint hasn't been
                // extended — read it from manifestJson as a fallback.
                const cl =
                  typeof v.manifestJson === 'object'
                    ? (v.manifestJson as { changelog?: string })?.changelog
                    : undefined;
                return (
                  <li key={v.id} className="grimoire-card p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div>
                        <p className="font-semibold">v{v.version}</p>
                        <p className="text-xs text-muted-foreground">
                          {fmtBytes(v.sizeBytes)} ·{' '}
                          {new Date(v.createdAt).toLocaleDateString()}
                        </p>
                      </div>
                      <Badge variant="outline">{v.sha256.slice(0, 12)}</Badge>
                    </div>
                    {cl ? (
                      <pre className="mt-2 whitespace-pre-wrap text-xs text-muted-foreground">
                        {cl}
                      </pre>
                    ) : null}
                  </li>
                );
              })}
          </ul>
        )}

        <div className="border-t border-border/40 pt-4">
          <h3 className="text-sm font-semibold">Ship a new version</h3>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="newver">Version</Label>
              <Input
                id="newver"
                value={newVersion}
                onChange={(e) => setNewVersion(e.target.value)}
                placeholder="0.2.0"
                aria-invalid={
                  newVersion.length > 0 && !SEMVER_RE.test(newVersion) ? true : undefined
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="newzip">New zip</Label>
              <input
                id="newzip"
                type="file"
                accept=".zip,application/zip"
                onChange={(e) => setNewZip(e.target.files?.[0] ?? null)}
                className="block w-full text-sm text-muted-foreground file:mr-4 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-2 file:text-sm file:font-medium file:text-primary-foreground hover:file:bg-primary/90"
              />
              {newZip ? (
                <p className="text-xs text-muted-foreground">
                  {newZip.name} — {fmtBytes(newZip.size)}
                </p>
              ) : null}
            </div>
            <div className="space-y-2 sm:col-span-2">
              <Label>Changelog (Markdown)</Label>
              <div data-color-mode="dark" className="md-editor-themed">
                <MDEditor value={changelog} onChange={setChangelog} height={200} />
              </div>
            </div>
          </div>
          <div className="mt-4 flex items-center justify-end gap-3">
            {newVersionMut.isError ? (
              <span className="text-xs text-destructive">
                {describeApiError(newVersionMut.error)}
              </span>
            ) : null}
            <Button
              onClick={() => newVersionMut.mutate()}
              disabled={
                !newZip || !SEMVER_RE.test(newVersion) || newVersionMut.isPending
              }
            >
              {newVersionMut.isPending ? <Spinner /> : <Upload className="h-4 w-4" />} Publish version
            </Button>
          </div>
        </div>
      </section>

      {/* ─── Danger zone ─── */}
      <section className="grimoire-card space-y-3 border-destructive/30 p-5">
        <div className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 h-4 w-4 text-destructive" />
          <div>
            <h2 className="text-lg font-semibold">Danger zone</h2>
            <p className="text-sm text-muted-foreground">
              Deleting removes the mod row and every published version. The slug becomes
              available for someone else to claim. This cannot be undone.
            </p>
          </div>
        </div>
        <Button
          variant="destructive"
          onClick={() => {
            if (
              window.confirm(
                `Delete "${mod.name}" and all its versions? This cannot be undone.`,
              )
            ) {
              remove.mutate();
            }
          }}
          disabled={remove.isPending}
        >
          {remove.isPending ? <Spinner /> : <Trash2 className="h-4 w-4" />} Delete mod
        </Button>
        {remove.isError ? (
          <p className="text-xs text-destructive">{describeApiError(remove.error)}</p>
        ) : null}
      </section>

      {lightboxIdx != null && screenshots[lightboxIdx] ? (
        <Lightbox
          shot={screenshots[lightboxIdx]}
          index={lightboxIdx}
          total={screenshots.length}
          onClose={closeLightbox}
          onPrev={prevImage}
          onNext={nextImage}
        />
      ) : null}
    </main>
  );
}

function Lightbox({
  shot,
  index,
  total,
  onClose,
  onPrev,
  onNext,
}: {
  shot: Screenshot;
  index: number;
  total: number;
  onClose: () => void;
  onPrev: () => void;
  onNext: () => void;
}) {
  return (
    <dialog
      open
      aria-label={shot.caption || `Screenshot ${index + 1}`}
      className="fixed inset-0 z-[90] bg-pitch/95 animate-fade-in"
    >
      <div className="absolute inset-0 overflow-y-auto">
        <button
          type="button"
          onClick={onClose}
          className="absolute inset-0 h-full w-full cursor-default"
          aria-label="Close preview"
        />
        <div className="pointer-events-none relative flex min-h-full items-center justify-center px-4 py-16 sm:px-20">
          <figure
            onClick={(e) => e.stopPropagation()}
            className="pointer-events-auto flex w-full max-w-6xl flex-col items-center gap-4"
          >
            <img
              src={shot.url}
              alt={shot.caption || `Screenshot ${index + 1}`}
              className="max-w-full rounded-md object-contain shadow-2xl"
            />
            <figcaption className="max-w-3xl text-center text-sm text-muted-foreground">
              {shot.caption || `Screenshot ${index + 1} of ${total}`}
            </figcaption>
            <p className="font-mono text-xs text-muted-foreground/70">
              {index + 1} / {total}
            </p>
          </figure>
        </div>
      </div>
      <button
        type="button"
        onClick={onClose}
        className="fixed right-4 top-4 z-20 rounded-md bg-background/80 p-2 text-foreground hover:bg-background"
        aria-label="Close"
      >
        <X className="h-5 w-5" />
      </button>
      {total > 1 ? (
        <button
          type="button"
          onClick={onPrev}
          className="fixed left-2 sm:left-4 top-1/2 z-20 -translate-y-1/2 rounded-md bg-background/80 p-3 text-foreground hover:bg-background"
          aria-label="Previous"
        >
          <ChevronLeft className="h-6 w-6" />
        </button>
      ) : null}
      {total > 1 ? (
        <button
          type="button"
          onClick={onNext}
          className="fixed right-2 sm:right-4 top-1/2 z-20 -translate-y-1/2 rounded-md bg-background/80 p-3 text-foreground hover:bg-background"
          aria-label="Next"
        >
          <ChevronRight className="h-6 w-6" />
        </button>
      ) : null}
    </dialog>
  );
}

function PreviewHeader({
  modName,
  slug,
  onExit,
}: {
  modName: string;
  slug: string;
  onExit: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-gilt/40 bg-gilt/5 px-4 py-2 text-sm">
      <div>
        <span className="font-semibold text-foreground">Preview</span>
        <span className="ml-2 font-mono text-muted-foreground">{slug}</span>
        <span className="ml-2 text-muted-foreground">— {modName}</span>
      </div>
      <Button type="button" size="sm" variant="outline" onClick={onExit}>
        <Pencil className="h-4 w-4" /> Back to edit
      </Button>
    </div>
  );
}

function PreviewBody({
  mod,
  description,
  screenshots,
  videos,
  onLightbox,
}: {
  mod: {
    name: string;
    summary: string;
    author: string | null;
    latestVersion: string | null;
    updatedAt: string;
    category: string | null;
    tags: string[];
    license: string | null;
    imageUrl: string | null;
    downloads: number;
  };
  description: string | undefined;
  screenshots: Screenshot[];
  videos: string[];
  onLightbox: (idx: number) => void;
}) {
  return (
    <div className="space-y-6">
      {mod.imageUrl ? (
        <div className="aspect-[21/9] w-full overflow-hidden rounded-xl border border-border/50 bg-muted">
          <img src={mod.imageUrl} alt={`${mod.name} cover`} className="h-full w-full object-cover" />
        </div>
      ) : null}
      <header>
        <h1 className="text-4xl font-bold tracking-tight">{mod.name}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {mod.author ?? 'unknown'}
          {mod.latestVersion ? ` · v${mod.latestVersion}` : ''}
          {` · updated ${new Date(mod.updatedAt).toLocaleDateString()}`}
        </p>
      </header>
      {mod.summary ? (
        <p className="max-w-3xl text-lg text-muted-foreground">{mod.summary}</p>
      ) : null}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        <div className="space-y-4 md:col-span-2">
          {description?.trim() ? (
            <div className="grimoire-card space-y-3 p-6">
              <h2 className="text-xl font-bold tracking-tight">About</h2>
              <div data-color-mode="dark" className="prose prose-sm prose-invert max-w-none">
                <MDPreview source={description} style={{ background: 'transparent' }} />
              </div>
            </div>
          ) : null}
          {(screenshots.length > 0 || videos.length > 0) ? (
            <div className="grimoire-card space-y-4 p-6">
              <h2 className="text-xl font-bold tracking-tight">Gallery</h2>
              {videos.length > 0 ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  {videos.map((url) => {
                    const embed = toEmbedUrl(url);
                    return (
                      <div key={url} className="aspect-video overflow-hidden rounded-md bg-muted">
                        {embed ? (
                          <iframe
                            src={embed}
                            title="Video preview"
                            loading="lazy"
                            allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                            allowFullScreen
                            className="h-full w-full"
                          />
                        ) : (
                          <a
                            href={url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex h-full w-full items-center justify-center text-sm underline"
                          >
                            {url}
                          </a>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : null}
              {screenshots.length > 0 ? (
                <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  {screenshots.map((shot, idx) => (
                    <li key={shot.url}>
                      <button
                        type="button"
                        onClick={() => onLightbox(idx)}
                        className="group block w-full text-left"
                      >
                        <div className="aspect-video overflow-hidden rounded-md bg-muted">
                          <img
                            src={shot.url}
                            alt={shot.caption || `Screenshot ${idx + 1}`}
                            loading="lazy"
                            className="h-full w-full object-cover transition-opacity group-hover:opacity-90"
                          />
                        </div>
                        {shot.caption ? (
                          <p className="mt-1 truncate text-xs text-muted-foreground">
                            {shot.caption}
                          </p>
                        ) : null}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </div>
        <aside className="space-y-4">
          <div className="grimoire-card p-6">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              Details
            </h3>
            <dl className="space-y-2 text-sm">
              {mod.category ? <Row k="Category" v={mod.category} /> : null}
              <Row k="Downloads" v={mod.downloads.toLocaleString()} />
              {mod.latestVersion ? <Row k="Latest" v={`v${mod.latestVersion}`} /> : null}
              {mod.license ? <Row k="License" v={mod.license} /> : null}
            </dl>
          </div>
          {mod.tags.length > 0 ? (
            <div className="grimoire-card p-6">
              <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                Tags
              </h3>
              <div className="flex flex-wrap gap-1.5">
                {mod.tags.map((t) => (
                  <Badge key={t} variant="secondary">
                    {t}
                  </Badge>
                ))}
              </div>
            </div>
          ) : null}
        </aside>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="font-medium">{v}</dd>
    </div>
  );
}
