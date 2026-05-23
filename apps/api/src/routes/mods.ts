import { zValidator } from '@hono/zod-validator';
import { getDb, schema } from '@rsmm/db';
import { modUploadRequestSchema } from '@rsmm/schemas';
import { and, desc, eq, ilike, or, sql } from 'drizzle-orm';
import { Hono } from 'hono';
import { z } from 'zod';
import { s3Configured } from '../env';
import { createRateLimiter } from '../rate-limit';
import { presignModUpload } from '../storage';
import type { AppEnv } from '../types';

export const modsRouter = new Hono<AppEnv>();

// Per-IP rate limiter for the download redirect endpoint. Without it,
// a script can spin the download counter (and the underlying S3 bill)
// arbitrarily fast. 120/min is well above any legitimate launcher
// install loop and small enough to make brute-forcing slug/version
// combos expensive.
const downloadLimiter = createRateLimiter({ windowMs: 60_000, maxHits: 120 });

const listQuerySchema = z.object({
  q: z.string().optional(),
  tag: z.string().optional(),
  limit: z.coerce.number().int().min(1).max(100).default(24),
  offset: z.coerce.number().int().min(0).default(0),
});

const slugParamSchema = z.object({
  slug: z.string().min(1).max(128).regex(/^[a-z0-9_-]+$/),
});

const downloadParamSchema = z.object({
  slug: z.string().min(1).max(128).regex(/^[a-z0-9_-]+$/),
  version: z.string().regex(/^\d+\.\d+\.\d+(?:[-+][\w.]+)?$/),
});

modsRouter.get('/', zValidator('query', listQuerySchema), async (c) => {
  const { q, tag, limit, offset } = c.req.valid('query');
  const db = getDb();

  const conditions = [
    q
      ? or(
          ilike(schema.mods.name, `%${q.replace(/[%_\\]/g, '\\$&')}%`),
          ilike(schema.mods.slug, `%${q.replace(/[%_\\]/g, '\\$&')}%`),
        )
      : undefined,
    tag ? sql`${tag} = ANY(${schema.mods.tags})` : undefined,
  ].filter(Boolean);

  const rows = await db
    .select({
      id: schema.mods.id,
      slug: schema.mods.slug,
      name: schema.mods.name,
      summary: schema.mods.summary,
      license: schema.mods.license,
      updatedAt: schema.mods.updatedAt,
      category: schema.mods.category,
      authorName: schema.mods.authorName,
      imageUrl: schema.mods.imageUrl,
      rating: schema.mods.rating,
      tags: schema.mods.tags,
      latestVersion: sql<string | null>`(
        select ${schema.modVersions.version}
        from ${schema.modVersions}
        where ${schema.modVersions.modId} = ${schema.mods.id}
        order by ${schema.modVersions.createdAt} desc
        limit 1
      )`,
      downloads: sql<number>`coalesce((
        select sum(${schema.modDownloads.count})::int
        from ${schema.modDownloads}
        where ${schema.modDownloads.modId} = ${schema.mods.id}
      ), 0)`,
    })
    .from(schema.mods)
    .where(conditions.length ? and(...conditions) : undefined)
    .orderBy(desc(schema.mods.updatedAt))
    .limit(limit)
    .offset(offset);

  const totals = await db
    .select({ total: sql<number>`count(*)::int` })
    .from(schema.mods)
    .where(conditions.length ? and(...conditions) : undefined);
  const total = totals[0]?.total ?? 0;

  return c.json({
    items: rows.map((r) => ({
      id: r.id,
      slug: r.slug,
      name: r.name,
      author: r.authorName,
      summary: r.summary,
      license: r.license,
      latestVersion: r.latestVersion,
      downloads: r.downloads,
      updatedAt: r.updatedAt.toISOString(),
      category: r.category,
      imageUrl: r.imageUrl,
      rating: r.rating != null ? Number(r.rating) : null,
      tags: r.tags ?? [],
    })),
    total,
  });
});

