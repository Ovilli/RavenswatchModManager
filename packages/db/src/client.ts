import { neonConfig, Pool as NeonPool } from '@neondatabase/serverless';
import { drizzle as drizzleNeon } from 'drizzle-orm/neon-serverless';
import { sql } from 'drizzle-orm';
import { drizzle as drizzlePg } from 'drizzle-orm/node-postgres';
import pg from 'pg';
import ws from 'ws';
import * as schema from './schema';

const { Pool: PgPool } = pg;

neonConfig.webSocketConstructor = ws;

export type Db =
  | ReturnType<typeof drizzleNeon<typeof schema>>
  | ReturnType<typeof drizzlePg<typeof schema>>;

interface CachedDb {
  db: Db;
  pool: NeonPool | pg.Pool;
  url: string;
}

let cached: CachedDb | null = null;

function build(url: string): CachedDb {
  const driver = (process.env.DB_DRIVER ?? 'pg').toLowerCase();
  if (driver === 'neon') {
    const pool = new NeonPool({ connectionString: url });
    return { db: drizzleNeon(pool, { schema }), pool, url };
  }
  const pool = new PgPool({ connectionString: url });
  return { db: drizzlePg(pool, { schema }), pool, url };
}

export function getDb(url = process.env.DATABASE_URL): Db {
  if (!url) throw new Error('DATABASE_URL is not set');
  if (cached && cached.url === url) return cached.db;
  // URL changed (test setup, runtime override) — drop the stale pool so
  // it doesn't leak connections.
  if (cached) {
    void cached.pool.end().catch(() => {});
  }
  cached = build(url);
  return cached.db;
}

/** Run `SELECT 1` against the cached pool. Returns true if it answers
 * within `timeoutMs`, false otherwise. */
export async function pingDb(timeoutMs = 5000): Promise<boolean> {
  if (!cached) {
    try {
      getDb();
    } catch {
      return false;
    }
  }
  const c = cached;
  if (!c) return false;
  try {
    await Promise.race([
      c.db.execute(sql`select 1`),
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error('db ping timed out')), timeoutMs),
      ),
    ]);
    return true;
  } catch {
    return false;
  }
}

/** Drop the cached pool. Next `getDb()` builds a fresh one. */
export async function resetDb(): Promise<void> {
  const c = cached;
  cached = null;
  if (c) await c.pool.end().catch(() => {});
}

/** Returns a healthy Db, rebuilding the pool with exponential backoff if
 * the cached one fails its health check. */
export async function getDbHealthy(maxAttempts = 3): Promise<Db> {
  const db = getDb();
  if (await pingDb()) return db;
  for (let i = 0; i < maxAttempts; i++) {
    const delay = 100 * 2 ** i;
    await new Promise((r) => setTimeout(r, delay));
    console.warn(`db health check failed, reconnecting (attempt ${i + 1}/${maxAttempts})`);
    await resetDb();
    const fresh = getDb();
    if (await pingDb()) return fresh;
  }
  throw new Error('database unreachable after retries');
}
