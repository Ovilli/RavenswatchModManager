import {
  DeleteObjectCommand,
  GetObjectCommand,
  HeadObjectCommand,
  PutObjectCommand,
  S3Client,
} from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import { env, s3Configured } from './env.js';
import { errString } from './logger.js';

let cached: S3Client | null = null;

export function s3(): S3Client {
  if (cached) return cached;
  if (!s3Configured()) {
    throw new Error(
      'S3 not configured. Set S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY (and S3_ENDPOINT for R2).',
    );
  }
  cached = new S3Client({
    region: env.s3.region,
    endpoint: env.s3.endpoint,
    forcePathStyle: Boolean(env.s3.endpoint), // R2 + minio need path-style
    credentials: {
      accessKeyId: env.s3.accessKeyId,
      secretAccessKey: env.s3.secretAccessKey,
    },
  });
  return cached;
}

export interface SignedUpload {
  uploadUrl: string;
  publicUrl: string;
  key: string;
  expiresIn: number;
}

/** Canonical S3 key for a mod version's zip. Single source of truth so the
 *  upload presign and the post-upload existence check agree. */
export function modUploadKey(slug: string, version: string, sha256: string): string {
  return `mods/${slug}/${version}-${sha256.slice(0, 12)}.zip`;
}

/** HEAD an object to confirm it exists (e.g. that a presigned upload actually
 *  completed). Works on private buckets, unlike fetching the public URL.
 *
 *  Retries a few times: the finalize check fires immediately after the browser
 *  PUT, and a Cloudflare-fronted / eventually-consistent gateway can 404 a
 *  just-written key for a moment. A 404/NotFound is treated as "not yet" and
 *  retried; any other error (bad creds, wrong endpoint) is logged — otherwise
 *  a misconfig looks identical to a missing upload and silently blocks publish. */
export async function objectExists(key: string, tries = 4): Promise<boolean> {
  const delaysMs = [300, 800, 1800];
  for (let attempt = 0; attempt < tries; attempt++) {
    try {
      await s3().send(new HeadObjectCommand({ Bucket: env.s3.bucket, Key: key }));
      return true;
    } catch (err) {
      const status = (err as { $metadata?: { httpStatusCode?: number } })?.$metadata
        ?.httpStatusCode;
      const notFound = status === 404 || (err as { name?: string })?.name === 'NotFound';
      if (!notFound) {
        // Not a "missing object" — creds/endpoint/permission problem. Surface it.
        console.error('objectExists HEAD failed (non-404)', { key, status, err: errString(err) });
        return false;
      }
      const delay = delaysMs[attempt];
      if (delay === undefined) break; // out of retries
      await new Promise((r) => setTimeout(r, delay));
    }
  }
  return false;
}

/** Delete an object. Used to purge a version whose malware scan flagged it —
 *  the bucket is public, so hiding the DB row is not enough; the bytes must
 *  actually leave the bucket or the direct URL keeps serving them. */
export async function deleteObject(key: string): Promise<void> {
  await s3().send(new DeleteObjectCommand({ Bucket: env.s3.bucket, Key: key }));
}

/** Fetch an object's bytes (for scanning archive contents / file-upload scan).
 *  Returns null if the object is missing or too large to buffer safely. */
export async function getObjectBytes(key: string, maxBytes: number): Promise<Buffer | null> {
  try {
    const res = await s3().send(new GetObjectCommand({ Bucket: env.s3.bucket, Key: key }));
    const len = Number(res.ContentLength ?? 0);
    if (len > maxBytes) return null;
    const body = res.Body as { transformToByteArray?: () => Promise<Uint8Array> } | undefined;
    if (!body?.transformToByteArray) return null;
    const bytes = await body.transformToByteArray();
    if (bytes.byteLength > maxBytes) return null;
    return Buffer.from(bytes);
  } catch {
    return null;
  }
}

/**
 * Confirm an object landed by HEADing its public URL over plain HTTP, with a
 * short retry to absorb write→read propagation on a CDN-fronted gateway.
 *
 * Preferred over the SDK HeadObject for the finalize gate: the bucket is
 * public (that's how the scanner fetches it), so this needs no credentials —
 * a write-scoped S3 key that can presign+PUT but is denied HeadObject/GetObject
 * would otherwise make a present upload look missing.
 */
