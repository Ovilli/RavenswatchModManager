import { zValidator } from '@hono/zod-validator';
import { getDb, schema } from '@rsmm/db';
import {
  guideCreateSchema,
  guideImagePresignSchema,
  guidePatchSchema,
  guideReviewUpsertSchema,
  guideSlugSchema,
} from '@rsmm/schemas';
import { and, asc, desc, eq, ilike, or, sql } from 'drizzle-orm';
import { Hono } from 'hono';
import { z } from 'zod';
import { isPgErrorCode } from '../db-errors';
import { env, s3Configured } from '../env';
import { createRateLimiter } from '../rate-limit';
import { presignGuideImage } from '../storage';
import type { AppEnv } from '../types';

export const guidesRouter = new Hono<AppEnv>();

const slugParamSchema = z.object({ slug: guideSlugSchema });

const isAdmin = (userId?: string | null): boolean => !!userId && env.adminUserIds.includes(userId);

type GuideVisibility = Pick<typeof schema.guides.$inferSelect, 'status' | 'ownerId'>;

// Approved guides are public; the owner and admins can see their guide in any
// status (draft/pending/rejected) so they can edit or review it.
function canViewGuide(guide: GuideVisibility, userId?: string | null): boolean {
  return guide.status === 'approved' || guide.ownerId === userId || isAdmin(userId);
}

const writeLimiter = createRateLimiter({
  name: 'guide-write',
  windowMs: 60_000,
  maxHits: 30,
  keyFrom: (c) => {
    const user = c.get('user');
    return (
      user?.id ??
      c.req.header('x-real-ip') ??
      c.req.header('x-forwarded-for')?.split(',').pop()?.trim() ??
      'anon'
    );
  },
});

const ratingSql = sql<number | null>`(
  select round(avg(${schema.guideReviews.rating})::numeric, 1)::float
  from ${schema.guideReviews}
  where ${schema.guideReviews.guideId} = ${schema.guides.id}
)`;
const reviewCountSql = sql<number>`(
  select count(*)::int from ${schema.guideReviews}
  where ${schema.guideReviews.guideId} = ${schema.guides.id}
)`;

function serializeList(r: {
  id: string;
  slug: string;
  ownerId: string;
  ownerName: string | null;
  ownerImage: string | null;
  title: string;
  summary: string | null;
  body: string;
  imageUrl: string | null;
  status: string;
  createdAt: Date;
  updatedAt: Date;
  rating: number | null;
  reviewCount: number;
}) {
  return {
    id: r.id,
    slug: r.slug,
    ownerId: r.ownerId,
    ownerName: r.ownerName,
    ownerImage: r.ownerImage,
    title: r.title,
    summary: r.summary,
    body: r.body,
    imageUrl: r.imageUrl,
    screenshots: [] as { url: string; caption?: string }[],
    status: r.status,
    rating: r.rating,
    reviewCount: r.reviewCount,
    createdAt: r.createdAt.toISOString(),
    updatedAt: r.updatedAt.toISOString(),
  };
}

const listColumns = {
  id: schema.guides.id,
  slug: schema.guides.slug,
  ownerId: schema.guides.ownerId,
  title: schema.guides.title,
  summary: schema.guides.summary,
  // List bodies are trimmed client-side; sent for search/preview only.
  body: schema.guides.body,
  imageUrl: schema.guides.imageUrl,
  status: schema.guides.status,
  createdAt: schema.guides.createdAt,
  updatedAt: schema.guides.updatedAt,
  ownerName: schema.users.name,
  ownerImage: schema.users.image,
  rating: ratingSql,
  reviewCount: reviewCountSql,
};

const listQuerySchema = z.object({
  q: z.string().trim().max(120).optional(),
  // recent = newest update; rating = highest average review score (unrated
  // sink last); popular = most reviewed; title = alphabetical.
  sort: z.enum(['recent', 'rating', 'popular', 'title']).default('recent'),
  limit: z.coerce.number().int().min(1).max(100).default(100),
  offset: z.coerce.number().int().min(0).default(0),
});

