import { getApiUrl } from '../../../lib/api-url';

// SSR-safe API base. Plain `process.env.NEXT_PUBLIC_API_URL` is unreliable
// here: the Vercel build historically baked in a localhost value, which made
// server-side metadata fetches hit the developer's machine and silently fall
// back to generic OG tags. getApiUrl() ignores a localhost env on the server.
export const apiUrl = getApiUrl();
