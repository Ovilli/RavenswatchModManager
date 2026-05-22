import { config as loadEnv } from 'dotenv';
import { migrate as migrateNeon } from 'drizzle-orm/neon-serverless/migrator';
import { migrate as migratePg } from 'drizzle-orm/node-postgres/migrator';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { getDb } from './client';

const here = fileURLToPath(new URL('.', import.meta.url));
const repoRoot = resolve(here, '..', '..', '..');
loadEnv({ path: resolve(repoRoot, '.env.local') });
loadEnv({ path: resolve(repoRoot, '.env') });
loadEnv({ path: '.env.local' });
loadEnv();

async function main() {
  const driver = (process.env.DB_DRIVER ?? 'pg').toLowerCase();
  const db = getDb();
  const opts = { migrationsFolder: './drizzle' } as const;
  if (driver === 'neon') {
    // biome-ignore lint/suspicious/noExplicitAny: dual-driver glue
    await migrateNeon(db as any, opts);
  } else {
    // biome-ignore lint/suspicious/noExplicitAny: dual-driver glue
    await migratePg(db as any, opts);
  }
  console.log('migrations applied');
  process.exit(0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
