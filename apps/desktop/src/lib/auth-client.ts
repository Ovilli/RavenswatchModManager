import { oneTimeTokenClient } from 'better-auth/client/plugins';
import { createAuthClient } from 'better-auth/react';
import { getApiUrl } from './api-url';

export const authClient = createAuthClient({
  baseURL: getApiUrl(),
  // Backs the desktop OAuth relay: the deep-link handler exchanges the
  // one-time token minted by the browser flow for this client's session.
  plugins: [oneTimeTokenClient()],
  fetchOptions: {
    credentials: 'include',
  },
  // Cache session in storage after get-session. Helps Tauri on Linux
  // where WebKit may not persist third-party API cookies under tauri://.
  session: {
    cookieCache: {
      enabled: true,
      maxAge: 60 * 60 * 24,
    },
  },
});

export const { signIn, signUp, signOut, useSession } = authClient;
