import { z } from 'zod';
import { modListItemSchema, modSlugSchema } from './mod';

export const collectionSlugSchema = z
  .string()
  .min(2)
  .max(64)
  .regex(/^[a-z0-9][a-z0-9-_]*$/, 'lowercase alphanumeric with -_');

export const collectionSchema = z.object({
  id: z.string().uuid(),
  slug: collectionSlugSchema,
  ownerId: z.string(),
  ownerName: z.string().nullable(),
  ownerImage: z.string().nullable(),
  name: z.string(),
  summary: z.string().nullable(),
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
  isPublic: z.boolean().optional(),
});

export type CollectionCreate = z.infer<typeof collectionCreateSchema>;

export const collectionPatchSchema = z.object({
  name: z.string().min(1).max(128).optional(),
  summary: z.string().max(512).nullable().optional(),
  isPublic: z.boolean().optional(),
});

export type CollectionPatch = z.infer<typeof collectionPatchSchema>;

export const collectionAddModSchema = z.object({
  modSlug: modSlugSchema,
});

export type CollectionAddMod = z.infer<typeof collectionAddModSchema>;
