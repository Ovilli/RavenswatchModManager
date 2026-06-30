import { z } from 'zod';

export const guideSlugSchema = z
  .string()
  .min(2)
  .max(80)
  .regex(/^[a-z0-9][a-z0-9-_]*$/, 'lowercase alphanumeric with -_');

// draft  — author is still writing (private to owner)
// pending — author submitted for review (visible to owner + admins)
// approved — a maintainer approved it (public, indexed, may show ads)
// rejected — a maintainer declined it (private to owner, can resubmit)
export const guideStatusSchema = z.enum(['draft', 'pending', 'approved', 'rejected']);
export type GuideStatus = z.infer<typeof guideStatusSchema>;

const screenshotSchema = z.object({
  url: z.string().url(),
  caption: z.string().max(200).optional(),
});

export const guideSchema = z.object({
  id: z.string().uuid(),
  slug: guideSlugSchema,
  ownerId: z.string(),
  ownerName: z.string().nullable(),
  ownerImage: z.string().nullable(),
  title: z.string(),
  summary: z.string().nullable(),
  body: z.string(),
  imageUrl: z.string().url().nullable(),
  screenshots: z.array(screenshotSchema).optional(),
  status: guideStatusSchema,
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime(),
});

export type Guide = z.infer<typeof guideSchema>;

export const guideListItemSchema = guideSchema.extend({
  rating: z.number().min(0).max(5).nullable(),
  reviewCount: z.number().int().nonnegative(),
});

export type GuideListItem = z.infer<typeof guideListItemSchema>;

export const guideCreateSchema = z.object({
  slug: guideSlugSchema,
  title: z.string().min(1).max(160),
  summary: z.string().max(512).nullable().optional(),
  body: z.string().min(1).max(100_000),
  imageUrl: z.string().url().nullable().optional(),
  screenshots: z.array(screenshotSchema).optional(),
});

export type GuideCreate = z.infer<typeof guideCreateSchema>;

export const guidePatchSchema = z.object({
  title: z.string().min(1).max(160).optional(),
  summary: z.string().max(512).nullable().optional(),
  body: z.string().min(1).max(100_000).optional(),
  imageUrl: z.string().url().nullable().optional(),
  screenshots: z.array(screenshotSchema).optional(),
  // Author-initiated transitions only (draft <-> pending). Admin approval
  // uses the dedicated review endpoint, not this patch.
  status: z.enum(['draft', 'pending']).optional(),
});

export type GuidePatch = z.infer<typeof guidePatchSchema>;

export const guideReviewSchema = z.object({
  id: z.string().uuid(),
  guideId: z.string().uuid(),
  userId: z.string(),
  userName: z.string().nullable(),
  userImage: z.string().nullable(),
  rating: z.number().int().min(1).max(5),
  title: z.string().max(120).nullable(),
  body: z.string().nullable(),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime(),
});

export type GuideReview = z.infer<typeof guideReviewSchema>;

export const guideReviewUpsertSchema = z.object({
  rating: z.number().int().min(1).max(5),
  title: z.string().max(120).nullable().optional(),
  body: z.string().nullable().optional(),
});

export type GuideReviewUpsert = z.infer<typeof guideReviewUpsertSchema>;

export const guideReviewsResponseSchema = z.object({
  items: z.array(guideReviewSchema),
  total: z.number().int().nonnegative(),
  averageRating: z.number().min(0).max(5).nullable(),
});

export const guideImagePresignSchema = z.object({
  contentType: z.enum(['image/png', 'image/jpeg', 'image/webp']),
  sizeBytes: z.number().int().positive().max(8_000_000),
});

export type GuideImagePresign = z.infer<typeof guideImagePresignSchema>;
