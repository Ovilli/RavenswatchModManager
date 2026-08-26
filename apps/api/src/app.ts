import { getDb, schema } from '@rsmm/db';
import { eq } from 'drizzle-orm';
import { Hono } from 'hono';
import { bodyLimit } from 'hono/body-limit';
import { cors } from 'hono/cors';
import { logger } from 'hono/logger';
import { auth } from './auth.js';
import { env, githubConfigured, googleConfigured, isProduction } from './env.js';
import { errString, log, requestId } from './logger.js';
import { createRateLimiter } from './rate-limit.js';
import { collectionsRouter } from './routes/collections.js';
import { cronRouter } from './routes/cron.js';
import { desktopAuthRouter } from './routes/desktop-auth.js';
import { guidesRouter } from './routes/guides.js';
import { legalRouter } from './routes/legal.js';
import { meRouter } from './routes/me.js';
import { moderationRouter } from './routes/moderation.js';
import { modsRouter } from './routes/mods.js';
import { telemetryRouter } from './routes/telemetry.js';
import { usersRouter } from './routes/users.js';
import type { AppEnv } from './types.js';

export const app = new Hono<AppEnv>();

app.use('*', requestId);
app.use('*', logger());
app.use(
  '*',
  cors({
    origin: env.trustedOrigins,
    credentials: true,
    allowMethods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
  }),
);

