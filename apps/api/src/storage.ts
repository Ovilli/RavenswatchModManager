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
  const publicUrl = env.s3.publicBaseUrl
    ? `${env.s3.publicBaseUrl.replace(/\/$/, '')}/${key}`
    : `${env.s3.endpoint ?? `https://${env.s3.bucket}.s3.${env.s3.region}.amazonaws.com`}/${key}`;
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
