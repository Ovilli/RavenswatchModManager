import { TanStackRouterVite } from '@tanstack/router-plugin/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// Tauri prefers fixed port; HMR over ws.
const host = process.env.TAURI_DEV_HOST;

// Where the dev server proxies `/api` + `/api/auth` to. Defaults to the
// production deploy so contributors don't need a local `apps/api`
// instance running. Override with `VITE_DEV_API_PROXY` to point at a
// local backend (e.g. `http://localhost:3001`).
const DEV_API_PROXY = process.env.VITE_DEV_API_PROXY || 'https://api.ravenswatch.ovilli.de';

export default defineConfig({
  plugins: [TanStackRouterVite(), react()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host
      ? { protocol: 'ws', host, port: 1421 }
      : undefined,
    watch: { ignored: ['**/src-tauri/**'] },
    // Same-origin proxy. The deployed API's `TRUSTED_ORIGINS` doesn't
    // include `http://localhost:1420`, so a direct cross-origin fetch
    // gets rejected even though the request reaches Vercel. Proxying
    // through Vite makes the browser see the API as same-origin and
    // sidesteps CORS entirely. Production Tauri builds talk to the
    // real API directly — Tauri origins (`tauri://localhost` /
    // `https://tauri.localhost`) ARE whitelisted server-side.
    proxy: {
      '/api': {
        target: DEV_API_PROXY,
        changeOrigin: true,
        secure: true,
        // Rewrite Set-Cookie `Domain=...` so session cookies bind to
        // `localhost` (the browser's origin) instead of the upstream
        // API domain. Without this the cookie is silently dropped and
        // every request looks unauthenticated after sign-in.
        cookieDomainRewrite: '',
        // `changeOrigin: true` rewrites the `Host` header but leaves the
        // `Origin` header alone, so better-auth still sees
        // `Origin: http://localhost:1420` and rejects the request with
        // a 403 (origin not in `trustedOrigins`). Rewrite Origin + Referer
        // to the target so the API treats the proxied call as same-origin.
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            try {
              const target = new URL(DEV_API_PROXY);
              proxyReq.setHeader('origin', target.origin);
              proxyReq.setHeader('referer', `${target.origin}/`);
            } catch {
              // DEV_API_PROXY isn't a valid URL — surface via the proxy's
              // own error path so the request fails loudly.
            }
            // Outgoing direction: the browser stored the session cookie
            // under the *unprefixed* name (see `proxyRes` below). Restore
            // the `__Secure-` prefix on the way out so better-auth's
            // session lookup finds it.
            const cookie = req.headers.cookie;
            if (cookie) {
              proxyReq.setHeader(
                'cookie',
                cookie.replace(/(^|;\s*)better-auth\./g, '$1__Secure-better-auth.'),
              );
            }
          });
          // Incoming direction: better-auth issues session cookies named
          // `__Secure-better-auth.session_token` over HTTPS. The
          // `__Secure-` prefix is a hard browser rule that requires the
          // Set-Cookie response itself to come over HTTPS — the Vite dev
          // server is plain http://localhost:1420, so the browser will
          // silently drop the cookie and the user appears logged out
          // immediately after a successful login.
          //
          // Strip the prefix *and* the `Secure` attribute so the browser
          // accepts the cookie under the unprefixed name. The matching
          // `proxyReq` handler re-adds the prefix when forwarding the
          // cookie back to the API, so the round-trip is invisible to
          // better-auth.
          proxy.on('proxyRes', (proxyRes) => {
            const setCookie = proxyRes.headers['set-cookie'];
            if (Array.isArray(setCookie)) {
              proxyRes.headers['set-cookie'] = setCookie.map((c) =>
                c.replace(/^__Secure-/i, '').replace(/;\s*Secure/gi, ''),
              );
            }
          });
        },
      },
    },
  },
  envPrefix: ['VITE_', 'TAURI_ENV_'],
});
