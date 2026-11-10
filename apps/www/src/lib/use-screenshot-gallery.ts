'use client';

import { ApiError } from '@rsmm/api-client';
import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from './api';
import {
  type Screenshot,
  type ScreenshotUploadIssue,
  createScreenshotSaveQueue,
  moveScreenshot,
  selectScreenshotFiles,
  uploadScreenshotBatch,
} from './screenshot-gallery';
import { putFile } from './upload';

function describeError(error: unknown) {
  if (error instanceof ApiError) {
    const body = error.body as { error?: string } | null;
    return body?.error || `HTTP ${error.status}`;
  }
  return error instanceof Error ? error.message : String(error);
}

/** Mounted once per mod. Gallery writes own their state; metadata saves and
 * background query refreshes must not restore an older screenshot order. */
export function useScreenshotGallery(slug: string, initial: Screenshot[] | undefined) {
  const [screenshots, setScreenshots] = useState<Screenshot[]>(initial ?? []);
  const current = useRef(screenshots);
  const edited = useRef(false);
  const revision = useRef(0);
  const saveRequest = useRef(0);
  const uploading = useRef(false);
  const [saveStatus, setSaveStatus] = useState('');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [issues, setIssues] = useState<ScreenshotUploadIssue[]>([]);
  const [retryFiles, setRetryFiles] = useState<File[]>([]);
  const [progress, setProgress] = useState<{
    name: string;
    index: number;
    total: number;
    percent: number;
  } | null>(null);
  const [announcement, setAnnouncement] = useState('');
  const enqueueSave = useMemo(
    () => createScreenshotSaveQueue((shots) => api.mods.patch(slug, { screenshots: shots })),
    [slug],
  );

  useEffect(() => {
    if (edited.current || !initial) return;
    current.current = initial;
    setScreenshots(initial);
  }, [initial]);

  function replace(next: Screenshot[]) {
    edited.current = true;
    revision.current += 1;
    current.current = next;
    setScreenshots(next);
  }

  async function save() {
    const savingRevision = revision.current;
    const request = ++saveRequest.current;
    setSaveStatus('Saving changes…');
    setSaveError(null);
    try {
      await enqueueSave(current.current);
      if (revision.current === savingRevision && saveRequest.current === request) {
        setSaveStatus('All changes saved.');
        setSaveError(null);
      }
    } catch (error) {
      if (revision.current === savingRevision && saveRequest.current === request) {
        setSaveStatus('');
        setSaveError(describeError(error));
      }
    }
  }

  function move(url: string, to: number) {
    const next = moveScreenshot(current.current, url, to);
    if (next === current.current) return;
    replace(next);
    setAnnouncement(
      `Screenshot moved to position ${next.findIndex((shot) => shot.url === url) + 1} of ${next.length}.`,
    );
    void save();
  }

  function remove(url: string) {
    replace(current.current.filter((shot) => shot.url !== url));
    setAnnouncement('Screenshot removed.');
    void save();
  }

  function setCaption(url: string, caption: string) {
    replace(current.current.map((shot) => (shot.url === url ? { ...shot, caption } : shot)));
    setSaveStatus('Unsaved caption.');
  }

  async function upload(files: File[]) {
    if (uploading.current || files.length === 0) return;
    const selection = selectScreenshotFiles(files, current.current.length);
    setIssues(selection.issues);
    setRetryFiles([]);
    if (selection.accepted.length === 0) return;
    uploading.current = true;
    // Prevent a background detail refetch from replacing local edits mid-batch.
    edited.current = true;
    try {
      const result = await uploadScreenshotBatch(
        selection.accepted,
        async (file) => {
          const presigned = await api.mods.presignImage(slug, {
            contentType: file.type as 'image/png' | 'image/jpeg' | 'image/webp',
            sizeBytes: file.size,
          });
          await putFile(presigned.uploadUrl, file, {
            headers: { 'Content-Type': file.type },
            what: 'screenshot upload',
            onProgress: (loaded, total) => {
              setProgress((p) => (p ? { ...p, percent: Math.round((loaded / total) * 100) } : p));
            },
          });
          return presigned.publicUrl;
        },
        (file, index) => {
          setProgress({ name: file.name, index, total: selection.accepted.length, percent: 0 });
        },
      );
      setIssues([
        ...selection.issues,
        ...result.failures.map(({ file, error }) => ({ file, message: describeError(error) })),
      ]);
      setRetryFiles(result.failures.map(({ file }) => file));
      if (result.screenshots.length > 0) {
        // Read the latest array: captions/removals/reordering may change during upload.
        replace([...current.current, ...result.screenshots]);
        await save();
      }
      setAnnouncement(
        `${result.screenshots.length} screenshot${result.screenshots.length === 1 ? '' : 's'} uploaded.`,
      );
    } finally {
      uploading.current = false;
      setProgress(null);
    }
  }

  return {
    screenshots,
    move,
    remove,
    setCaption,
    save,
    upload,
    progress,
    issues,
    retryFiles,
    saveStatus,
    saveError,
    announcement,
  };
}
