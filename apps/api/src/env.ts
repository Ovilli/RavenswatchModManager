import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { config as loadEnv } from 'dotenv';

const here = fileURLToPath(new URL('.', import.meta.url));
const repoRoot = resolve(here, '..', '..', '..');
// `.env.local` holds secrets and wins over `.env` (which is the
// committed template). dotenv never overrides existing keys, so the
// LAST load wins — load repo-root files first, then CWD files.
loadEnv({ path: resolve(repoRoot, '.env') });
loadEnv({ path: resolve(repoRoot, '.env.local') });
loadEnv({ path: '.env' });
loadEnv({ path: '.env.local' });
// Also pick up the default CWD `.env` search (handles Docker / PM2
// setups where the CWD is the API dir).
loadEnv();

export const isProduction = process.env.NODE_ENV === 'production';

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

/** Canonical public site origin, used when the deploy did not say. */
const CANONICAL_WEB_URL = 'https://rsmm.me';

function isLocalhostUrl(url: string): boolean {
  return /^https?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/i.test(url);
}

function resolveWebUrl(): string {
  const raw = process.env.WEB_URL?.trim();
  if (!isProduction) return raw || 'http://localhost:3000';
  if (!raw || isLocalhostUrl(raw)) {
    console.warn(
      `WEB_URL is ${raw ? 'a localhost address' : 'not set'} in production — user-facing links (shared logs, email landings) would point at the developer's machine. Falling back to ${CANONICAL_WEB_URL}; set WEB_URL on the deploy to make this explicit.`,
    );
    return CANONICAL_WEB_URL;
  }
  return raw;
}

export const env = {
  port: parsePort(process.env.API_PORT, 3001),
  databaseUrl: required('DATABASE_URL'),
  betterAuthSecret: required('BETTER_AUTH_SECRET'),
  betterAuthUrl: process.env.BETTER_AUTH_URL || 'http://localhost:3001',
  virusTotalApiKey: process.env.VIRUS_TOTAL_API_KEY ?? process.env.VIRUSTOTAL_API_KEY ?? '',
  // Shared secret the scheduled scan-drain endpoint checks. Vercel Cron sends
  // it as `Authorization: Bearer <CRON_SECRET>`. Without a cron the in-process
  // setInterval worker never fires on serverless (the instance is torn down
  // between requests), so a freshly uploaded version can sit 'pending' forever
  // and stay hidden by the fail-closed serve gate. The cron is the guaranteed
  // heartbeat that drains the queue. Empty in dev (endpoint is then disabled).
  cronSecret: process.env.CRON_SECRET ?? '',
  // Public URL of the marketing site — the origin every user-facing link the
  // API hands out is built from (a shared log's /l/<id>, email landing pages).
  //
  // Defaults to localhost so dev works without extra config, but that default
  // is actively wrong in production and fails SILENTLY: the API answers 200
  // and the user is handed http://localhost:3000/l/<id>, a link that works on
  // nobody's machine but the developer's. That shipped — the WEB_URL var was
  // simply never set on the deploy. So in production a missing or localhost
  // value is treated as the misconfiguration it is and replaced with the
  // canonical origin, which is the same call apps/www/src/lib/api-url.ts
  // already makes in the other direction for the same reason.
  webUrl: resolveWebUrl(),
  // User IDs allowed to approve/reject community guides (comma-separated).
  // Empty in dev — see guidesRouter approval endpoints.
  adminUserIds: (process.env.ADMIN_USER_IDS || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean),
  // Tauri WebView origins vary by platform and must always be accepted
  // regardless of the TRUSTED_ORIGINS env override:
  //   Linux WebKitGTK:   tauri://localhost
  //   Windows WebView2:  http://tauri.localhost
  trustedOrigins: (() => {
    const devDefault = 'http://localhost:3000,http://localhost:1420';
    const fromEnv = (process.env.TRUSTED_ORIGINS || devDefault)
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    // Always-trusted origins, regardless of NODE_ENV or env overrides:
    //  - the public browser site (rsmm.me is canonical; www 308s to it,
    //    but keep www trusted so a request already in flight isn't rejected)
    //  - every Tauri WebView origin the desktop app ships under
    // Baked in so a CORS-breaking misconfig can't drop them.
    const alwaysTrusted = [
      'https://www.rsmm.me',
      'https://rsmm.me',
      'tauri://localhost',
      'https://tauri.localhost',
      'http://tauri.localhost',
    ];
    // Optional extra site origin via WEB_URL (also used for email links).
    const webOrigin = (() => {
      try {
        return new URL(process.env.WEB_URL || 'http://localhost:3000').origin;
      } catch {
        return '';
      }
    })();
    return [...new Set([...fromEnv, ...alwaysTrusted, webOrigin].filter(Boolean))];
  })(),
  s3: {
    bucket: process.env.S3_BUCKET ?? '',
    region: process.env.S3_REGION ?? 'auto',
    endpoint: process.env.S3_ENDPOINT, // R2: https://<account>.r2.cloudflarestorage.com
    accessKeyId: process.env.S3_ACCESS_KEY_ID ?? '',
    secretAccessKey: process.env.S3_SECRET_ACCESS_KEY ?? '',
    publicBaseUrl: process.env.S3_PUBLIC_BASE_URL ?? '', // e.g. https://cdn.rsmm.me
    signedUrlTtlSeconds: (() => {
      const raw = process.env.S3_SIGNED_TTL;
      if (!raw) return 900;
      const n = Number(raw);
      if (!Number.isFinite(n) || n < 1) {
        console.warn(`Invalid S3_SIGNED_TTL "${raw}", falling back to 900`);
        return 900;
      }
      return n;
    })(),
  },
  google: {
    clientId: process.env.GOOGLE_CLIENT_ID ?? '',
    clientSecret: process.env.GOOGLE_CLIENT_SECRET ?? '',
  },
  github: {
    clientId: process.env.GITHUB_CLIENT_ID ?? '',
    clientSecret: process.env.GITHUB_CLIENT_SECRET ?? '',
  },
  smtp: {
    host: process.env.SMTP_HOST ?? '',
    port: (() => {
      const raw = process.env.SMTP_PORT;
      if (!raw) return 587;
      const n = Number(raw);
      if (!Number.isFinite(n) || n < 1 || n > 65535) {
        console.warn(`Invalid SMTP_PORT "${raw}", falling back to 587`);
        return 587;
      }
      return n;
    })(),
    user: process.env.SMTP_USER ?? '',
    pass: process.env.SMTP_PASS ?? '',
    // STARTTLS on 587 by default; set SMTP_SECURE=true for SMTPS on 465.
    secure: process.env.SMTP_SECURE === 'true',
    from: process.env.EMAIL_FROM || 'no-reply.ravenswatch@ovilli.de',
  },
  // testmail.app inbox used by the email-verification e2e test. testmail
  // only RECEIVES mail (at <namespace>.<tag>@inbox.testmail.app); the API
  // still sends through SMTP above. Unset in prod — the test self-skips.
  testmail: {
    apikey: process.env.TESTMAIL_APIKEY ?? '',
    namespace: process.env.TESTMAIL_NAMESPACE ?? '',
  },
  // Impressum (§5 DDG) contact details, served to the www legal page via
  // /api/legal/impressum. Kept out of git — set in .env.local (dev) or the
  // host's env dashboard (prod), never hardcoded in source.
  impressum: {
    name: process.env.IMPRESSUM_NAME ?? '',
    address: process.env.IMPRESSUM_ADDRESS ?? '',
    email: process.env.IMPRESSUM_EMAIL ?? '',
  },
};

