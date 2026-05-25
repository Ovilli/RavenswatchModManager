import { zValidator } from '@hono/zod-validator';
import { getDb, schema } from '@rsmm/db';
import {
  modImagePresignSchema,
  modPatchSchema,
  modUploadRequestSchema,
  modVersionCreateSchema,
  reviewUpsertSchema,
} from '@rsmm/schemas';
import { and, desc, eq, ilike, or, sql } from 'drizzle-orm';
import { Hono } from 'hono';
import { z } from 'zod';
import { isPgErrorCode } from '../db-errors';
import { s3Configured } from '../env';
import { createRateLimiter } from '../rate-limit';
import { presignModImage, presignModUpload } from '../storage';
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
  featured: z
    .union([z.literal('true'), z.literal('false'), z.literal('1'), z.literal('0')])
    .optional()
    .transform((v) => (v === 'true' || v === '1' ? true : v === undefined ? undefined : false)),
  owner: z.string().optional(),
  sort: z.enum(['recent', 'popular', 'featured']).default('recent'),
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
  const { q, tag, featured, owner, sort, limit, offset } = c.req.valid('query');
  const db = getDb();

  const conditions = [
    q
      ? or(
          ilike(schema.mods.name, `%${q.replace(/[%_\\]/g, '\\$&')}%`),
          ilike(schema.mods.slug, `%${q.replace(/[%_\\]/g, '\\$&')}%`),
        )
      : undefined,
    tag ? sql`${tag} = ANY(${schema.mods.tags})` : undefined,
    featured === true ? eq(schema.mods.featured, true) : undefined,
    owner ? eq(schema.mods.ownerId, owner) : undefined,
  ].filter(Boolean);

  const orderBy =
    sort === 'popular'
      ? sql`coalesce((
          select sum(${schema.modDownloads.count})
          from ${schema.modDownloads}
          where ${schema.modDownloads.modId} = ${schema.mods.id}
        ), 0) desc`
      : sort === 'featured'
        ? sql`${schema.mods.featured} desc, ${schema.mods.featuredAt} desc nulls last, ${schema.mods.updatedAt} desc`
        : desc(schema.mods.updatedAt);

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
      screenshots: schema.mods.screenshots,
      videos: schema.mods.videos,
      rating: schema.mods.rating,
      tags: schema.mods.tags,
      featured: schema.mods.featured,
      ownerId: schema.mods.ownerId,
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
    .orderBy(orderBy)
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
      screenshots: r.screenshots ?? [],
      videos: r.videos ?? [],
      rating: r.rating != null ? Number(r.rating) : null,
      tags: r.tags ?? [],
      featured: r.featured,
      ownerId: r.ownerId,
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
      description: mod.description,
      license: mod.license,
      repoUrl: mod.repoUrl,
      homepageUrl: mod.homepageUrl,
      latestVersion: mod.versions[0]?.version ?? null,
      downloads,
      updatedAt: mod.updatedAt.toISOString(),
      category: mod.category,
      imageUrl: mod.imageUrl,
      screenshots: mod.screenshots ?? [],
      videos: mod.videos ?? [],
      rating: mod.rating != null ? Number(mod.rating) : null,
      tags: mod.tags ?? [],
      featured: mod.featured,
      ownerId: mod.ownerId,
      dependencies:
        (mod.versions[0]?.manifestJson as { dependencies?: Record<string, string> } | undefined)
          ?.dependencies ?? undefined,
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
  const { slug, version } = c.req.valid('param');
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

// ─────────────────────────────────────────────────────────────────────
// Owner-scoped mod management routes. All require an authenticated
// session and verify that `mod.ownerId === user.id` before mutating.
// ─────────────────────────────────────────────────────────────────────

const ownerLimiter = createRateLimiter({
  windowMs: 60_000,
  maxHits: 60,
  keyFrom: (c) => {
    const user = c.get('user');
    return user?.id ?? c.req.header('x-forwarded-for')?.split(',')[0]?.trim() ?? 'anon';
  },
});

