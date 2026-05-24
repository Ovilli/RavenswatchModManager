/**
 * Apply migration 0005 (collections description/image_url/screenshots + collection_reviews) to prod Neon.
 *
 * The drizzle migrations tracking table (`__drizzle_migrations`) was
 * never bootstrapped in prod, so `drizzle-kit migrate` would try to
 * re-apply 0001-0004. This script runs only the 0005 statements idempotently
 * via raw SQL, mirroring migrate-0004.ts.
 *
 * Run:
 *   DATABASE_URL='<neon-prod-url>' npx tsx scripts/migrate-0005.ts
 */
import { Pool, neonConfig } from '@neondatabase/serverless';
import ws from 'ws';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const sqlPath = resolve(
  here,
  '..',
  'packages',
  'db',
  'drizzle',
  '0005_blue_havok.sql',
);

const url = process.env.DATABASE_URL;
if (!url) {
  console.error('DATABASE_URL is required');
  process.exit(1);
}

const raw = readFileSync(sqlPath, 'utf8');
const statements = raw
  .split('--> statement-breakpoint')
  .map((s) => s.trim())
  .filter(Boolean);

const idempotent = statements.map((s) => {
  if (/ALTER TABLE .* ADD COLUMN /i.test(s) && !/IF NOT EXISTS/i.test(s)) {
    return s.replace(/ADD COLUMN /i, 'ADD COLUMN IF NOT EXISTS ');
  }
  if (/^CREATE TABLE "/i.test(s)) {
    return s.replace(/^CREATE TABLE /i, 'CREATE TABLE IF NOT EXISTS ');
  }
  if (/^CREATE INDEX /i.test(s)) {
    return s.replace(/^CREATE INDEX /i, 'CREATE INDEX IF NOT EXISTS ');
  }
  if (/^CREATE UNIQUE INDEX /i.test(s)) {
    return s.replace(/^CREATE UNIQUE INDEX /i, 'CREATE UNIQUE INDEX IF NOT EXISTS ');
  }
  const fkMatch = /ALTER TABLE "(\w+)" ADD CONSTRAINT "(\w+)"/i.exec(s);
  if (fkMatch) {
    const [, table, name] = fkMatch;
    return `DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '${name}') THEN
    ${s.replace(/;\s*$/, '')};
  END IF;
END $$;`;
  }
  return s;
});

neonConfig.webSocketConstructor = ws;
const pool = new Pool({ connectionString: url });

async function run() {
  const client = await pool.connect();
  try {
    for (const s of idempotent) {
      console.log('▶', s.split('\n')[0]?.slice(0, 80));
      await client.query(s);
    }
    console.log(`✓ applied ${idempotent.length} statements`);
  } finally {
    client.release();
    await pool.end();
  }
}

run().catch((err) => {
  console.error('migration failed:', err);
  process.exit(1);
});