export async function remoteObjectExists(publicUrl: string, tries = 4): Promise<boolean> {
  const delaysMs = [300, 800, 1800];
  for (let attempt = 0; attempt < tries; attempt++) {
    try {
      // Cache-buster: the public URL is fronted by Cloudflare, which can hold a
      // cached NoSuchKey 404 from before the object landed (or from a deleted
      // predecessor). A unique query string forces a cache miss so we check the
      // origin, not the edge.
      const url = new URL(publicUrl);
      url.searchParams.set('rsmm-cb', `${Date.now()}-${attempt}`);
      const res = await fetch(url, { method: 'HEAD' });
      if (res.ok) return true;
      // 5xx / 429 are worth a retry; a 403/404 usually means not-there-yet or
      // access issue — retry a couple times then give up.
    } catch {
      // network blip — fall through to retry
    }
    const delay = delaysMs[attempt];
    if (delay === undefined) break;
    await new Promise((r) => setTimeout(r, delay));
  }
  return false;
}

export async function presignModUpload(args: {
  slug: string;
  version: string;
  sha256: string;
  sizeBytes: number;
}): Promise<SignedUpload> {
  const key = modUploadKey(args.slug, args.version, args.sha256);
  const cmd = new PutObjectCommand({
    Bucket: env.s3.bucket,
    Key: key,
    ContentType: 'application/zip',
    ContentLength: args.sizeBytes,
    ChecksumSHA256: bufToB64(hexToBuf(args.sha256)),
  });
  const uploadUrl = await getSignedUrl(s3(), cmd, { expiresIn: env.s3.signedUrlTtlSeconds });
  let publicUrl: string;
  if (env.s3.publicBaseUrl) {
    publicUrl = `${env.s3.publicBaseUrl.replace(/\/$/, '')}/${key}`;
  } else if (env.s3.endpoint) {
    // S3-compatible (R2 / MinIO) — path-style with bucket
    publicUrl = `${env.s3.endpoint.replace(/\/$/, '')}/${env.s3.bucket}/${key}`;
  } else {
    // Standard AWS S3 — virtual-hosted style
    publicUrl = `https://${env.s3.bucket}.s3.${env.s3.region}.amazonaws.com/${key}`;
  }
  return { uploadUrl, publicUrl, key, expiresIn: env.s3.signedUrlTtlSeconds };
}

export async function presignModImage(args: {
  slug: string;
  contentType: 'image/png' | 'image/jpeg' | 'image/webp';
  sizeBytes: number;
}): Promise<SignedUpload> {
  const ext =
    args.contentType === 'image/png' ? 'png' : args.contentType === 'image/webp' ? 'webp' : 'jpg';
  // Random suffix so re-uploads don't collide with cached objects on
  // the public CDN. The mod row's image_url moves to the new key on
  // PATCH; the old object is orphaned and ages out of cache naturally.
  const id = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  const key = `mod-images/${args.slug}/${id}.${ext}`;
  const cmd = new PutObjectCommand({
    Bucket: env.s3.bucket,
    Key: key,
    ContentType: args.contentType,
    ContentLength: args.sizeBytes,
  });
  const uploadUrl = await getSignedUrl(s3(), cmd, { expiresIn: env.s3.signedUrlTtlSeconds });
  let publicUrl: string;
  if (env.s3.publicBaseUrl) {
    publicUrl = `${env.s3.publicBaseUrl.replace(/\/$/, '')}/${key}`;
  } else if (env.s3.endpoint) {
    publicUrl = `${env.s3.endpoint.replace(/\/$/, '')}/${env.s3.bucket}/${key}`;
  } else {
    publicUrl = `https://${env.s3.bucket}.s3.${env.s3.region}.amazonaws.com/${key}`;
  }
  return { uploadUrl, publicUrl, key, expiresIn: env.s3.signedUrlTtlSeconds };
}

