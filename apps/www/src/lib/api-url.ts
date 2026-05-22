/**
 * Resolve the API base URL the marketing site should talk to.
 *
 * Precedence:
 *   1. `NEXT_PUBLIC_API_URL` at build time, if the deploy env supplies it.
 *   2. Production fallback when the page is served from a real domain
 *      (anything that isn't localhost / 127.0.0.1 / a Vercel preview's
 *      *.vercel.app default). This catches the case where the Vercel
 *      project forgets the env var.
 *   3. `http://localhost:3001` for local `next dev`.
 *
 * Kept in one module so the auth client and the API client agree —
 * a mismatch (e.g. auth on prod, list on localhost) silently breaks
 * sign-in flows that depend on shared cookies.
 */
const PROD_API_URL = 'https://api.ravenswatch.ovilli.de';
const DEV_API_URL = 'http://localhost:3001';

export function getApiUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  if (envUrl) return envUrl;
  if (typeof window !== 'undefined') {
    const h = window.location.hostname;
    if (h === 'localhost' || h === '127.0.0.1') return DEV_API_URL;
    return PROD_API_URL;
  }
  // SSR build with no env: assume production — we deploy to Vercel.
  return PROD_API_URL;
}
