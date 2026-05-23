import { PutObjectCommand, S3Client } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import { env, s3Configured } from './env';

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

export async function presignModUpload(args: {
  slug: string;
  version: string;
  sha256: string;
  sizeBytes: number;
}): Promise<SignedUpload> {
  const key = `mods/${args.slug}/${args.version}-${args.sha256.slice(0, 12)}.zip`;
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