modsRouter.use('/:slug/edit', ownerLimiter);
modsRouter.patch(
  '/:slug/edit',
  zValidator('param', slugParamSchema),
  zValidator('json', modPatchSchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    const { slug } = c.req.valid('param');
    const patch = c.req.valid('json');
    const db = getDb();

    const existing = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
    if (!existing) return c.json({ error: 'not found' }, 404);
    if (existing.ownerId !== user.id) return c.json({ error: 'forbidden' }, 403);

    // Build an update object that only sets keys the caller sent. The
    // `?? undefined` dance is needed because zod returns `null` for
    // fields the caller explicitly cleared and we want those nulls to
    // persist to the DB.
    const updates: Partial<typeof schema.mods.$inferInsert> = { updatedAt: new Date() };
    if (patch.name !== undefined) updates.name = patch.name;
    if (patch.summary !== undefined) updates.summary = patch.summary;
    if (patch.description !== undefined) updates.description = patch.description;
    if (patch.license !== undefined) updates.license = patch.license;
    if (patch.repoUrl !== undefined) updates.repoUrl = patch.repoUrl;
    if (patch.homepageUrl !== undefined) updates.homepageUrl = patch.homepageUrl;
    if (patch.category !== undefined) updates.category = patch.category;
    if (patch.tags !== undefined) updates.tags = patch.tags;
    if (patch.imageUrl !== undefined) updates.imageUrl = patch.imageUrl;
    if (patch.screenshots !== undefined) updates.screenshots = patch.screenshots;
    if (patch.videos !== undefined) updates.videos = patch.videos;

    const rows = await db
      .update(schema.mods)
      .set(updates)
      .where(eq(schema.mods.id, existing.id))
      .returning();
    return c.json({ mod: rows[0] });
  },
);

modsRouter.use('/:slug/image', ownerLimiter);
modsRouter.post(
  '/:slug/image',
  zValidator('param', slugParamSchema),
  zValidator('json', modImagePresignSchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    if (!s3Configured()) return c.json({ error: 'object storage not configured' }, 503);
    const { slug } = c.req.valid('param');
    const body = c.req.valid('json');
    const db = getDb();

    const existing = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
    if (!existing) return c.json({ error: 'not found' }, 404);
    if (existing.ownerId !== user.id) return c.json({ error: 'forbidden' }, 403);

    const signed = await presignModImage({
      slug,
      contentType: body.contentType,
      sizeBytes: body.sizeBytes,
    });
    return c.json({
      uploadUrl: signed.uploadUrl,
      publicUrl: signed.publicUrl,
      expiresIn: signed.expiresIn,
    });
  },
);

modsRouter.use('/:slug/versions', ownerLimiter);
modsRouter.post(
  '/:slug/versions',
  zValidator('param', slugParamSchema),
  zValidator('json', modVersionCreateSchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    if (!s3Configured()) return c.json({ error: 'object storage not configured' }, 503);
    const { slug } = c.req.valid('param');
    const body = c.req.valid('json');

    const MAX_MOD_SIZE_BYTES = 500_000_000;
    if (body.sizeBytes > MAX_MOD_SIZE_BYTES) {
      return c.json({ error: 'mod exceeds maximum size' }, 413);
    }

    const db = getDb();
    const existing = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
    if (!existing) return c.json({ error: 'not found' }, 404);
    if (existing.ownerId !== user.id) return c.json({ error: 'forbidden' }, 403);

    const signed = await presignModUpload({
      slug,
      version: body.version,
      sha256: body.sha256,
      sizeBytes: body.sizeBytes,
    });

    try {
      const rows = await db
        .insert(schema.modVersions)
        .values({
          modId: existing.id,
          version: body.version,
          sha256: body.sha256,
          sizeBytes: body.sizeBytes,
          manifestJson: body.manifest,
          assetUrl: signed.publicUrl,
          changelog: body.changelog ?? null,
        })
        .onConflictDoUpdate({
          target: [schema.modVersions.modId, schema.modVersions.version],
          set: {
            sha256: body.sha256,
            sizeBytes: body.sizeBytes,
            manifestJson: body.manifest,
            assetUrl: signed.publicUrl,
            changelog: body.changelog ?? null,
          },
        })
        .returning();

      await db
        .update(schema.mods)
        .set({ updatedAt: new Date() })
        .where(eq(schema.mods.id, existing.id));

      return c.json({
        uploadUrl: signed.uploadUrl,
        publicUrl: signed.publicUrl,
        versionId: rows[0]?.id,
        expiresIn: signed.expiresIn,
      });
    } catch (err) {
      console.error('Version create error:', err);
      return c.json({ error: 'failed to create version' }, 500);
    }
  },
);