modsRouter.get('/:slug', zValidator('param', slugParamSchema), async (c) => {
  const { slug } = c.req.valid('param');
  const db = getDb();

  const mod = await db.query.mods.findFirst({
    where: eq(schema.mods.slug, slug),
    with: { versions: true },
  });
  if (!mod) return c.json({ error: 'not found' }, 404);

  // Aggregate downloads across all days for this mod. Mirrors the
  // expression used by the list endpoint so the same number shows up
  // everywhere; previously this route hard-coded `downloads: 0` and
  // the mod-detail page was permanently stuck at zero even after
  // hundreds of installs.
  const downloadAgg = await db
    .select({
      total: sql<number>`coalesce(sum(${schema.modDownloads.count})::int, 0)`,
    })
    .from(schema.modDownloads)
    .where(eq(schema.modDownloads.modId, mod.id));
  const downloads = downloadAgg[0]?.total ?? 0;

  return c.json({
    mod: {
      id: mod.id,
      slug: mod.slug,
      name: mod.name,
      author: mod.authorName,
      summary: mod.summary,
      license: mod.license,
      latestVersion: mod.versions[0]?.version ?? null,
      downloads,
      updatedAt: mod.updatedAt.toISOString(),
      category: mod.category,
      imageUrl: mod.imageUrl,
      rating: mod.rating != null ? Number(mod.rating) : null,
      tags: mod.tags ?? [],
    },
    versions: mod.versions.map((v) => ({
      id: v.id,
      modId: v.modId,
      version: v.version,
      sha256: v.sha256,
      sizeBytes: v.sizeBytes,
      manifestJson: v.manifestJson,
      assetUrl: v.assetUrl,
      createdAt: v.createdAt.toISOString(),
    })),
  });
});

modsRouter.use('/:slug/:version/download', downloadLimiter);
modsRouter.get('/:slug/:version/download', zValidator('param', downloadParamSchema), async (c) => {
  const slug = c.req.param('slug');
  const version = c.req.param('version');
  const db = getDb();

  const mod = await db.query.mods.findFirst({
    where: eq(schema.mods.slug, slug),
    with: {
      versions: {
        where: eq(schema.modVersions.version, version),
        limit: 1,
      },
    },
  });

  if (!mod || !mod.versions[0]) return c.json({ error: 'not found' }, 404);

  const ver = mod.versions[0];

  // Record the download. `mod_downloads` is bucketed by day with a
  // composite PK (mod_id, day), so the conflict path bumps today's
  // counter instead of inserting a duplicate row. We fire-and-forget
  // before the redirect so a tracker hiccup never blocks the actual
  // file download.
  void db
    .insert(schema.modDownloads)
    .values({
      modId: mod.id,
      versionId: ver.id,
      // `day` defaults to CURRENT_DATE in the schema.
      count: 1,
    })
    .onConflictDoUpdate({
      target: [schema.modDownloads.modId, schema.modDownloads.day],
      set: { count: sql`${schema.modDownloads.count} + 1` },
    })
    .catch((err: unknown) => {
      console.error('download-count upsert failed:', err);
    });

  // In dev without S3, serve a placeholder file
  if (!s3Configured() || ver.assetUrl.startsWith('https://example.invalid')) {
    const name = `${slug}-${version}.zip`;
    const content = `RSMM Mod Archive\n${slug} v${version}\nPlaceholder — replace with real mod files.\n`;
    c.header('Content-Type', 'application/octet-stream');
    c.header('Content-Disposition', `attachment; filename="${name}"`);
    return c.body(content);
  }

  return c.redirect(ver.assetUrl);
});