app.use('*', async (c, next) => {
  c.header('X-Content-Type-Options', 'nosniff');
  c.header('X-Frame-Options', 'DENY');
  c.header('Referrer-Policy', 'strict-origin-when-cross-origin');
  c.header('X-XSS-Protection', '0');
  c.header('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
  // This API answers JSON to a browser and to the desktop app; it never serves
  // a document that should be framed, embedded, or allowed to reach a device
  // API. The CSP is the belt to X-Frame-Options' braces and also neutralises
  // any error page or third-party HTML that might otherwise render inline.
  c.header(
    'Content-Security-Policy',
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
  );
  c.header('Cross-Origin-Resource-Policy', 'same-site');
  c.header('Permissions-Policy', 'camera=(), microphone=(), geolocation=(), interest-cohort=()');
  await next();
});

/**
 * Hard cap on request bodies.
 *
 * Every write endpoint here takes a small JSON document — mod archives and
 * images go straight to object storage through a presigned PUT and never pass
 * through the API at all. The platform's own limit is 100 MB, so without this
 * any signed-in account could make the function buffer and JSON-parse 100 MB
 * per request. The largest legitimate body is a guide (100 000 chars of body
 * plus metadata), which stays comfortably under 1 MB even fully multi-byte.
 */
app.use(
  '*',
  bodyLimit({
    maxSize: 1024 * 1024,
    onError: (c) => c.json({ error: 'request body too large' }, 413),
  }),
);

/**
 * Global rate-limit backstop.
 *
 * The tuned per-endpoint limiters (auth, upload, report, review, download…)
 * stay authoritative; this only catches the endpoints that had none at all —
 * the public browse/detail/profile reads, which are the cheapest thing to
 * scrape and the most expensive to serve, since each one fans out into several
 * correlated aggregate subqueries. 600/min per IP is far above any real
 * session (a registry page load is a handful of calls) and still turns an
 * unbounded scrape into a bounded one.
 */
app.use('/api/*', createRateLimiter({ name: 'global', windowMs: 60_000, maxHits: 600 }));

app.onError((err, c) => {
  (c.get('log') ?? log).error('unhandled error', { err: errString(err), stack: err.stack });
  return c.json({ error: 'internal server error' }, 500);
});

app.notFound((c) => c.json({ error: 'not found' }, 404));

app.use('*', async (c, next) => {
  const session = await auth.api.getSession({ headers: c.req.raw.headers }).catch(() => null);
  let user = session?.user ?? null;
  c.set('bannedInfo', null);
  // Ban gate: a banned user is treated as anonymous everywhere (can't publish,
  // review, or moderate). Checked against the DB so a ban takes effect on the
  // banned user's very next request without waiting for their session to
  // expire. Only costs a query when a session is actually present. The ban is
  // stashed on the context (bannedInfo) so GET /api/session can tell the still
  // -cookie'd frontend to show a ban notice instead of a silent dead state.
  if (user) {
    const row = await getDb()
      .select({ banned: schema.users.banned, reason: schema.users.bannedReason })
      .from(schema.users)
      .where(eq(schema.users.id, user.id))
      .limit(1)
      .then((r) => r[0] ?? null)
      .catch(() => null);
    if (row?.banned) {
      c.set('bannedInfo', { banned: true, reason: row.reason ?? null });
      user = null;
    }
  }
  const isVerified = user?.emailVerified === true;
  c.set('user', isProduction && user && !isVerified ? null : user);
  c.set('session', isProduction && user && !isVerified ? null : (session?.session ?? null));
  await next();
});

// OAuth callback diagnostics. Records only whether the browser presented a
// state cookie, never the value: the `state` param and the `better-auth.state`
// cookie ARE the CSRF token for the flow, and the verification row they key is
// still live and single-use when the callback runs. Logging either put a
// replayable credential into the log pipeline (and into every downstream log
// aggregator) for the sake of debugging a cookie-presence question that the
// boolean answers on its own.
app.use('/api/auth/callback/*', async (c, next) => {
  const cookie = c.req.header('cookie') ?? '';
  const hasStateCookie = /(?:^|;\s*)(?:__Secure-)?better-auth\.state=/.test(cookie);
  (c.get('log') ?? log).info('oauth callback', {
    path: c.req.path,
    hasStateParam: Boolean(c.req.query('state')),
    hasStateCookie,
  });
  await next();
});

app.use('/api/auth/*', createRateLimiter({ name: 'auth', windowMs: 60_000, maxHits: 10 }));
app.on(['GET', 'POST'], '/api/auth/*', (c) => auth.handler(c.req.raw));

// Desktop OAuth relay (browser-side flow → one-time-token handoff). Rate-limited
// like /api/auth to blunt abuse of the provider-redirect kickoff.
app.use(
  '/api/desktop-auth/*',
  createRateLimiter({ name: 'desktop-auth', windowMs: 60_000, maxHits: 20 }),
);
app.route('/api/desktop-auth', desktopAuthRouter);

app.use(
  '/api/mods/upload',
  createRateLimiter({
    name: 'mod-upload',
    windowMs: 3_600_000,
    maxHits: 5,
    keyFrom: (c) => {
      const user = c.get('user');
      return (
        user?.id ??
        c.req.header('x-real-ip') ??
        c.req.header('x-forwarded-for')?.split(',').pop()?.trim() ??
        'anon'
      );
    },
  }),
);

app.get('/api', (c) => c.json({ name: 'rsmm-api', ok: true }));
app.get('/api/health', (c) => c.json({ ok: true, ts: Date.now() }));

// Session status probe the web app polls to detect a ban. The Better Auth
// cookie stays valid after a ban (auth.handler bypasses the ban gate), so the
// client would otherwise look signed-in while every API call 401s. This lets
// the UI show an explicit ban notice + sign-out instead of a silent dead state.
app.get('/api/session', (c) => {
  const b = c.get('bannedInfo');
  return c.json({ banned: b?.banned ?? false, reason: b?.reason ?? null });
});

// Tells the sign-in UI which providers to render. Avoids the frontend
// hard-coding a list and showing buttons that 500 when an admin hasn't
// set the OAuth env vars yet.
app.get('/api/auth-config', (c) =>
  c.json({
    providers: {
      google: googleConfigured(),
      github: githubConfigured(),
    },
  }),
);

// Scheduled scan-queue drain (Vercel Cron → Bearer CRON_SECRET). Self-gates on
// the secret; no session/cookie involved.
app.route('/api/cron', cronRouter);

app.route('/api/mods', modsRouter);
app.route('/api/moderation', moderationRouter);
app.route('/api/me', meRouter);
app.route('/api/users', usersRouter);
app.route('/api/collections', collectionsRouter);
app.route('/api/guides', guidesRouter);
app.route('/api/telemetry', telemetryRouter);
app.route('/api/legal', legalRouter);
