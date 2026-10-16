import { ApiError, ApiTimeoutError, createApiClient } from '@rsmm/api-client';
import type { ModTranslations } from '@rsmm/schemas';
import { getApiUrl } from './api-url';
import { t } from './i18n';
import { modLocale } from './rsmm';

const API_BASE = getApiUrl();

// Don't send cookies on API fetch calls — the Tauri WebView origin
// (http://tauri.localhost on Windows) must be CORS-whitelisted by the
// API for credentialed requests. Since the desktop app uses a separate
// better-auth client for sign-in, the API client only needs public /
// unauthenticated access. Removing credentials avoids the strict CORS
// origin-matching requirement that breaks on Windows when the API's
// TRUSTED_ORIGINS env var doesn't include the Windows WebView origin.
const noCredsFetch: typeof fetch = (input, init) => fetch(input, { ...init, credentials: 'omit' });

const client = createApiClient({
  baseUrl: API_BASE,
  fetch: noCredsFetch,
});

type Translatable = {
  name: string;
  summary: string | null;
  description?: string | null;
  translations?: ModTranslations | null;
};

/** A registry mod with its own translation for `locale` laid over the English
 *  name/summary/description; any field the author left out stays English. */
export function localizeMod<T extends Translatable>(mod: T, locale: string): T {
  const tr = mod.translations?.[locale];
  if (!tr) return mod;
  return {
    ...mod,
    name: tr.name || mod.name,
    summary: tr.summary || mod.summary,
    description: tr.description || mod.description,
  };
}

// Every registry read the desktop shows goes through these two, so localizing
// here covers browse, detail, updates and the command palette at once.
export const api: typeof client = {
  ...client,
  mods: {
    ...client.mods,
    list: async (...args) => {
      const res = await client.mods.list(...args);
      const loc = modLocale();
      return { ...res, items: res.items.map((m) => localizeMod(m, loc)) };
    },
    get: async (...args) => {
      const res = await client.mods.get(...args);
      return { ...res, mod: localizeMod(res.mod, modLocale()) };
    },
  },
};

export function getApiBaseUrl(): string {
  return API_BASE;
}

/**
 * Turn a failed store/API fetch into a message a user (or bug report)
 * can act on. A bare `TypeError` from `fetch` carries no HTTP status —
 * inside a Tauri WebView that almost always means the request was
 * blocked before it left the app (the API origin is missing from CSP
 * `connect-src` in `tauri.conf.json`) or rejected by the server's CORS
 * policy (this WebView origin is missing from the API's
 * `trustedOrigins`). Spell both out instead of showing "Failed to
 * fetch".
 */
export function describeApiError(err: unknown): string {
  if (err instanceof ApiTimeoutError) {
    return t(
      'The API at {url} did not respond in time. It may be down or your connection is slow.',
      {
        url: API_BASE,
      },
    );
  }
  if (err instanceof ApiError) {
    return t('The API at {url} responded with HTTP {status}. ({message})', {
      url: API_BASE,
      status: err.status,
      message: err.message,
    });
  }
  if (err instanceof TypeError) {
    const origin = typeof window !== 'undefined' ? window.location.origin : '<unknown>';
    // The second half names source files a maintainer greps for, so it stays
    // one message: a translator can move the placeholders, not split the file
    // paths out of it.
    return [
      t('Request to {url} was blocked before reaching the server ({message}).', {
        url: API_BASE,
        message: err.message,
      }),
      t('If you are offline, reconnect and retry. Otherwise this is usually config:'),
      t("the app origin {origin} must be in the API's CORS trustedOrigins (apps/api/src/env.ts),", {
        origin,
      }),
      t('and {url} must be in the CSP connect-src (apps/desktop/src-tauri/tauri.conf.json).', {
        url: API_BASE,
      }),
    ].join(' ');
  }
  return err instanceof Error ? err.message : String(err);
}

/** Console diagnostic for store-fetch failures: one readable line plus the raw error object. */
export function logApiError(scope: string, err: unknown): void {
  console.error(`[${scope}] API request failed: ${describeApiError(err)}`, err);
}
