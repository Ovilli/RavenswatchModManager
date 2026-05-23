/**
 * Wipe every mod whose slug *isn't* listed as kept.
 *
 * Run after the index API has been live + real users have published —
 * cleans out the mock seed rows (`speed-runner`, `witchfire-fx`, etc.)
 * that `seed.ts` planted before real uploads existed.
 *
 * `mod_versions` rows are removed via the schema's
 * `onDelete: 'cascade'` foreign key, no extra deletes needed.
 *
 * Usage:
 *
 *   pnpm --filter @rsmm/db exec tsx src/wipe-seed.ts
 *
 * To keep additional slugs, pass them on the command line:
 *
 *   pnpm --filter @rsmm/db exec tsx src/wipe-seed.ts examplemagicitem foo bar
 *
 * Default keep-list is the two slugs the project has actually uploaded
 * to the live index so far.
 */

import { inArray, notInArray } from 'drizzle-orm';
import { getDb } from './client';
import { mods } from './schema/mods';

const DEFAULT_KEEP = ['examplemagicitem', 'examplerawassets'];

async function main() {
  const cliKeep = process.argv.slice(2).filter((s) => s.length > 0);
  const keep = cliKeep.length ? cliKeep : DEFAULT_KEEP;
  const db = getDb();

  const before = await db.select({ slug: mods.slug }).from(mods);
  console.log(`before: ${before.length} mod row(s)`);

  // Surface what we're about to delete so it's reviewable in the log.
  const willDelete = before.filter((m) => !keep.includes(m.slug)).map((m) => m.slug);
  if (!willDelete.length) {
    console.log('nothing to delete — keep-list already matches the table.');
    return;
  }
  console.log(`keeping: ${keep.join(', ')}`);
  console.log(`deleting: ${willDelete.join(', ')}`);

  const deleted = await db
    .delete(mods)
    .where(notInArray(mods.slug, keep))
    .returning({ slug: mods.slug });
  console.log(`deleted ${deleted.length} mod row(s) (cascade nukes mod_versions + downloads).`);

  const after = await db.select({ slug: mods.slug }).from(mods);
  console.log(`after: ${after.length} mod row(s) → ${after.map((m) => m.slug).join(', ')}`);
}

// Silence the unused-import warning for `inArray` if a future caller wants it.
void inArray;

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
