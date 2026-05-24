import { z } from 'zod';
import { modListItemSchema, modSlugSchema } from './mod';

export const collectionSlugSchema = z
  .string()
  .min(2)
  .max(64)
  .regex(/^[a-z0-9][a-z0-9-_]*$/, 'lowercase alphanumeric with -_');

const screenshotSchema = z.object({
  url: z.string().url(),
  caption: z.string().max(200).optional(),
});

export const collectionSchema = z.object({
  id: z.string().uuid(),
  slug: collectionSlugSchema,
  ownerId: z.string(),
  ownerName: z.string().nullable(),
  ownerImage: z.string().nullable(),
  name: z.string(),
  summary: z.string().nullable(),
  description: z.string().nullable(),
  imageUrl: z.string().url().nullable(),
  screenshots: z.array(screenshotSchema).optional(),
  isPublic: z.boolean(),
  modCount: z.number().int().nonnegative(),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime(),
});

export type Collection = z.infer<typeof collectionSchema>;

export const collectionDetailSchema = collectionSchema.extend({
  mods: z.array(modListItemSchema),
});

export type CollectionDetail = z.infer<typeof collectionDetailSchema>;

export const collectionCreateSchema = z.object({
  slug: collectionSlugSchema,
  name: z.string().min(1).max(128),
  summary: z.string().max(512).nullable().optional(),
  description: z.string().optional(),
  imageUrl: z.string().url().nullable().optional(),
  screenshots: z.array(screenshotSchema).optional(),
  isPublic: z.boolean().optional(),
});

export type CollectionCreate = z.infer<typeof collectionCreateSchema>;

export const collectionPatchSchema = z.object({
  name: z.string().min(1).max(128).optional(),
  summary: z.string().max(512).nullable().optional(),
  description: z.string().nullable().optional(),
  imageUrl: z.string().url().nullable().optional(),
  screenshots: z.array(screenshotSchema).optional(),
  isPublic: z.boolean().optional(),
});

export type CollectionPatch = z.infer<typeof collectionPatchSchema>;

export const collectionAddModSchema = z.object({
  modSlug: modSlugSchema,
});

export type CollectionAddMod = z.infer<typeof collectionAddModSchema>;

export const collectionImagePresignSchema = z.object({
  contentType: z.enum(['image/png', 'image/jpeg', 'image/webp']),
  sizeBytes: z.number().int().positive(),
});

export type CollectionImagePresign = z.infer<typeof collectionImagePresignSchema>;

export const collectionReviewSchema = z.object({
  id: z.string().uuid(),
  collectionId: z.string().uuid(),
  userId: z.string(),
  userName: z.string().nullable(),
  userImage: z.string().nullable(),
  rating: z.number().int().min(1).max(5),
  title: z.string().max(120).nullable(),
  body: z.string().nullable(),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime(),
});

export type CollectionReview = z.infer<typeof collectionReviewSchema>;

export const collectionReviewUpsertSchema = z.object({
  rating: z.number().int().min(1).max(5),
  title: z.string().max(120).nullable().optional(),
  body: z.string().nullable().optional(),
});

export type CollectionReviewUpsert = z.infer<typeof collectionReviewUpsertSchema>;

export const collectionReviewsResponseSchema = z.object({
  items: z.array(collectionReviewSchema),
  total: z.number().int().nonnegative(),
  averageRating: z.number().min(0).max(5).nullable(),
});
