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

function isLocalhostUrl(url: string): boolean {
  return /^https?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/i.test(url);
}

export function getApiUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  // Browser context: ignore a localhost env override when the page
  // itself isn't loaded from localhost. The Vercel deploy historically
  // shipped with NEXT_PUBLIC_API_URL=http://localhost:3001 baked into
  // the bundle, which made ravenswatch.ovilli.de try to fetch from the
  // user's own machine. Treat that combination as a misconfiguration
  // and route to PROD_API_URL.
  if (typeof window !== 'undefined') {
    const h = window.location.hostname;
    const onLocalhost = h === 'localhost' || h === '127.0.0.1';
    if (envUrl && !(isLocalhostUrl(envUrl) && !onLocalhost)) return envUrl;
    return onLocalhost ? DEV_API_URL : PROD_API_URL;
  }
  // SSR: a localhost env var almost certainly means a developer's
  // shell leaked into the build. Production SSR should hit prod.
  if (envUrl && !isLocalhostUrl(envUrl)) return envUrl;
  return PROD_API_URL;
}
