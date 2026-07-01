import { getDb, schema } from '@rsmm/db';
import { and, eq } from 'drizzle-orm';

/**
 * Whether a user may MANAGE a mod (edit metadata, publish versions, upload
 * images, trigger scans). True for the owner or anyone listed in mod_authors.
 *
 * Owner-ONLY actions (delete, transfer, add/remove co-authors) must keep
 * checking `mod.ownerId === user.id` directly — do not route them through this.
 */
export async function canManageMod(
  mod: { id: string; ownerId: string | null },
  userId: string,
): Promise<boolean> {
  if (mod.ownerId === userId) return true;
  const rows = await getDb()
    .select({ userId: schema.modAuthors.userId })
    .from(schema.modAuthors)
    .where(and(eq(schema.modAuthors.modId, mod.id), eq(schema.modAuthors.userId, userId)))
    .limit(1);
  return rows.length > 0;
}
