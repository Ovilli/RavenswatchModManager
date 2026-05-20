import { config as loadEnv } from 'dotenv';
import { defineConfig } from 'drizzle-kit';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = fileURLToPath(new URL('.', import.meta.url));
// repo-root .env (packages/db -> repo root = ../../)
loadEnv({ path: resolve(here, '..', '..', '.env') });
loadEnv(); // also pick up local .env if present

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
