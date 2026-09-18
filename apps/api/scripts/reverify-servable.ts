// One-off admin pass: re-hash every servable mod version against its declared
// sha256.
//
// Before d67ebb3 a version could be marked `clean` without anyone comparing the
// stored bytes to the sha256 the uploader declared (and big files were
// URL-scanned unhashed), so a verdict may cover bytes other than the ones being
// served. `/scan` cannot redo this — enqueueScan refuses servable rows on
// purpose — hence a script.
//
//   pnpm --filter api exec tsx scripts/reverify-servable.ts           # report only
//   pnpm --filter api exec tsx scripts/reverify-servable.ts --apply   # hide mismatches
//
// --apply marks a MISMATCHED row `error`: it stops being served, and the scan
// drain's retry fails closed on the same mismatch, so it stays hidden until the
// author re-uploads. An UNREADABLE object is only reported; a network blip must
// not take a mod down.

import { getDb, schema } from '@rsmm/db';
import { eq, inArray } from 'drizzle-orm';
import '../src/env.js';
import { SERVABLE_STATUSES, storedBytesMatchDeclared } from '../src/scan-gate.js';
import { markScan } from '../src/scan-service.js';
import { fetchPublicObject } from '../src/storage.js';

const apply = process.argv.includes('--apply');

async function main(): Promise<number> {
  const db = getDb();
  const rows = await db
    .select({
      id: schema.modVersions.id,
      slug: schema.mods.slug,
      version: schema.modVersions.version,
      sha256: schema.modVersions.sha256,
      status: schema.modVersions.scanStatus,
      assetUrl: schema.modVersions.assetUrl,
    })
    .from(schema.modVersions)
    .innerJoin(schema.mods, eq(schema.modVersions.modId, schema.mods.id))
    .where(inArray(schema.modVersions.scanStatus, [...SERVABLE_STATUSES]));

  let ok = 0;
  const mismatched: string[] = [];
  const unreadable: string[] = [];
  for (const r of rows) {
    const label = `${r.slug}@${r.version} (${r.id}, ${r.status})`;
    // maxBytes 0: stream the hash, never buffer the archive.
    const fetched = r.assetUrl ? await fetchPublicObject(r.assetUrl, 0) : null;
    if (!fetched) {
      unreadable.push(label);
      console.log(`UNREADABLE ${label}`);
      continue;
    }
    if (storedBytesMatchDeclared(fetched.sha256, r.sha256)) {
      ok++;
      continue;
    }
    mismatched.push(label);
    console.log(`MISMATCH   ${label}: declared ${r.sha256}, stored ${fetched.sha256}`);
    if (apply) await markScan(r.id, 'error', r.sha256);
  }

  console.log(
    `\n${rows.length} servable version(s): ${ok} match, ${mismatched.length} mismatched, ` +
      `${unreadable.length} unreadable.` +
      (mismatched.length && !apply ? ' Re-run with --apply to hide the mismatches.' : '') +
      (mismatched.length && apply ? ' Mismatches marked error.' : ''),
  );
  return mismatched.length || unreadable.length ? 1 : 0;
}

main().then(
  (code) => process.exit(code),
  (err) => {
    console.error(err);
    process.exit(2);
  },
);
