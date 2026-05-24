import { createApiClient } from '@rsmm/api-client';
import { getApiUrl } from './api-url';

const API_BASE = getApiUrl();

// Don't send cookies on API fetch calls — the Tauri WebView origin 
// (http://tauri.localhost on Windows) must be CORS-whitelisted by the 
// API for credentialed requests. Since the desktop app uses a separate 
// better-auth client for sign-in, the API client only needs public /
// unauthenticated access. Removing credentials avoids the strict CORS
// origin-matching requirement that breaks on Windows when the API's
// TRUSTED_ORIGINS env var doesn't include the Windows WebView origin.
const noCredsFetch: typeof fetch = (input, init) =>
  fetch(input, { ...init, credentials: 'omit' });

export const api = createApiClient({
  baseUrl: API_BASE,
  fetch: noCredsFetch,
});

export function getApiBaseUrl(): string {
  return API_BASE;
}
