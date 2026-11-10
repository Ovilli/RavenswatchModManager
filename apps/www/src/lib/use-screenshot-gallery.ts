'use client';

import { ApiError } from '@rsmm/api-client';
import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import {
  type Screenshot,
  type ScreenshotUploadIssue,
  getListingPhotos,
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

/** Upload files to storage, but keep listing membership and order as a local
 * draft until the page's contextual Save changes action commits them. */
export function useScreenshotGallery(
  slug: string,
  initial: { imageUrl?: string | null; screenshots?: Screenshot[] } | undefined,
) {
  const [screenshots, setScreenshots] = useState<Screenshot[]>(() =>
    getListingPhotos(initial?.imageUrl, initial?.screenshots),
  );
  const current = useRef(screenshots);
  const hydrated = useRef(false);
  const generation = useRef(0);
  const uploading = useRef(false);
  const [isUploading, setIsUploading] = useState(false);
  const [issues, setIssues] = useState<ScreenshotUploadIssue[]>([]);
  const [retryFiles, setRetryFiles] = useState<File[]>([]);
  const [progress, setProgress] = useState<{
    name: string;
    index: number;
    total: number;
    percent: number;
  } | null>(null);
  const [announcement, setAnnouncement] = useState('');
  useEffect(() => {
    if (hydrated.current || !initial) return;
    hydrated.current = true;
    const photos = getListingPhotos(initial.imageUrl, initial.screenshots);
    current.current = photos;
    setScreenshots(photos);
  }, [initial]);

  useEffect(
    () => () => {
      generation.current += 1;
    },
    [],
  );

  function replace(next: Screenshot[]) {
    current.current = next;
    setScreenshots(next);
  }

  function reset(photos: Screenshot[]) {
    // Ignore results from uploads discarded or abandoned while in flight.
    generation.current += 1;
    uploading.current = false;
    setIsUploading(false);
    setProgress(null);
    setIssues([]);
    setRetryFiles([]);
    replace(photos);
  }

  function move(url: string, to: number) {
    const next = moveScreenshot(current.current, url, to);
    if (next === current.current) return;
    replace(next);
    setAnnouncement(
      to === 0 ? 'Cover photo updated.' : `Photo moved to position ${to + 1} of ${next.length}.`,
    );
  }

  function remove(url: string) {
    replace(current.current.filter((shot) => shot.url !== url));
    setAnnouncement('Photo deleted.');
  }

  function setCaption(url: string, caption: string) {
    replace(current.current.map((shot) => (shot.url === url ? { ...shot, caption } : shot)));
  }

  async function upload(files: File[]) {
    if (uploading.current || files.length === 0) return;
    const selection = selectScreenshotFiles(files, current.current.length);
    setIssues(selection.issues);
    setRetryFiles([]);
    if (selection.accepted.length === 0) return;
    uploading.current = true;
    setIsUploading(true);
    const batch = generation.current;
    try {
      const result = await uploadScreenshotBatch(
        selection.accepted,
        async (file) => {
          if (batch !== generation.current) throw new Error('Upload discarded');
          const presigned = await api.mods.presignImage(slug, {
            contentType: file.type as 'image/png' | 'image/jpeg' | 'image/webp',
            sizeBytes: file.size,
          });
          await putFile(presigned.uploadUrl, file, {
            headers: { 'Content-Type': file.type },
            what: 'photo upload',
            onProgress: (loaded, total) => {
              if (batch !== generation.current) return;
              setProgress((p) => (p ? { ...p, percent: Math.round((loaded / total) * 100) } : p));
            },
          });
          return presigned.publicUrl;
        },
        (file, index) => {
          if (batch !== generation.current) return;
          setProgress({ name: file.name, index, total: selection.accepted.length, percent: 0 });
        },
      );
      if (batch !== generation.current) return;
      setIssues([
        ...selection.issues,
        ...result.failures.map(({ file, error }) => ({ file, message: describeError(error) })),
      ]);
      setRetryFiles(result.failures.map(({ file }) => file));
      if (result.screenshots.length > 0) {
        // Read the latest array: captions/removals/reordering may change during upload.
        replace([...current.current, ...result.screenshots]);
      }
      setAnnouncement(
        `${result.screenshots.length} photo${result.screenshots.length === 1 ? '' : 's'} uploaded.`,
      );
    } finally {
      if (batch === generation.current) {
        uploading.current = false;
        setIsUploading(false);
        setProgress(null);
      }
    }
  }

  return {
    screenshots,
    coverUrl: screenshots[0]?.url ?? null,
    move,
    remove,
    setCaption,
    reset,
    upload,
    progress,
    issues,
    retryFiles,
    isUploading,
    announcement,
  };
}
