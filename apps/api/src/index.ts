import { serve } from '@hono/node-server';
import { pingDb } from '@rsmm/db';
import { app } from './app.js';
import { env } from './env.js';
import { errString, log } from './logger.js';
import { startScanWorker } from './scan-worker.js';

const port = env.port;

async function main() {
  const ok = await pingDb();
  if (!ok) {
    const sanitizedUrl = env.databaseUrl.replace(/:\/\/[^@]+@/, '://<redacted>@');
    log.error('database unreachable; check connection and .env / .env.local', {
      url: sanitizedUrl,
    });
    process.exit(1);
  }
  log.info(`rsmm-api listening on http://localhost:${port}`, { port });
  try {
    serve({ fetch: app.fetch, port });
    // Long-running servers (local dev, self-hosting) drain the scan queue on a
    // timer. On Vercel every instance ran that timer — two DB queries a minute
    // per warm instance, keeping Neon awake — while the queue is already driven
    // by the publish/scan-status kicks and the 10-minute GitHub Actions drain.
    if (!process.env.VERCEL) startScanWorker();
  } catch (err) {
    log.error('failed to start server', { port, err: errString(err) });
    process.exit(1);
  }
}

main().catch((err) => {
  log.error('fatal startup error', { err: errString(err) });
  process.exit(1);
});
