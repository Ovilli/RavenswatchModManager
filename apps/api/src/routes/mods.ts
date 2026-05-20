import { zValidator } from '@hono/zod-validator';
import { getDb, schema } from '@rsmm/db';
import { modUploadRequestSchema } from '@rsmm/schemas';
import { and, desc, eq, ilike, or, sql } from 'drizzle-orm';
import { Hono } from 'hono';
import { z } from 'zod';
import { s3Configured } from '../env';
import { presignModUpload } from '../storage';
import type { AppEnv } from '../types';

export const modsRouter = new Hono<AppEnv>();

const listQuerySchema = z.object({
  q: z.string().optional(),
  tag: z.string().optional(),
  limit: z.coerce.number().int().min(1).max(100).default(24),
  offset: z.coerce.number().int().min(0).default(0),
});

modsRouter.get('/', zValidator('query', listQuerySchema), async (c) => {
  const { q, tag, limit, offset } = c.req.valid('query');
  const db = getDb();

  const conditions = [
    q ? or(ilike(schema.mods.name, `%${q}%`), ilike(schema.mods.slug, `%${q}%`)) : undefined,
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
      author: null,
      summary: r.summary,
      license: r.license,
      latestVersion: r.latestVersion,
      downloads: r.downloads,
      updatedAt: r.updatedAt.toISOString(),
    })),
    total,
  });
});

modsRouter.get('/:slug', async (c) => {
  const slug = c.req.param('slug');
  const db = getDb();

  const mod = await db.query.mods.findFirst({
    where: eq(schema.mods.slug, slug),
    with: { versions: true },
  });
  if (!mod) return c.json({ error: 'not found' }, 404);

  return c.json({
    mod: {
      id: mod.id,
      slug: mod.slug,
      name: mod.name,
      author: null,
      summary: mod.summary,
      license: mod.license,
      latestVersion: mod.versions[0]?.version ?? null,
      downloads: 0,
      updatedAt: mod.updatedAt.toISOString(),
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
  const db = getDb();

  const existing = await db.query.mods.findFirst({
    where: eq(schema.mods.slug, body.slug),
  });
  if (existing?.ownerId && existing.ownerId !== user.id) {
    return c.json({ error: 'slug owned by another user' }, 403);
  }

  const dupVersion = existing
    ? await db.query.modVersions.findFirst({
        where: and(
          eq(schema.modVersions.modId, existing.id),
          eq(schema.modVersions.version, body.version),
        ),
      })
    : null;
  if (dupVersion) {
    return c.json({ error: 'version already exists' }, 409);
  }

  const signed = await presignModUpload({
    slug: body.slug,
    version: body.version,
    sha256: body.sha256,
    sizeBytes: body.sizeBytes,
  });

  const modRows = await db
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
        updatedAt: new Date(),
      },
    })
    .returning();
  const mod = modRows[0];
  if (!mod) return c.json({ error: 'failed to upsert mod' }, 500);

  const versionRows = await db
    .insert(schema.modVersions)
    .values({
      modId: mod.id,
      version: body.version,
      sha256: body.sha256,
      sizeBytes: body.sizeBytes,
      manifestJson: body.manifest,
      assetUrl: signed.publicUrl,
    })
    .returning();
  const version = versionRows[0];
  if (!version) return c.json({ error: 'failed to insert version' }, 500);

  // Client now PUTs the .zip to uploadUrl with
  // `Content-Type: application/zip` and
  // `x-amz-checksum-sha256: <base64-of-sha256>` matching the body.
  return c.json({
    uploadUrl: signed.uploadUrl,
    publicUrl: signed.publicUrl,
    versionId: version.id,
    expiresIn: signed.expiresIn,
  });
});
