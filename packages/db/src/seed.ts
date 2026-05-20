import { config as loadEnv } from 'dotenv';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { getDb } from './client';
import { mods, modVersions } from './schema/mods';

const here = fileURLToPath(new URL('.', import.meta.url));
loadEnv({ path: resolve(here, '..', '..', '..', '.env') });
loadEnv();

async function main() {
  const db = getDb();
  console.log('seeding…');

  const [example] = await db
    .insert(mods)
    .values({
      slug: 'example-magic-item',
      name: 'Example Magic Item',
      summary: 'Adds a sample magic item to the loot pool.',
      license: 'MIT',
      tags: ['example', 'item'],
    })
    .onConflictDoNothing()
    .returning();

  if (example) {
    await db
      .insert(modVersions)
      .values({
        modId: example.id,
        version: '0.1.0',
        sha256: 'a'.repeat(64),
        sizeBytes: 1024,
        assetUrl: 'https://example.invalid/example-magic-item-0.1.0.zip',
        manifestJson: {
          id: 'example-magic-item',
          name: 'Example Magic Item',
          version: '0.1.0',
        },
      })
      .onConflictDoNothing();
  }

  console.log('seed complete');
  process.exit(0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
