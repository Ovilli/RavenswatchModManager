import { serve } from '@hono/node-server';
import { pingDb } from '@rsmm/db';
import { app } from './app';
import { env } from './env';

const port = env.port;

async function main() {
  const ok = await pingDb();
  if (!ok) {
    const sanitizedUrl = env.databaseUrl.replace(/:\/\/[^@]+@/, '://<redacted>@');
    console.error(
      `Database is unreachable at ${sanitizedUrl}. Check your connection and .env / .env.local configuration.`,
    );
    process.exit(1);
  }
  console.log(`rsmm-api listening on http://localhost:${port}`);
  try {
    serve({ fetch: app.fetch, port });
  } catch (err) {
    console.error(`Failed to start server on port ${port}:`, err);
    process.exit(1);
  }
}

main().catch((err) => {
  console.error('Fatal startup error:', err);
  process.exit(1);
});