export function s3Configured(): boolean {
  return Boolean(env.s3.bucket && env.s3.accessKeyId && env.s3.secretAccessKey);
}

export function smtpConfigured(): boolean {
  return Boolean(env.smtp.host && env.smtp.user && env.smtp.pass);
}

export function googleConfigured(): boolean {
  return Boolean(env.google.clientId && env.google.clientSecret);
}

export function githubConfigured(): boolean {
  return Boolean(env.github.clientId && env.github.clientSecret);
}

export function virusTotalConfigured(): boolean {
  return Boolean(env.virusTotalApiKey);
}

export function cronConfigured(): boolean {
  return Boolean(env.cronSecret);
}

export function testmailConfigured(): boolean {
  return Boolean(env.testmail.apikey && env.testmail.namespace);
}

export function impressumConfigured(): boolean {
  return Boolean(env.impressum.name && env.impressum.address && env.impressum.email);
}

if (isProduction && !smtpConfigured()) {
  console.warn(
    'SMTP not configured — email verification and password reset will fail. Set SMTP_HOST, SMTP_USER, SMTP_PASS, and EMAIL_FROM to enable them.',
  );
}

if (isProduction && !virusTotalConfigured()) {
  console.warn(
    'VirusTotal not configured — uploaded mods will not be scanned. Set VIRUS_TOTAL_API_KEY to enable upload scanning.',
  );
}

/**
 * Whether rate limits are shared across instances.
 *
 * Without Upstash, `createRateLimiter` falls back to a per-process sliding
 * window, so on a serverless deploy the effective limit is
 * `maxHits x instances` — the counters are not merely approximate, they are
 * independent. That is survivable for read endpoints and not for the ones
 * whose limit IS the abuse control: `/api/logs` stores up to 150 KB of
 * user-supplied text per accepted call, which without a shared counter is a
 * pastebin with a soft cap.
 */
export function distributedRateLimitsConfigured(): boolean {
  return Boolean(process.env.UPSTASH_REDIS_REST_URL && process.env.UPSTASH_REDIS_REST_TOKEN);
}

if (isProduction && !distributedRateLimitsConfigured()) {
  console.warn(
    'Upstash not configured — rate limits are per-instance, so on a scaled deploy the real limit is maxHits x instances. Set UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN; the shared-log endpoint (/api/logs) depends on this to bound how much user-supplied text it will store.',
  );
}

if (isProduction && !impressumConfigured()) {
  console.warn(
    'Impressum not configured — the /legal page on rsmm.me is not §5 DDG compliant. Set IMPRESSUM_NAME, IMPRESSUM_ADDRESS, and IMPRESSUM_EMAIL.',
  );
}
