import { modImagePresignSchema } from '@rsmm/schemas';

export interface Screenshot {
  url: string;
  caption?: string;
}

export const MAX_SCREENSHOTS = 12;

export interface ScreenshotUploadIssue {
  file: File;
  message: string;
}

/** Validate before requesting storage, keeping the file picker's order. */
export function selectScreenshotFiles(files: File[], existingCount: number) {
  const accepted: File[] = [];
  const issues: ScreenshotUploadIssue[] = [];
  for (const file of files) {
    const validation = modImagePresignSchema.safeParse({
      contentType: file.type,
      sizeBytes: file.size,
    });
    let message: string | undefined;
    if (!validation.success) {
      message = !['image/png', 'image/jpeg', 'image/webp'].includes(file.type)
        ? 'Choose a PNG, JPEG, or WebP image.'
        : file.size === 0
          ? 'This file is empty.'
          : 'Choose an image no larger than 8 MB.';
    } else if (existingCount + accepted.length >= MAX_SCREENSHOTS) {
      message = 'The gallery holds 12 screenshots. Remove an image before adding this one.';
    }
    if (message) issues.push({ file, message });
    else accepted.push(file);
  }
  return { accepted, issues };
}

/** A failed file must not discard the rest of the selection or reorder it. */
export async function uploadScreenshotBatch(
  files: File[],
  upload: (file: File) => Promise<string>,
  onFile: (file: File, index: number) => void,
) {
  const screenshots: Screenshot[] = [];
  const failures: { file: File; error: unknown }[] = [];
  for (const [index, file] of files.entries()) {
    onFile(file, index);
    try {
      screenshots.push({ url: await upload(file) });
    } catch (error) {
      failures.push({ file, error });
    }
  }
  return { screenshots, failures };
}

export function moveScreenshot(screenshots: Screenshot[], url: string, offset: -1 | 1) {
  const from = screenshots.findIndex((shot) => shot.url === url);
  const to = from + offset;
  if (from < 0 || to < 0 || to >= screenshots.length) return screenshots;
  const next = [...screenshots];
  const [shot] = next.splice(from, 1);
  if (shot) next.splice(to, 0, shot);
  return next;
}

/** Serialize complete gallery snapshots so a slower old request cannot win.
 * A rejected write is reported to its caller without blocking later edits. */
export function createScreenshotSaveQueue(save: (shots: Screenshot[]) => Promise<unknown>) {
  let tail: Promise<unknown> = Promise.resolve();
  return (screenshots: Screenshot[]) => {
    const snapshot = screenshots.map((shot) => ({
      url: shot.url,
      caption: shot.caption?.trim() || undefined,
    }));
    const result = tail.then(() => save(snapshot));
    tail = result.catch(() => {});
    return result;
  };
}
