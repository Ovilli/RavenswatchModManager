/**
 * Apply migration 0004 (featured + reviews + collections) to prod Neon.
 *
 * Run:
 *   DATABASE_URL='<neon-prod-url>' npx tsx scripts/migrate-0004.ts
 *
 * The drizzle migrations tracking table (`__drizzle_migrations`) was
 * never bootstrapped in prod, so `drizzle-kit migrate` would try to
 * re-apply 0001-0003. This script runs only the 0004 statements idempotently
 * via raw SQL.
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
  '0004_add_featured_reviews_collections.sql',
);

const url = process.env.DATABASE_URL;
if (!url) {
  console.error('DATABASE_URL is required');
  process.exit(1);
}

const raw = readFileSync(sqlPath, 'utf8');
// drizzle uses `--> statement-breakpoint` between statements.
const statements = raw
  .split('--> statement-breakpoint')
  .map((s) => s.trim())
  .filter(Boolean);

// Wrap each create/alter so re-runs are safe.
const idempotent = statements.map((s) => {
  // ALTER TABLE "mods" ADD COLUMN "featured" ...  → ADD COLUMN IF NOT EXISTS
  if (/ALTER TABLE .* ADD COLUMN /i.test(s) && !/IF NOT EXISTS/i.test(s)) {
    return s.replace(/ADD COLUMN /i, 'ADD COLUMN IF NOT EXISTS ');
  }
  // CREATE TABLE "x" (... → CREATE TABLE IF NOT EXISTS
  if (/^CREATE TABLE "/i.test(s)) {
    return s.replace(/^CREATE TABLE /i, 'CREATE TABLE IF NOT EXISTS ');
  }
  // CREATE INDEX → CREATE INDEX IF NOT EXISTS
  if (/^CREATE INDEX /i.test(s)) {
    return s.replace(/^CREATE INDEX /i, 'CREATE INDEX IF NOT EXISTS ');
  }
  if (/^CREATE UNIQUE INDEX /i.test(s)) {
    return s.replace(/^CREATE UNIQUE INDEX /i, 'CREATE UNIQUE INDEX IF NOT EXISTS ');
  }
  // ALTER TABLE ... ADD CONSTRAINT — wrap in a DO block that skips if exists.
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
