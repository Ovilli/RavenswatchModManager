import { config as loadEnv } from 'dotenv';
import { defineConfig } from 'drizzle-kit';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = fileURLToPath(new URL('.', import.meta.url));
const repoRoot = resolve(here, '..', '..');
// Mirror the API's precedence: .env is the committed template, .env.local
// holds the real secrets (DATABASE_URL) and wins. dotenv never overrides an
// already-set key, so load the more-specific files first.
loadEnv({ path: resolve(repoRoot, '.env.local') });
loadEnv({ path: resolve(repoRoot, '.env') });
loadEnv({ path: '.env.local' }); // also pick up a packages/db-local override
loadEnv(); // and a local .env if present

const url = process.env.DATABASE_URL;
if (!url) {
  throw new Error('DATABASE_URL is required (see .env.example)');
}

export default defineConfig({
  schema: './src/schema/index.ts',
  out: './drizzle',
  dialect: 'postgresql',
  dbCredentials: { url },
  strict: true,
  verbose: true,
});
