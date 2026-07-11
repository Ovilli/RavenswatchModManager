import { getDb, schema } from '@rsmm/db';
import { eq } from 'drizzle-orm';
import { Hono } from 'hono';
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
  await next();
});

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

// TEMP diagnostic: log what actually reaches the OAuth callback so we can see
// whether the browser sent the state cookie and whether it matches the state
// query param (state_mismatch debugging). Remove once desktop OAuth is verified.
app.use('/api/auth/callback/*', async (c, next) => {
  const cookie = c.req.header('cookie') ?? '';
  const cookieNames = cookie
    .split(';')
    .map((s) => s.trim().split('=')[0])
    .filter(Boolean);
  const stateCookie = cookie.match(/(?:^|;\s*)(?:__Secure-)?better-auth\.state=([^;.]+)/);
  (c.get('log') ?? log).info('[oauth-debug] callback', {
    path: c.req.path,
    stateParam: c.req.query('state') ?? null,
    stateCookieValue: stateCookie?.[1] ?? null,
    hasStateCookie: Boolean(stateCookie),
    cookieNames: cookieNames.join(','),
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