// Public list — approved guides only. Searchable (q) and sortable (sort).
guidesRouter.get('/', zValidator('query', listQuerySchema), async (c) => {
  const { q, sort, limit, offset } = c.req.valid('query');
  const db = getDb();

  const conditions = [
    eq(schema.guides.status, 'approved'),
    q
      ? or(
          ilike(schema.guides.title, `%${q.replace(/[%_\\]/g, '\\$&')}%`),
          ilike(schema.guides.summary, `%${q.replace(/[%_\\]/g, '\\$&')}%`),
          ilike(schema.guides.body, `%${q.replace(/[%_\\]/g, '\\$&')}%`),
        )
      : undefined,
  ].filter(Boolean);

  const orderBy =
    sort === 'rating'
      ? [sql`${ratingSql} desc nulls last`, desc(schema.guides.updatedAt)]
      : sort === 'popular'
        ? [sql`${reviewCountSql} desc`, desc(schema.guides.updatedAt)]
        : sort === 'title'
          ? [asc(schema.guides.title)]
          : [desc(schema.guides.updatedAt)];

  const rows = await db
    .select(listColumns)
    .from(schema.guides)
    .innerJoin(schema.users, eq(schema.users.id, schema.guides.ownerId))
    .where(and(...conditions))
    .orderBy(...orderBy)
    .limit(limit)
    .offset(offset);
  return c.json({ items: rows.map(serializeList) });
});

// The signed-in user's own guides, any status.
guidesRouter.get('/mine', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const db = getDb();
  const rows = await db
    .select(listColumns)
    .from(schema.guides)
    .innerJoin(schema.users, eq(schema.users.id, schema.guides.ownerId))
    .where(eq(schema.guides.ownerId, user.id))
    .orderBy(desc(schema.guides.updatedAt));
  return c.json({ items: rows.map(serializeList) });
});

// Moderation queue — admins only, guides awaiting review.
guidesRouter.get('/pending', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  if (!isAdmin(user.id)) return c.json({ error: 'forbidden' }, 403);
  const db = getDb();
  const rows = await db
    .select(listColumns)
    .from(schema.guides)
    .innerJoin(schema.users, eq(schema.users.id, schema.guides.ownerId))
    .where(eq(schema.guides.status, 'pending'))
    .orderBy(desc(schema.guides.updatedAt));
  return c.json({ items: rows.map(serializeList) });
});

guidesRouter.post('/', writeLimiter, zValidator('json', guideCreateSchema), async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const body = c.req.valid('json');
  const db = getDb();
  try {
    const [row] = await db
      .insert(schema.guides)
      .values({
        slug: body.slug,
        ownerId: user.id,
        title: body.title,
        summary: body.summary ?? null,
        body: body.body,
        imageUrl: body.imageUrl ?? null,
        screenshots: body.screenshots ?? null,
        status: 'draft',
      })
      .returning();
    return c.json({ guide: row }, 201);
  } catch (err) {
    if (isPgErrorCode(err, '23505')) return c.json({ error: 'slug already in use' }, 409);
    throw err;
  }
});

guidesRouter.get('/:slug', zValidator('param', slugParamSchema), async (c) => {
  const { slug } = c.req.valid('param');
  const user = c.get('user');
  const db = getDb();
  const row = await db
    .select({
      id: schema.guides.id,
      slug: schema.guides.slug,
      ownerId: schema.guides.ownerId,
      title: schema.guides.title,
      summary: schema.guides.summary,
      body: schema.guides.body,
      imageUrl: schema.guides.imageUrl,
      screenshots: schema.guides.screenshots,
      status: schema.guides.status,
      createdAt: schema.guides.createdAt,
      updatedAt: schema.guides.updatedAt,
      ownerName: schema.users.name,
      ownerImage: schema.users.image,
      rating: ratingSql,
      reviewCount: reviewCountSql,
    })
    .from(schema.guides)
    .innerJoin(schema.users, eq(schema.users.id, schema.guides.ownerId))
    .where(eq(schema.guides.slug, slug))
    .limit(1);

  const head = row[0];
  if (!head) return c.json({ error: 'not found' }, 404);
  if (!canViewGuide(head, user?.id)) return c.json({ error: 'not found' }, 404);

  return c.json({
    id: head.id,
    slug: head.slug,
    ownerId: head.ownerId,
    ownerName: head.ownerName,
    ownerImage: head.ownerImage,
    title: head.title,
    summary: head.summary,
    body: head.body,
    imageUrl: head.imageUrl,
    screenshots: head.screenshots ?? [],
    status: head.status,
    rating: head.rating,
    reviewCount: head.reviewCount,
    createdAt: head.createdAt.toISOString(),
    updatedAt: head.updatedAt.toISOString(),
  });
});