export async function presignGuideImage(args: {
  slug: string;
  contentType: 'image/png' | 'image/jpeg' | 'image/webp';
  sizeBytes: number;
}): Promise<SignedUpload> {
  const ext =
    args.contentType === 'image/png' ? 'png' : args.contentType === 'image/webp' ? 'webp' : 'jpg';
  const id = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  const key = `guide-images/${args.slug}/${id}.${ext}`;
  const cmd = new PutObjectCommand({
    Bucket: env.s3.bucket,
    Key: key,
    ContentType: args.contentType,
    ContentLength: args.sizeBytes,
  });
  const uploadUrl = await getSignedUrl(s3(), cmd, { expiresIn: env.s3.signedUrlTtlSeconds });
  let publicUrl: string;
  if (env.s3.publicBaseUrl) {
    publicUrl = `${env.s3.publicBaseUrl.replace(/\/$/, '')}/${key}`;
  } else if (env.s3.endpoint) {
    publicUrl = `${env.s3.endpoint.replace(/\/$/, '')}/${env.s3.bucket}/${key}`;
  } else {
    publicUrl = `https://${env.s3.bucket}.s3.${env.s3.region}.amazonaws.com/${key}`;
  }
  return { uploadUrl, publicUrl, key, expiresIn: env.s3.signedUrlTtlSeconds };
}

export async function presignCollectionImage(args: {
  slug: string;
  contentType: 'image/png' | 'image/jpeg' | 'image/webp';
  sizeBytes: number;
}): Promise<SignedUpload> {
  const ext =
    args.contentType === 'image/png' ? 'png' : args.contentType === 'image/webp' ? 'webp' : 'jpg';
  const id = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  const key = `collection-images/${args.slug}/${id}.${ext}`;
  const cmd = new PutObjectCommand({
    Bucket: env.s3.bucket,
    Key: key,
    ContentType: args.contentType,
    ContentLength: args.sizeBytes,
  });
  const uploadUrl = await getSignedUrl(s3(), cmd, { expiresIn: env.s3.signedUrlTtlSeconds });
  let publicUrl: string;
  if (env.s3.publicBaseUrl) {
    publicUrl = `${env.s3.publicBaseUrl.replace(/\/$/, '')}/${key}`;
  } else if (env.s3.endpoint) {
    publicUrl = `${env.s3.endpoint.replace(/\/$/, '')}/${env.s3.bucket}/${key}`;
  } else {
    publicUrl = `https://${env.s3.bucket}.s3.${env.s3.region}.amazonaws.com/${key}`;
  }
  return { uploadUrl, publicUrl, key, expiresIn: env.s3.signedUrlTtlSeconds };
}

export async function presignAvatar(args: {
  userId: string;
  contentType: 'image/png' | 'image/jpeg' | 'image/webp';
  sizeBytes: number;
}): Promise<SignedUpload> {
  const ext =
    args.contentType === 'image/png' ? 'png' : args.contentType === 'image/webp' ? 'webp' : 'jpg';
  const id = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  const key = `avatars/${args.userId}/${id}.${ext}`;
  const cmd = new PutObjectCommand({
    Bucket: env.s3.bucket,
    Key: key,
    ContentType: args.contentType,
    ContentLength: args.sizeBytes,
  });
  const uploadUrl = await getSignedUrl(s3(), cmd, { expiresIn: env.s3.signedUrlTtlSeconds });
  let publicUrl: string;
  if (env.s3.publicBaseUrl) {
    publicUrl = `${env.s3.publicBaseUrl.replace(/\/$/, '')}/${key}`;
  } else if (env.s3.endpoint) {
    publicUrl = `${env.s3.endpoint.replace(/\/$/, '')}/${env.s3.bucket}/${key}`;
  } else {
    publicUrl = `https://${env.s3.bucket}.s3.${env.s3.region}.amazonaws.com/${key}`;
  }
  return { uploadUrl, publicUrl, key, expiresIn: env.s3.signedUrlTtlSeconds };
}

function hexToBuf(hex: string): Uint8Array {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = Number.parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}

function bufToB64(buf: Uint8Array): string {
  return Buffer.from(buf).toString('base64');
}
