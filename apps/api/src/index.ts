import { serve } from '@hono/node-server';
import { app } from './app';
import { env } from './env';

const port = env.port;
console.log(`rsmm-api listening on http://localhost:${port}`);
serve({ fetch: app.fetch, port });
