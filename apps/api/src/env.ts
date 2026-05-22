import { config as loadEnv } from 'dotenv';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = fileURLToPath(new URL('.', import.meta.url));
const repoRoot = resolve(here, '..', '..', '..');
// `.env.local` holds secrets and wins over `.env` (which is the
// committed template). dotenv preserves the first value it sees per key,
// so load `.local` first, then the template as fallback.
loadEnv({ path: resolve(repoRoot, '.env.local') });
loadEnv({ path: resolve(repoRoot, '.env') });
loadEnv({ path: '.env.local' });
loadEnv();

function required(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`${name} env var is required`);
  return v;
}

function parsePort(raw: string | undefined, fallback: number): number {
  if (!raw) return fallback;
  const n = Number.parseInt(raw, 10);
  if (Number.isNaN(n) || n < 1 || n > 65535) {
    console.warn(`Invalid API_PORT "${raw}", falling back to ${fallback}`);
    return fallback;
  }
  return n;
}

export const env = {
  port: parsePort(process.env.API_PORT, 3001),
  databaseUrl: required('DATABASE_URL'),
  betterAuthSecret: required('BETTER_AUTH_SECRET'),
  betterAuthUrl: process.env.BETTER_AUTH_URL || 'http://localhost:3001',
  trustedOrigins: (process.env.TRUSTED_ORIGINS || 'http://localhost:3000,http://localhost:1420,tauri://localhost,https://tauri.localhost')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean),
  s3: {
    bucket: process.env.S3_BUCKET ?? '',
    region: process.env.S3_REGION ?? 'auto',
    endpoint: process.env.S3_ENDPOINT, // R2: https://<account>.r2.cloudflarestorage.com
    accessKeyId: process.env.S3_ACCESS_KEY_ID ?? '',
    secretAccessKey: process.env.S3_SECRET_ACCESS_KEY ?? '',
    publicBaseUrl: process.env.S3_PUBLIC_BASE_URL ?? '', // e.g. https://cdn.rsmm.dev
    signedUrlTtlSeconds: Number(process.env.S3_SIGNED_TTL ?? 900),
  },
};

export function s3Configured(): boolean {
  return Boolean(env.s3.bucket && env.s3.accessKeyId && env.s3.secretAccessKey);
}
