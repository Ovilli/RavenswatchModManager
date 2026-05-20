import { serve } from '@hono/node-server';
import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { logger } from 'hono/logger';
import { auth } from './auth';
import { env } from './env';
import { modsRouter } from './routes/mods';
import { telemetryRouter } from './routes/telemetry';
import type { AppEnv } from './types';

const app = new Hono<AppEnv>();

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
  const session = await auth.api.getSession({ headers: c.req.raw.headers });
  c.set('user', session?.user ?? null);
  c.set('session', session?.session ?? null);
  await next();
});

app.on(['GET', 'POST'], '/api/auth/*', (c) => auth.handler(c.req.raw));

app.get('/', (c) => c.json({ name: 'rsmm-api', ok: true }));
app.get('/health', (c) => c.json({ ok: true, ts: Date.now() }));

app.route('/mods', modsRouter);
app.route('/telemetry', telemetryRouter);

const port = env.port;
console.log(`rsmm-api listening on http://localhost:${port}`);
serve({ fetch: app.fetch, port });
