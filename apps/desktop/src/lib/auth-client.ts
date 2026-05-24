import { createAuthClient } from 'better-auth/react';
import { getApiUrl } from './api-url';

export const authClient = createAuthClient({
  baseURL: getApiUrl(),
  fetchOptions: {
    credentials: 'include',
  },
  // Cache session in storage after get-session. Helps Tauri on macOS/Linux
  // where WebKit may not persist third-party API cookies under tauri://.
  session: {
    cookieCache: {
      enabled: true,
      maxAge: 60 * 60 * 24,
    },
  },
});

export const { signIn, signUp, signOut, useSession } = authClient;
