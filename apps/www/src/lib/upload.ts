import { formatObjectStorageError } from './object-storage-error';

// Shared by the publish, manage-mod and account pages, which each used to carry
// their own copy of these.

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MiB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GiB`;
}

export async function sha256Hex(file: Blob): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

/** Hex digest → base64, the form S3's `x-amz-checksum-sha256` header takes. */
export function hexToBase64(hex: string): string {
  let bin = '';
  for (let i = 0; i < hex.length; i += 2) {
    bin += String.fromCharCode(Number.parseInt(hex.slice(i, i + 2), 16));
  }
  return btoa(bin);
}

/**
 * PUT a file to a presigned object-storage URL. XHR rather than fetch because
 * fetch has no upload progress, and a mod archive can be hundreds of MB.
 * Rejects with the storage provider's error, made readable.
 */
export function putFile(
  url: string,
  file: Blob,
  opts: {
    headers: Record<string, string>;
    what: string;
    onProgress?: (loaded: number, total: number) => void;
  },
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', url);
    for (const [k, v] of Object.entries(opts.headers)) xhr.setRequestHeader(k, v);
    if (opts.onProgress) {
      const report = opts.onProgress;
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) report(e.loaded, e.total);
      };
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(formatObjectStorageError(xhr.status, xhr.responseText, opts.what)));
    };
    xhr.onerror = () => reject(new Error(`${opts.what} failed: network error`));
    xhr.send(file);
  });
}
