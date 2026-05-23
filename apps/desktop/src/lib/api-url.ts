/**
 * Resolve the API base URL the desktop app should talk to.
 *
 * Precedence:
 *   1. `VITE_API_URL` at build time — explicit override (point at a
 *      staging deploy, raw localhost backend, etc.).
 *   2. `window.location.origin` when running under Vite's dev server.
 *      Requests become same-origin against the dev server, which
 *      proxies `/api` to the real backend (see `vite.config.ts`).
 *      Skips CORS — the production API does not whitelist
 *      `http://localhost:1420`.
 *   3. The production deployment otherwise. Tauri production builds
 *      land here because Vite's `DEV` flag is false in bundles, and
 *      `tauri://localhost` / `https://tauri.localhost` ARE whitelisted
 *      server-side.
 *
 * Kept in one module so the API client and the auth client agree —
 * a mismatch (auth on prod, mod list on localhost) silently breaks
 * sign-in flows that depend on shared cookies. Mirrors
 * `apps/www/src/lib/api-url.ts`.
 */
const PROD_API_URL = 'https://api.ravenswatch.ovilli.de';

export function getApiUrl(): string {
  const envUrl = import.meta.env.VITE_API_URL;
  if (envUrl) return envUrl;
  if (import.meta.env.DEV && typeof window !== 'undefined') {
    return window.location.origin;
  }
  return PROD_API_URL;
}