guidesRouter.patch(
  '/:slug',
  writeLimiter,
  zValidator('param', slugParamSchema),
  zValidator('json', guidePatchSchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    const { slug } = c.req.valid('param');
    const body = c.req.valid('json');
    const db = getDb();

    const existing = await db.query.guides.findFirst({ where: eq(schema.guides.slug, slug) });
    if (!existing) return c.json({ error: 'not found' }, 404);
    if (existing.ownerId !== user.id) return c.json({ error: 'forbidden' }, 403);

    const updates: Record<string, unknown> = { updatedAt: new Date() };
    if (body.title !== undefined) updates.title = body.title;
    if (body.summary !== undefined) updates.summary = body.summary;
    if (body.body !== undefined) updates.body = body.body;
    if (body.imageUrl !== undefined) updates.imageUrl = body.imageUrl;
    if (body.screenshots !== undefined) updates.screenshots = body.screenshots;
    // Author transitions only: submit (draft/rejected -> pending) or withdraw
    // (pending -> draft). Approval is admin-only via /approve.
    if (body.status !== undefined) updates.status = body.status;

    await db.update(schema.guides).set(updates).where(eq(schema.guides.id, existing.id));
    return c.json({ ok: true });
  },
);

guidesRouter.delete('/:slug', writeLimiter, zValidator('param', slugParamSchema), async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const { slug } = c.req.valid('param');
  const db = getDb();
  const existing = await db.query.guides.findFirst({ where: eq(schema.guides.slug, slug) });
  if (!existing) return c.json({ error: 'not found' }, 404);
  if (existing.ownerId !== user.id && !isAdmin(user.id)) {
    return c.json({ error: 'forbidden' }, 403);
  }
  await db.delete(schema.guides).where(eq(schema.guides.id, existing.id));
  return c.json({ ok: true });
});

// ─────────── Moderation (admins) ───────────

async function setStatus(slug: string, status: 'approved' | 'rejected', userId: string) {
  const db = getDb();
  if (!isAdmin(userId)) return { code: 403 as const };
  const existing = await db.query.guides.findFirst({ where: eq(schema.guides.slug, slug) });
  if (!existing) return { code: 404 as const };
  await db
    .update(schema.guides)
    .set({ status, updatedAt: new Date() })
    .where(eq(schema.guides.id, existing.id));
  return { code: 200 as const };
}

guidesRouter.post(
  '/:slug/approve',
  writeLimiter,
  zValidator('param', slugParamSchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    const { slug } = c.req.valid('param');
    const r = await setStatus(slug, 'approved', user.id);
    if (r.code === 403) return c.json({ error: 'forbidden' }, 403);
    if (r.code === 404) return c.json({ error: 'not found' }, 404);
    return c.json({ ok: true });
  },
);

guidesRouter.post(
  '/:slug/reject',
  writeLimiter,
  zValidator('param', slugParamSchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    const { slug } = c.req.valid('param');
    const r = await setStatus(slug, 'rejected', user.id);
    if (r.code === 403) return c.json({ error: 'forbidden' }, 403);
    if (r.code === 404) return c.json({ error: 'not found' }, 404);
    return c.json({ ok: true });
  },
);

