import '@rsmm/ui/styles.css';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createRouter } from '@tanstack/react-router';
import { isTauri } from '@tauri-apps/api/core';
import { getCurrent as getCurrentDeepLink, onOpenUrl } from '@tauri-apps/plugin-deep-link';
import { Component, type ErrorInfo, type ReactNode, StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { OverlayHud } from './components/overlay-hud';
import { RouteErrorComponent } from './components/route-error';
import { applyAppearance } from './lib/appearance';
import { authClient } from './lib/auth-client';
import { reportDesktopAuthFailure } from './lib/desktop-auth';
import { wireGlobalErrorHandlers } from './lib/telemetry';
import { routeTree } from './routeTree.gen';
import { useApp } from './store';

wireGlobalErrorHandlers();

// Typeface + UI scale live on <html>, so they must be written before the
// first paint — a React effect would flash the default face on every start.
// The store rehydrates from localStorage synchronously, so getState() here
// already carries the user's saved choice.
applyAppearance(useApp.getState().settings);
// Re-apply on ANY settings change, rather than diffing the appearance fields
// by name. The named list was `fontFamily`/`fontScale`/`density`, so the
// animation toggle added later did nothing until the next launch — a setting
// that silently needs a restart reads as a broken setting. `updateSettings`
// replaces the settings object wholesale, so this identity check catches every
// edit, and `applyAppearance` is a handful of idempotent style writes.
useApp.subscribe((state, prev) => {
  if (state.settings !== prev.settings) applyAppearance(state.settings);
});

// Handle the desktop OAuth relay deep link: rsmm://desktop-auth?token=…
// The system browser drove the whole OAuth flow and minted a one-time token;
// exchange it here for this client's session cookie (see apps/api desktop-auth
// relay). Only meaningful inside the Tauri shell.
async function handleAuthDeepLink(urls: string[] | null) {
  const raw = urls?.[0];
  if (!raw) return;
  let token: string | null = null;
  try {
    const url = new URL(raw);
    // rsmm://desktop-auth?token=…  → host is "desktop-auth"
    if (url.host !== 'desktop-auth' && !url.pathname.includes('desktop-auth')) return;
    // Login-CSRF guard: only accept tokens from a flow THIS install started.
    // signin.tsx minted the nonce and the relay echoed it back; a deep link
    // someone else crafted (their own OAuth flow → their token) won't match.
    const expected = localStorage.getItem('rsmm.desktopAuthNonce');
    if (!expected || url.searchParams.get('app') !== expected) {
      console.error('[oauth] deep link rejected: app nonce missing or mismatched');
      reportDesktopAuthFailure(
        'That sign-in link did not match a sign-in started by this app. Please try again.',
      );
      return;
    }
    localStorage.removeItem('rsmm.desktopAuthNonce'); // single-use
    token = url.searchParams.get('token');
  } catch {
    return;
  }
  if (!token) {
    reportDesktopAuthFailure('The sign-in link was incomplete. Please try again.');
    return;
  }
  try {
    const res = await authClient.$fetch('/one-time-token/verify', {
      method: 'POST',
      body: { token },
    });
    if (res.error) throw new Error(res.error.message ?? 'token verification failed');
    // The session cookie is now set for this client; refresh the cached session
    // before routing so guarded views see the signed-in state.
    await authClient.getSession({ query: { disableCookieCache: true } });
    window.location.href = '/';
  } catch (error) {
    console.error('[oauth] desktop deep-link auth failed', error);
    reportDesktopAuthFailure(
      'Sign-in could not be completed — the sign-in link may have expired or already been used. Please try again.',
    );
  }
}

// An overlay is a SECOND window of this same bundle, told apart by a query
// parameter rather than a route: the packaged app serves static files, so a
// deep path like /overlay has no SPA fallback to land on. It also has to skip
// everything below (router, auth, deep links) — it is a HUD, not the app.
// `mod` says WHICH mod's overlay to draw; overlays are declared by mods, so
// the client never hardcodes one.
const OVERLAY_PARAMS = new URLSearchParams(window.location.search);
const IS_OVERLAY_WINDOW = OVERLAY_PARAMS.get('window') === 'overlay';
const OVERLAY_MOD_ID = OVERLAY_PARAMS.get('mod') ?? '';

if (isTauri() && !IS_OVERLAY_WINDOW) {
  // The overlay un-pin hotkey lives on the main window: overlays come and go,
  // and a click-through one cannot receive the click that would undo it.
  void import('./lib/overlay-hotkey').then((m) => m.registerUnpinShortcut());
  // Cold start: the app may have been launched by the deep link.
  getCurrentDeepLink()
    .then(handleAuthDeepLink)
    .catch(() => {});
  // Warm: the single-instance plugin forwards the URL to the running window.
  onOpenUrl(handleAuthDeepLink);
}

class RootErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  override state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Root render error:', error, info.componentStack);
  }

  override render() {
    if (this.state.error) {
      return (
        <div className="flex h-screen w-screen items-center justify-center bg-pitch p-8">
          <div className="max-w-md text-center space-y-4">
            <h1 className="font-fraktur text-3xl text-crimson">Something went wrong</h1>
            <pre className="font-mono text-sm text-ash whitespace-pre-wrap break-all">
              {this.state.error.message}
            </pre>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="border border-crimson px-4 py-2 text-parchment hover:bg-crimson/20"
            >
              Reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 30_000 },
  },
});

const router = createRouter({
  routeTree,
  context: { queryClient },
  // Per-route error isolation: a crash in one route renders inside that
  // route's outlet (shell/nav survive) rather than tripping the root
  // boundary and white-screening the whole app.
  defaultErrorComponent: RouteErrorComponent,
});

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}

const root = document.getElementById('root');
if (!root) throw new Error('missing #root');

createRoot(root).render(
  <StrictMode>
    <RootErrorBoundary>
      {IS_OVERLAY_WINDOW ? (
        <OverlayHud modId={OVERLAY_MOD_ID} />
      ) : (
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      )}
    </RootErrorBoundary>
  </StrictMode>,
);
