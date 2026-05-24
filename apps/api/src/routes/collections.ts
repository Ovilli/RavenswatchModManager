import { zValidator } from '@hono/zod-validator';
import { getDb, schema } from '@rsmm/db';
import {
  collectionAddModSchema,
  collectionCreateSchema,
  collectionPatchSchema,
  collectionSlugSchema,
} from '@rsmm/schemas';
import { and, asc, desc, eq, sql } from 'drizzle-orm';
import { Hono } from 'hono';
import { z } from 'zod';
import { createRateLimiter } from '../rate-limit';
import type { AppEnv } from '../types';

export const collectionsRouter = new Hono<AppEnv>();

const slugParamSchema = z.object({ slug: collectionSlugSchema });
const slugAndModParamSchema = z.object({
  slug: collectionSlugSchema,
  modSlug: z.string().min(1).max(128).regex(/^[a-z0-9_-]+$/),
});

const writeLimiter = createRateLimiter({
  windowMs: 60_000,
  maxHits: 30,
  keyFrom: (c) => c.get('user')?.id ?? c.req.header('x-forwarded-for') ?? 'anon',
});

collectionsRouter.get('/', async (c) => {
  const db = getDb();
  const rows = await db
    .select({
      id: schema.collections.id,
      slug: schema.collections.slug,
      ownerId: schema.collections.ownerId,
      name: schema.collections.name,
      summary: schema.collections.summary,
      isPublic: schema.collections.isPublic,
      createdAt: schema.collections.createdAt,
      updatedAt: schema.collections.updatedAt,
      ownerName: schema.users.name,
      ownerImage: schema.users.image,
      modCount: sql<number>`(
        select count(*)::int from ${schema.collectionMods}
        where ${schema.collectionMods.collectionId} = ${schema.collections.id}
      )`,
    })
    .from(schema.collections)
    .innerJoin(schema.users, eq(schema.users.id, schema.collections.ownerId))
    .where(eq(schema.collections.isPublic, true))
    .orderBy(desc(schema.collections.updatedAt))
    .limit(60);

  return c.json({
    items: rows.map((r) => ({
      id: r.id,
      slug: r.slug,
      ownerId: r.ownerId,
      ownerName: r.ownerName,
      ownerImage: r.ownerImage,
      name: r.name,
      summary: r.summary,
      isPublic: r.isPublic,
      modCount: r.modCount,
      createdAt: r.createdAt.toISOString(),
      updatedAt: r.updatedAt.toISOString(),
    })),
  });
});

collectionsRouter.get('/mine', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const db = getDb();
  const rows = await db
    .select({
      id: schema.collections.id,
      slug: schema.collections.slug,
      ownerId: schema.collections.ownerId,
      name: schema.collections.name,
      summary: schema.collections.summary,
      isPublic: schema.collections.isPublic,
      createdAt: schema.collections.createdAt,
      updatedAt: schema.collections.updatedAt,
      modCount: sql<number>`(
        select count(*)::int from ${schema.collectionMods}
        where ${schema.collectionMods.collectionId} = ${schema.collections.id}
      )`,
    })
    .from(schema.collections)
    .where(eq(schema.collections.ownerId, user.id))
    .orderBy(desc(schema.collections.updatedAt));

  return c.json({
    items: rows.map((r) => ({
      id: r.id,
      slug: r.slug,
      ownerId: r.ownerId,
      ownerName: user.name ?? null,
      ownerImage: user.image ?? null,
      name: r.name,
      summary: r.summary,
      isPublic: r.isPublic,
      modCount: r.modCount,
      createdAt: r.createdAt.toISOString(),
      updatedAt: r.updatedAt.toISOString(),
    })),
  });
});

collectionsRouter.use('/', writeLimiter);
collectionsRouter.post('/', zValidator('json', collectionCreateSchema), async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const body = c.req.valid('json');
  const db = getDb();

  try {
    const [row] = await db
      .insert(schema.collections)
      .values({
        slug: body.slug,
        ownerId: user.id,
        name: body.name,
        summary: body.summary ?? null,
        isPublic: body.isPublic ?? true,
      })
      .returning();
    return c.json({ collection: row }, 201);
  } catch (err) {
    if ((err as { code?: string })?.code === '23505') {
      return c.json({ error: 'slug already in use' }, 409);
    }
    throw err;
  }
});

