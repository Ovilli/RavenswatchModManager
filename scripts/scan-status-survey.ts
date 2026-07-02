/**
 * READ-ONLY survey of mod_versions scan status vs age. Helps decide which
 * pre-scan-system versions need grandfathering to 'skipped'. No writes.
 *
 * Run:
 *   DATABASE_URL='<neon-prod-url>' npx tsx scripts/scan-status-survey.ts
 */
import { Pool, neonConfig } from '@neondatabase/serverless';
import ws from 'ws';

const url = process.env.DATABASE_URL;
if (!url) {
  console.error('DATABASE_URL is required');
  process.exit(1);
}

neonConfig.webSocketConstructor = ws;
const pool = new Pool({ connectionString: url });

async function run() {
  const client = await pool.connect();
  try {
    const byStatus = await client.query(
      `select scan_status, count(*)::int as n,
              min(created_at) as oldest, max(created_at) as newest
         from mod_versions
        group by scan_status
        order by n desc`,
    );
    console.log('=== mod_versions by scan_status ===');
    console.table(byStatus.rows);

    const stuck = await client.query(
      `select v.id, m.slug, v.version, v.scan_status, v.created_at, v.scanned_at,
              v.size_bytes
         from mod_versions v
         join mods m on m.id = v.mod_id
        where v.scan_status not in ('clean','skipped')
        order by v.created_at asc`,
    );
    console.log(`\n=== ${stuck.rows.length} NON-servable versions ===`);
    console.table(stuck.rows);

    const modsNoServable = await client.query(
      `select m.slug, m.featured, m.takedown_status,
              count(v.id)::int as versions,
              count(*) filter (where v.scan_status in ('clean','skipped'))::int as servable
         from mods m
         left join mod_versions v on v.mod_id = m.id
        group by m.id
       having count(*) filter (where v.scan_status in ('clean','skipped')) = 0
        order by m.featured desc, m.slug`,
    );
    console.log(`\n=== ${modsNoServable.rows.length} mods with ZERO servable versions ===`);
    console.table(modsNoServable.rows);
  } finally {
    client.release();
    await pool.end();
  }
}

run().catch((err) => {
  console.error('survey failed:', err);
  process.exit(1);
});