guidesRouter.post(
  '/:slug/image',
  writeLimiter,
  zValidator('param', slugParamSchema),
  zValidator('json', guideImagePresignSchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    if (!s3Configured()) return c.json({ error: 'object storage not configured' }, 503);
    const { slug } = c.req.valid('param');
    const body = c.req.valid('json');
    const db = getDb();
    const existing = await db.query.guides.findFirst({ where: eq(schema.guides.slug, slug) });
    if (!existing) return c.json({ error: 'not found' }, 404);
    if (existing.ownerId !== user.id) return c.json({ error: 'forbidden' }, 403);

    const signed = await presignGuideImage({
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

// ─────────── Guide Reviews ───────────

const reviewLimiter = createRateLimiter({
  name: 'guide-review',
  windowMs: 60_000,
  maxHits: 10,
  keyFrom: (c) => {
    const user = c.get('user');
    return (
      user?.id ??
      c.req.header('x-real-ip') ??
      c.req.header('x-forwarded-for')?.split(',').pop()?.trim() ??
      'anon'
    );
  },
});

guidesRouter.get('/:slug/reviews', zValidator('param', slugParamSchema), async (c) => {
  const { slug } = c.req.valid('param');
  const user = c.get('user');
  const db = getDb();
  const guide = await db.query.guides.findFirst({ where: eq(schema.guides.slug, slug) });
  if (!guide) return c.json({ error: 'not found' }, 404);
  if (!canViewGuide(guide, user?.id)) return c.json({ error: 'not found' }, 404);

  const rows = await db
    .select({
      id: schema.guideReviews.id,
      guideId: schema.guideReviews.guideId,
      userId: schema.guideReviews.userId,
      rating: schema.guideReviews.rating,
      title: schema.guideReviews.title,
      body: schema.guideReviews.body,
      createdAt: schema.guideReviews.createdAt,
      updatedAt: schema.guideReviews.updatedAt,
      userName: schema.users.name,
      userImage: schema.users.image,
    })
    .from(schema.guideReviews)
    .innerJoin(schema.users, eq(schema.users.id, schema.guideReviews.userId))
    .where(eq(schema.guideReviews.guideId, guide.id))
    .orderBy(desc(schema.guideReviews.updatedAt));

  const items = rows.map((r) => ({
    id: r.id,
    guideId: r.guideId,
    userId: r.userId,
    userName: r.userName,
    userImage: r.userImage,
    rating: r.rating,
    title: r.title,
    body: r.body,
    createdAt: r.createdAt.toISOString(),
    updatedAt: r.updatedAt.toISOString(),
  }));
  const average = items.length ? items.reduce((s, r) => s + r.rating, 0) / items.length : null;
  return c.json({ items, total: items.length, averageRating: average });
});

guidesRouter.use('/:slug/reviews', reviewLimiter);
guidesRouter.put(
  '/:slug/reviews',
  zValidator('param', slugParamSchema),
  zValidator('json', guideReviewUpsertSchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    const { slug } = c.req.valid('param');
    const body = c.req.valid('json');
    const db = getDb();
    const guide = await db.query.guides.findFirst({ where: eq(schema.guides.slug, slug) });
    if (!guide) return c.json({ error: 'not found' }, 404);
    if (!canViewGuide(guide, user.id)) return c.json({ error: 'not found' }, 404);
    if (guide.ownerId === user.id) {
      return c.json({ error: 'authors cannot review their own guide' }, 400);
    }

    const now = new Date();
    await db
      .insert(schema.guideReviews)
      .values({
        guideId: guide.id,
        userId: user.id,
        rating: body.rating,
        title: body.title ?? null,
        body: body.body ?? null,
        updatedAt: now,
      })
      .onConflictDoUpdate({
        target: [schema.guideReviews.guideId, schema.guideReviews.userId],
        set: {
          rating: body.rating,
          title: body.title ?? null,
          body: body.body ?? null,
          updatedAt: now,
        },
      });
    return c.json({ ok: true });
  },
);

guidesRouter.delete('/:slug/reviews', zValidator('param', slugParamSchema), async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const { slug } = c.req.valid('param');
  const db = getDb();
  const guide = await db.query.guides.findFirst({ where: eq(schema.guides.slug, slug) });
  if (!guide) return c.json({ error: 'not found' }, 404);
  await db
    .delete(schema.guideReviews)
    .where(and(eq(schema.guideReviews.guideId, guide.id), eq(schema.guideReviews.userId, user.id)));
  return c.json({ ok: true });
});