collectionsRouter.get('/:slug', zValidator('param', slugParamSchema), async (c) => {
  const { slug } = c.req.valid('param');
  const db = getDb();
  const user = c.get('user');

  const row = await db
    .select({
      id: schema.collections.id,
      slug: schema.collections.slug,
      ownerId: schema.collections.ownerId,
      name: schema.collections.name,
      summary: schema.collections.summary,
      isPublic: schema.collections.isPublic,
      createdAt: schema.collections.createdAt,
      updatedAt: schema.collections.updatedAt,
      ownerName: schema.users.name,
      ownerImage: schema.users.image,
    })
    .from(schema.collections)
    .innerJoin(schema.users, eq(schema.users.id, schema.collections.ownerId))
    .where(eq(schema.collections.slug, slug))
    .limit(1);

  const head = row[0];
  if (!head) return c.json({ error: 'not found' }, 404);
  if (!head.isPublic && head.ownerId !== user?.id) {
    return c.json({ error: 'not found' }, 404);
  }

  const mods = await db
    .select({
      position: schema.collectionMods.position,
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
    .from(schema.collectionMods)
    .innerJoin(schema.mods, eq(schema.mods.id, schema.collectionMods.modId))
    .where(eq(schema.collectionMods.collectionId, head.id))
    .orderBy(asc(schema.collectionMods.position), asc(schema.collectionMods.addedAt));

  return c.json({
    id: head.id,
    slug: head.slug,
    ownerId: head.ownerId,
    ownerName: head.ownerName,
    ownerImage: head.ownerImage,
    name: head.name,
    summary: head.summary,
    isPublic: head.isPublic,
    modCount: mods.length,
    createdAt: head.createdAt.toISOString(),
    updatedAt: head.updatedAt.toISOString(),
    mods: mods.map((m) => ({
      id: m.id,
      slug: m.slug,
      name: m.name,
      author: m.authorName,
      summary: m.summary,
      license: m.license,
      latestVersion: m.latestVersion,
      downloads: m.downloads,
      updatedAt: m.updatedAt.toISOString(),
      category: m.category,
      imageUrl: m.imageUrl,
      rating: m.rating != null ? Number(m.rating) : null,
      tags: m.tags ?? [],
      featured: m.featured,
      ownerId: m.ownerId,
    })),
  });
});

collectionsRouter.patch(
  '/:slug',
  zValidator('param', slugParamSchema),
  zValidator('json', collectionPatchSchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    const { slug } = c.req.valid('param');
    const body = c.req.valid('json');
    const db = getDb();

    const existing = await db.query.collections.findFirst({
      where: eq(schema.collections.slug, slug),
    });
    if (!existing) return c.json({ error: 'not found' }, 404);
    if (existing.ownerId !== user.id) return c.json({ error: 'forbidden' }, 403);

    const updates: Record<string, unknown> = { updatedAt: new Date() };
    if (body.name !== undefined) updates.name = body.name;
    if (body.summary !== undefined) updates.summary = body.summary;
    if (body.isPublic !== undefined) updates.isPublic = body.isPublic;

    await db.update(schema.collections).set(updates).where(eq(schema.collections.id, existing.id));
    return c.json({ ok: true });
  },
);

collectionsRouter.delete('/:slug', zValidator('param', slugParamSchema), async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const { slug } = c.req.valid('param');
  const db = getDb();
  const existing = await db.query.collections.findFirst({
    where: eq(schema.collections.slug, slug),
  });
  if (!existing) return c.json({ error: 'not found' }, 404);
  if (existing.ownerId !== user.id) return c.json({ error: 'forbidden' }, 403);
  await db.delete(schema.collections).where(eq(schema.collections.id, existing.id));
  return c.json({ ok: true });
});

collectionsRouter.post(
  '/:slug/mods',
  zValidator('param', slugParamSchema),
  zValidator('json', collectionAddModSchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    const { slug } = c.req.valid('param');
    const { modSlug } = c.req.valid('json');
    const db = getDb();

    const collection = await db.query.collections.findFirst({
      where: eq(schema.collections.slug, slug),
    });
    if (!collection) return c.json({ error: 'not found' }, 404);
    if (collection.ownerId !== user.id) return c.json({ error: 'forbidden' }, 403);

    const mod = await db.query.mods.findFirst({ where: eq(schema.mods.slug, modSlug) });
    if (!mod) return c.json({ error: 'mod not found' }, 404);

    const maxPos = await db
      .select({ p: sql<number | null>`max(${schema.collectionMods.position})` })
      .from(schema.collectionMods)
      .where(eq(schema.collectionMods.collectionId, collection.id));
    const nextPos = (maxPos[0]?.p ?? -1) + 1;

    await db
      .insert(schema.collectionMods)
      .values({ collectionId: collection.id, modId: mod.id, position: nextPos })
      .onConflictDoNothing();
    await db
      .update(schema.collections)
      .set({ updatedAt: new Date() })
      .where(eq(schema.collections.id, collection.id));
    return c.json({ ok: true });
  },
);

collectionsRouter.delete(
  '/:slug/mods/:modSlug',
  zValidator('param', slugAndModParamSchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    const { slug, modSlug } = c.req.valid('param');
    const db = getDb();

    const collection = await db.query.collections.findFirst({
      where: eq(schema.collections.slug, slug),
    });
    if (!collection) return c.json({ error: 'not found' }, 404);
    if (collection.ownerId !== user.id) return c.json({ error: 'forbidden' }, 403);

    const mod = await db.query.mods.findFirst({ where: eq(schema.mods.slug, modSlug) });
    if (!mod) return c.json({ error: 'mod not found' }, 404);

    await db
      .delete(schema.collectionMods)
      .where(
        and(
          eq(schema.collectionMods.collectionId, collection.id),
          eq(schema.collectionMods.modId, mod.id),
        ),
      );
    await db
      .update(schema.collections)
      .set({ updatedAt: new Date() })
      .where(eq(schema.collections.id, collection.id));
    return c.json({ ok: true });
  },
);
