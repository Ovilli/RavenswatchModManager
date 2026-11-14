'use client';
import { ApiError, isRateLimited } from '@rsmm/api-client';
import type { CollectionDetail } from '@rsmm/schemas';
import { Button, Input } from '@rsmm/ui';
import { useQueryClient } from '@tanstack/react-query';
import { ImageIcon, Loader2, Save, Upload, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { api } from '../../../lib/api';
import { MDEditor } from '../../components/md-editor';

export function describeCollectionError(error: unknown): string {
  if (isRateLimited(error)) return `Try again in ${error.retryAfter}s.`;
  if (error instanceof ApiError) {
    const body = error.body as { error?: string } | null;
    if (body?.error) return body.error;
  }
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.';
}

async function uploadImage(file: File, slug: string): Promise<string> {
  const contentType = file.type as 'image/png' | 'image/jpeg' | 'image/webp';
  const presign = await api.collections.presignImage(slug, { contentType, sizeBytes: file.size });
  const response = await fetch(presign.uploadUrl, {
    method: 'PUT',
    body: file,
    headers: { 'Content-Type': contentType },
  });
  if (!response.ok) throw new Error('The image couldn’t be uploaded. Please try again.');
  return presign.publicUrl;
}

export function CollectionEditor({
  collection: c,
  onClose,
}: {
  collection: CollectionDetail;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [editName, setEditName] = useState(c.name);
  const [editSummary, setEditSummary] = useState(c.summary ?? '');
  const [editDescription, setEditDescription] = useState(c.description ?? '');
  const [editIsPublic, setEditIsPublic] = useState(c.isPublic);
  const [imageUrl, setImageUrl] = useState(c.imageUrl);
  const [editIconFile, setEditIconFile] = useState<File | null>(null);
  const [editIconPreview, setEditIconPreview] = useState<string | null>(null);
  const [editScreenshots, setEditScreenshots] = useState(c.screenshots ?? []);
  const [newScreenshots, setNewScreenshots] = useState<
    { file: File; preview: string; caption: string }[]
  >([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  const previews = useRef<string[]>([]);
  useEffect(() => {
    previews.current = [editIconPreview, ...newScreenshots.map((shot) => shot.preview)].filter(
      (url): url is string => !!url,
    );
  }, [editIconPreview, newScreenshots]);
  useEffect(
    () => () => {
      for (const url of previews.current) URL.revokeObjectURL(url);
    },
    [],
  );

  const saveEditing = async () => {
    setSaving(true);
    setError(null);
    try {
      const cover = editIconFile ? await uploadImage(editIconFile, c.slug) : imageUrl;
      const shots = [...editScreenshots];
      for (const shot of newScreenshots) {
        const url = await uploadImage(shot.file, c.slug);
        shots.push({ url, caption: shot.caption || undefined });
      }
      await api.collections.patch(c.slug, {
        name: editName.trim(),
        summary: editSummary.trim() || null,
        description: editDescription || null,
        imageUrl: cover,
        screenshots: shots,
        isPublic: editIsPublic,
      });
      await qc.invalidateQueries({ queryKey: ['collections', c.slug] });
      onClose();
    } catch (error) {
      setError(describeCollectionError(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section
      id="collection-editor"
      className="mod-section"
      aria-labelledby="collection-editor-heading"
    >
      <h2 id="collection-editor-heading" ref={heading} tabIndex={-1}>
        Edit collection
      </h2>
      <fieldset disabled={saving} className="space-y-5 min-w-0">
        <label htmlFor="collection-name" className="block space-y-1.5 text-sm font-medium">
          <span>Name</span>
          <Input
            id="collection-name"
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            maxLength={128}
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={editIsPublic}
            onChange={(e) => setEditIsPublic(e.target.checked)}
          />
          Public collection
        </label>

        <div className="space-y-1.5">
          <span className="block text-sm font-medium">Icon / Cover image</span>
          <div className="flex items-center gap-3">
            {editIconPreview || imageUrl ? (
              <img
                src={editIconPreview ?? imageUrl ?? ''}
                alt="Icon preview"
                className="h-24 w-24 rounded-md object-cover"
              />
            ) : null}
            <label className="flex cursor-pointer items-center gap-2 rounded-md border border-input px-3 py-2 text-sm hover:bg-accent">
              <Upload className="h-4 w-4" />
              <span>{editIconPreview || imageUrl ? 'Replace' : 'Upload'}</span>
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) {
                    if (editIconPreview) URL.revokeObjectURL(editIconPreview);
                    setEditIconFile(f);
                    setEditIconPreview(URL.createObjectURL(f));
                  }
                }}
              />
            </label>
            {editIconPreview || imageUrl ? (
              <button
                type="button"
                onClick={() => {
                  if (editIconPreview) URL.revokeObjectURL(editIconPreview);
                  setEditIconFile(null);
                  setEditIconPreview(null);
                  setImageUrl(null);
                }}
                className="text-sm text-destructive hover:underline"
              >
                Remove
              </button>
            ) : null}
          </div>
        </div>
        <textarea
          aria-label="Summary"
          value={editSummary}
          onChange={(e) => setEditSummary(e.target.value)}
          maxLength={512}
          rows={2}
          className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          placeholder="Summary"
        />

        <div className="space-y-1.5">
          <span className="block text-sm font-medium">
            Description <span className="text-muted-foreground">(Markdown)</span>
          </span>
          <div data-color-mode="dark" className="md-editor-themed">
            <MDEditor
              value={editDescription}
              onChange={(v) => setEditDescription(v ?? '')}
              preview="edit"
              height={300}
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <span className="block text-sm font-medium">Screenshots (gallery)</span>
          <div className="grid grid-cols-3 gap-3 sm:grid-cols-4">
            {editScreenshots.map((shot, i) => (
              <div key={shot.url} className="relative">
                <img
                  loading="lazy"
                  src={shot.url}
                  alt={shot.caption || `Screenshot ${i + 1}`}
                  className="aspect-video w-full rounded-md object-cover"
                />
                <button
                  type="button"
                  aria-label={`Remove screenshot ${i + 1}`}
                  onClick={() => setEditScreenshots((prev) => prev.filter((_, j) => j !== i))}
                  className="absolute -right-2 -top-2 rounded-full bg-background border p-1"
                >
                  <X className="h-3 w-3" />
                </button>
                <input
                  value={shot.caption ?? ''}
                  onChange={(e) =>
                    setEditScreenshots((prev) =>
                      prev.map((x, j) => (j === i ? { ...x, caption: e.target.value } : x)),
                    )
                  }
                  aria-label={`Screenshot ${i + 1} caption`}
                  maxLength={200}
                  placeholder="Caption"
                  className="mt-1 w-full rounded border border-input bg-background px-1.5 py-0.5 text-xs"
                />
              </div>
            ))}
            {newScreenshots.map((ns, i) => (
              <div key={ns.preview} className="relative">
                <img
                  src={ns.preview}
                  alt={`New screenshot ${i + 1}`}
                  className="aspect-video w-full rounded-md object-cover"
                />
                <button
                  type="button"
                  aria-label={`Remove new screenshot ${i + 1}`}
                  onClick={() => {
                    URL.revokeObjectURL(ns.preview);
                    setNewScreenshots((prev) => prev.filter((_, j) => j !== i));
                  }}
                  className="absolute -right-2 -top-2 rounded-full bg-background border p-1"
                >
                  <X className="h-3 w-3" />
                </button>
                <input
                  value={ns.caption}
                  onChange={(e) =>
                    setNewScreenshots((prev) =>
                      prev.map((x, j) => (j === i ? { ...x, caption: e.target.value } : x)),
                    )
                  }
                  aria-label={`Screenshot ${i + 1} caption`}
                  maxLength={200}
                  placeholder="Caption"
                  className="mt-1 w-full rounded border border-input bg-background px-1.5 py-0.5 text-xs"
                />
              </div>
            ))}
            {editScreenshots.length + newScreenshots.length < 12 ? (
              <label
                aria-label="Add screenshot"
                className="flex aspect-video cursor-pointer items-center justify-center rounded-md border border-dashed border-input text-muted-foreground hover:bg-accent"
              >
                <ImageIcon className="h-5 w-5" />
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) {
                      setNewScreenshots((prev) => [
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

        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        <div className="flex items-center gap-2">
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" size="sm" onClick={saveEditing} disabled={!editName.trim()}>
            {saving ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-1 h-4 w-4" />
            )}
            {saving ? 'Saving…' : 'Save collection'}
          </Button>
        </div>
      </fieldset>
    </section>
  );
}
