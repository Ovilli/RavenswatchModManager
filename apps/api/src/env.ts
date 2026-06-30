import { config as loadEnv } from 'dotenv';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

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

export const env = {
  port: parsePort(process.env.API_PORT, 3001),
  databaseUrl: required('DATABASE_URL'),
  betterAuthSecret: required('BETTER_AUTH_SECRET'),
  betterAuthUrl: process.env.BETTER_AUTH_URL || 'http://localhost:3001',
  virusTotalApiKey: process.env.VIRUS_TOTAL_API_KEY ?? process.env.VIRUSTOTAL_API_KEY ?? '',
  // Public URL of the marketing site. Used as the verification-email
  // landing target. Defaults to localhost so dev works without extra
  // config; prod overrides via WEB_URL.
  webUrl: process.env.WEB_URL || 'http://localhost:3000',
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
    //  - the public browser site (www.rsmm.me; apex redirects there)
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

export function testmailConfigured(): boolean {
  return Boolean(env.testmail.apikey && env.testmail.namespace);
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
