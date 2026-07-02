/**
 * Grandfather all non-servable (pending/queued/error) mod_versions to
 * 'skipped' so they pass the fail-closed serve gate and become downloadable.
 * These predate a working scan pipeline (finalize never ran / VT returned an
 * incomplete verdict). 'skipped' is the same status the API assigns when
 * VirusTotal is unconfigured (mods.ts). Idempotent; prints before/after.
 *
 * Does NOT touch 'flagged' rows (genuine positive detections stay hidden).
 *
 * Run:
 *   DATABASE_URL='<neon-prod-url>' npx tsx scripts/grandfather-scan-skipped.ts
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
    const before = await client.query(
      `select m.slug, v.version, v.scan_status
         from mod_versions v join mods m on m.id = v.mod_id
        where v.scan_status in ('pending','queued','error')
        order by v.created_at`,
    );
    console.log(`About to grandfather ${before.rows.length} version(s) to 'skipped':`);
    console.table(before.rows);

    const res = await client.query(
      `update mod_versions
          set scan_status = 'skipped', scanned_at = now()
        where scan_status in ('pending','queued','error')`,
    );
    console.log(`\n✓ updated ${res.rowCount} row(s)`);

    const after = await client.query(
      `select scan_status, count(*)::int as n from mod_versions group by scan_status`,
    );
    console.table(after.rows);
  } finally {
    client.release();
    await pool.end();
  }
}

run().catch((err) => {
  console.error('grandfather failed:', err);
  process.exit(1);
});
