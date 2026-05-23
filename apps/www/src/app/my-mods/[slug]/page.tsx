'use client';

import { ApiError } from '@rsmm/api-client';
import type { ModCategory } from '@rsmm/schemas';
import { Badge, Button, Input, Spinner } from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, ImageIcon, Loader2, Save, Trash2, Upload } from 'lucide-react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { api } from '../../../lib/api';
import { useSession } from '../../../lib/auth-client';

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
    // repoUrl / homepageUrl are not on ModListItem; leave blank and
    // let the user fill them on first save.
    setRepoUrl('');
    setHomepageUrl('');
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

  return (
    <main className="container mx-auto max-w-3xl space-y-8 px-6 py-12">
      <header>
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
            <div data-color-mode="dark">
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
              <div data-color-mode="dark">
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
    </main>
  );
}