modsRouter.post('/upload', zValidator('json', modUploadRequestSchema), async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  if (!s3Configured()) {
    return c.json(
      { error: 'object storage is not configured on this server' },
      503,
    );
  }
  const body = c.req.valid('json');

  const MAX_MOD_SIZE_BYTES = 500_000_000;
  if (body.sizeBytes > MAX_MOD_SIZE_BYTES) {
    return c.json({ error: 'mod exceeds maximum size' }, 413);
  }

  const db = getDb();

  const signed = await presignModUpload({
    slug: body.slug,
    version: body.version,
    sha256: body.sha256,
    sizeBytes: body.sizeBytes,
  });

  // Declared outside the try so the catch block can read it after the
  // transaction throws to abort itself on ownership conflict.
  let ownerConflict = false;
  try {
    const result = await db.transaction(async (tx) => {
      // Re-do the ownership check inside the transaction with a row
      // lock so two concurrent uploads can't both pass a stale check
      // and then both upsert. The old code did the SELECT outside the
      // transaction, leaving a window where two callers could each
      // see the row as "free" and race to claim it.
      const lockedExisting = await tx
        .select()
        .from(schema.mods)
        .where(eq(schema.mods.slug, body.slug))
        .for('update');
      const existing = lockedExisting[0];
      if (existing && existing.ownerId !== null && existing.ownerId !== user.id) {
        ownerConflict = true;
        // Throwing aborts the transaction; the catch below converts
        // this signal into a clean 403 instead of a 500.
        throw new Error('owner conflict');
      }

      const modRows = await tx
        .insert(schema.mods)
        .values({
          slug: body.slug,
          name: body.manifest.name,
          summary: body.manifest.summary,
          description: body.manifest.description,
          license: body.manifest.license,
          repoUrl: body.manifest.repo_url,
          homepageUrl: body.manifest.homepage_url,
          tags: body.manifest.tags,
          authorName: body.manifest.author,
          ownerId: user.id,
        })
        .onConflictDoUpdate({
          target: schema.mods.slug,
          set: {
            name: body.manifest.name,
            summary: body.manifest.summary,
            description: body.manifest.description,
            license: body.manifest.license,
            repoUrl: body.manifest.repo_url,
            homepageUrl: body.manifest.homepage_url,
            tags: body.manifest.tags,
            authorName: body.manifest.author,
            ownerId: user.id,
            updatedAt: new Date(),
          },
        })
        .returning();
      const mod = modRows[0];
      if (!mod) throw new Error('failed to upsert mod');

      // Idempotent: re-presigning the same (mod_id, version) tuple
      // refreshes the row instead of dying on the unique-key. Without
      // this, a failed object-store PUT (e.g. browser hit Cloudflare's
      // Bot Fight Mode) would orphan the row and every subsequent
      // upload would 23505 forever. Retries now just rewrite the
      // asset_url / sha256 / size in-place.
      const versionRows = await tx
        .insert(schema.modVersions)
        .values({
          modId: mod.id,
          version: body.version,
          sha256: body.sha256,
          sizeBytes: body.sizeBytes,
          manifestJson: body.manifest,
          assetUrl: signed.publicUrl,
        })
        .onConflictDoUpdate({
          target: [schema.modVersions.modId, schema.modVersions.version],
          set: {
            sha256: body.sha256,
            sizeBytes: body.sizeBytes,
            manifestJson: body.manifest,
            assetUrl: signed.publicUrl,
          },
        })
        .returning();
      const version = versionRows[0];
      if (!version) throw new Error('failed to insert version');

      return { mod, version };
    });

    return c.json({
      uploadUrl: signed.uploadUrl,
      publicUrl: signed.publicUrl,
      versionId: result.version.id,
      expiresIn: signed.expiresIn,
    });
  } catch (err) {
    // The transaction throws "owner conflict" when the slug already
    // belongs to a different user. Surface that as a 403 instead of
    // a 500 — `ownerConflict` is set inside the transaction body.
    if (ownerConflict) {
      return c.json({ error: 'slug owned by another user' }, 403);
    }
    // Unique constraint violation (PostgreSQL error code 23505).
    // Drizzle wraps the underlying pg error in `DrizzleQueryError`, so
    // the PG `code` lives on `err.cause.code`. Older code only checked
    // `err.code` and let dupes leak through as a generic 500.
    if (isPgErrorCode(err, '23505')) {
      return c.json({ error: 'version already exists' }, 409);
    }
    console.error('Upload error:', err);
    return c.json({ error: 'failed to create mod version' }, 500);
  }
});

function isPgErrorCode(err: unknown, code: string): boolean {
  if (!err || typeof err !== 'object') return false;
  const top = err as { code?: unknown; cause?: unknown };
  if (top.code === code) return true;
  const cause = top.cause;
  if (cause && typeof cause === 'object' && (cause as { code?: unknown }).code === code) {
    return true;
  }
  return false;
}
