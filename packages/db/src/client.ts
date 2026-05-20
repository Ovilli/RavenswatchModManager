import { neonConfig, Pool as NeonPool } from '@neondatabase/serverless';
import { drizzle as drizzleNeon } from 'drizzle-orm/neon-serverless';
import { drizzle as drizzlePg } from 'drizzle-orm/node-postgres';
import pg from 'pg';
import ws from 'ws';
import * as schema from './schema';

const { Pool: PgPool } = pg;

neonConfig.webSocketConstructor = ws;

export type Db =
  | ReturnType<typeof drizzleNeon<typeof schema>>
  | ReturnType<typeof drizzlePg<typeof schema>>;

let cached: Db | null = null;

export function getDb(url = process.env.DATABASE_URL): Db {
  if (cached) return cached;
  if (!url) throw new Error('DATABASE_URL is not set');

  const driver = (process.env.DB_DRIVER ?? 'pg').toLowerCase();
  if (driver === 'neon') {
    const pool = new NeonPool({ connectionString: url });
    cached = drizzleNeon(pool, { schema });
  } else {
    const pool = new PgPool({ connectionString: url });
    cached = drizzlePg(pool, { schema });
  }
  return cached;
}

export const db = new Proxy({} as Db, {
  get(_target, prop) {
    return (getDb() as unknown as Record<string | symbol, unknown>)[prop];
  },
});