modsRouter.use('/:slug/delete', ownerLimiter);
modsRouter.delete('/:slug/delete', zValidator('param', slugParamSchema), async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const { slug } = c.req.valid('param');
  const db = getDb();

  const existing = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
  if (!existing) return c.json({ error: 'not found' }, 404);
  if (existing.ownerId !== user.id) return c.json({ error: 'forbidden' }, 403);

  // Cascade removes mod_versions, mod_authors, mod_downloads via FK.
  await db.delete(schema.mods).where(eq(schema.mods.id, existing.id));
  return c.json({ ok: true });
});

// ─────────── Reviews ───────────

const reviewLimiter = createRateLimiter({
  windowMs: 60_000,
  maxHits: 10,
  keyFrom: (c) => {
    const user = c.get('user');
    return user?.id ?? c.req.header('x-forwarded-for')?.split(',')[0]?.trim() ?? 'anon';
  },
});

async function recomputeRating(modId: string): Promise<void> {
  const db = getDb();
  const agg = await db
    .select({
      avg: sql<number | null>`avg(${schema.modReviews.rating})::numeric(3,2)`,
    })
    .from(schema.modReviews)
    .where(eq(schema.modReviews.modId, modId));
  const avg = agg[0]?.avg;
  await db
    .update(schema.mods)
    .set({ rating: avg == null ? null : String(avg) })
    .where(eq(schema.mods.id, modId));
}

modsRouter.get('/:slug/reviews', zValidator('param', slugParamSchema), async (c) => {
  const { slug } = c.req.valid('param');
  const db = getDb();
  const mod = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
  if (!mod) return c.json({ error: 'not found' }, 404);

  const rows = await db
    .select({
      id: schema.modReviews.id,
      modId: schema.modReviews.modId,
      userId: schema.modReviews.userId,
      rating: schema.modReviews.rating,
      title: schema.modReviews.title,
      body: schema.modReviews.body,
      createdAt: schema.modReviews.createdAt,
      updatedAt: schema.modReviews.updatedAt,
      userName: schema.users.name,
      userImage: schema.users.image,
    })
    .from(schema.modReviews)
    .innerJoin(schema.users, eq(schema.users.id, schema.modReviews.userId))
    .where(eq(schema.modReviews.modId, mod.id))
    .orderBy(desc(schema.modReviews.updatedAt));

  const items = rows.map((r) => ({
    id: r.id,
    modId: r.modId,
    userId: r.userId,
    userName: r.userName,
    userImage: r.userImage,
    rating: r.rating,
    title: r.title,
    body: r.body,
    createdAt: r.createdAt.toISOString(),
    updatedAt: r.updatedAt.toISOString(),
  }));

  const average = items.length
    ? items.reduce((s, r) => s + r.rating, 0) / items.length
    : null;

  return c.json({ items, total: items.length, averageRating: average });
});

modsRouter.use('/:slug/reviews', reviewLimiter);
modsRouter.put(
  '/:slug/reviews',
  zValidator('param', slugParamSchema),
  zValidator('json', reviewUpsertSchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    const { slug } = c.req.valid('param');
    const body = c.req.valid('json');
    const db = getDb();

    const mod = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
    if (!mod) return c.json({ error: 'not found' }, 404);
    if (mod.ownerId === user.id) {
      return c.json({ error: 'authors cannot review their own mod' }, 400);
    }

    const now = new Date();
    await db
      .insert(schema.modReviews)
      .values({
        modId: mod.id,
        userId: user.id,
        rating: body.rating,
        title: body.title ?? null,
        body: body.body ?? null,
        updatedAt: now,
      })
      .onConflictDoUpdate({
        target: [schema.modReviews.modId, schema.modReviews.userId],
        set: {
          rating: body.rating,
          title: body.title ?? null,
          body: body.body ?? null,
          updatedAt: now,
        },
      });

    await recomputeRating(mod.id);
    return c.json({ ok: true });
  },
);

modsRouter.delete('/:slug/reviews', zValidator('param', slugParamSchema), async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const { slug } = c.req.valid('param');
  const db = getDb();

  const mod = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
  if (!mod) return c.json({ error: 'not found' }, 404);

  await db
    .delete(schema.modReviews)
    .where(
      and(eq(schema.modReviews.modId, mod.id), eq(schema.modReviews.userId, user.id)),
    );
  await recomputeRating(mod.id);
  return c.json({ ok: true });
});
