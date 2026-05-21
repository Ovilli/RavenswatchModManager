import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { logger } from 'hono/logger';
import { auth } from './auth';
import { env } from './env';
import { createRateLimiter } from './rate-limit';
import { modsRouter } from './routes/mods';
import { telemetryRouter } from './routes/telemetry';
import type { AppEnv } from './types';

export const app = new Hono<AppEnv>();

app.use('*', logger());
app.use(
  '*',
  cors({
    origin: env.trustedOrigins,
    credentials: true,
    allowMethods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
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
  console.error('Unhandled error:', err);
  return c.json({ error: 'internal server error' }, 500);
});

app.notFound((c) => c.json({ error: 'not found' }, 404));

app.use('*', async (c, next) => {
  const session = await auth.api.getSession({ headers: c.req.raw.headers }).catch(() => null);
  c.set('user', session?.user ?? null);
  c.set('session', session?.session ?? null);
  await next();
});

app.use('/api/auth/*', createRateLimiter({ windowMs: 60_000, maxHits: 10 }));
app.on(['GET', 'POST'], '/api/auth/*', (c) => auth.handler(c.req.raw));

app.use('/api/mods/upload', createRateLimiter({
  windowMs: 3_600_000,
  maxHits: 5,
  keyFrom: (c) => {
    const user = c.get('user');
    return user?.id ?? c.req.header('x-forwarded-for')?.split(',')[0]?.trim() ?? 'anon';
  },
}));

app.get('/api', (c) => c.json({ name: 'rsmm-api', ok: true }));
app.get('/api/health', (c) => c.json({ ok: true, ts: Date.now() }));

app.route('/api/mods', modsRouter);
app.route('/api/telemetry', telemetryRouter);
