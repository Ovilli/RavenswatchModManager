import { z } from 'zod';

export const modSlugSchema = z
  .string()
  .min(2)
  .max(64)
  .regex(/^[a-z0-9][a-z0-9-_]*$/, 'lowercase alphanumeric with -_');

export const semverSchema = z
  .string()
  .regex(/^\d+\.\d+\.\d+(?:[-+][\w.]+)?$/, 'semver x.y.z');

export const modManifestSchema = z.object({
  id: modSlugSchema,
  name: z.string().min(1).max(128),
  version: semverSchema,
  author: z.string().min(1).max(128).optional(),
  summary: z.string().max(512).optional(),
  description: z.string().max(8192).optional(),
  license: z.string().max(64).optional(),
  repo_url: z.string().url().optional(),
  homepage_url: z.string().url().optional(),
  tags: z.array(z.string().max(32)).max(16).optional(),
  enabled: z.boolean().optional(),
  dependencies: z.record(z.string(), semverSchema).optional(),
});

export type ModManifest = z.infer<typeof modManifestSchema>;

export const modCategorySchema = z.enum([
  'gameplay',
  'balance',
  'cosmetic',
  'qol',
  'audio',
  'difficulty',
  'speedrun',
  'utility',
]);

export type ModCategory = z.infer<typeof modCategorySchema>;

export const modListItemSchema = z.object({
  id: z.string().uuid(),
  slug: modSlugSchema,
  name: z.string(),
  author: z.string().nullable(),
  summary: z.string().nullable(),
  license: z.string().nullable(),
  latestVersion: semverSchema.nullable(),
  downloads: z.number().int().nonnegative(),
  updatedAt: z.string().datetime(),
  category: modCategorySchema.nullable(),
  imageUrl: z.string().url().nullable(),
  rating: z.number().min(0).max(5).nullable(),
  tags: z.array(z.string()),
  screenshots: z.array(z.string()).optional(),
  videos: z.array(z.string()).optional(),
});

export type ModListItem = z.infer<typeof modListItemSchema>;

export const modVersionSchema = z.object({
  id: z.string().uuid(),
  modId: z.string().uuid(),
  version: semverSchema,
  sha256: z.string().regex(/^[a-f0-9]{64}$/),
  sizeBytes: z.number().int().positive(),
  manifestJson: modManifestSchema,
  assetUrl: z.string().url(),
  createdAt: z.string().datetime(),
});

export type ModVersion = z.infer<typeof modVersionSchema>;

export const modUploadRequestSchema = z.object({
  slug: modSlugSchema,
  version: semverSchema,
  manifest: modManifestSchema,
  sha256: z.string().regex(/^[a-f0-9]{64}$/),
  sizeBytes: z.number().int().positive(),
});

export type ModUploadRequest = z.infer<typeof modUploadRequestSchema>;

/** Owner-only patch: edit mutable metadata. All fields optional. */
export const modPatchSchema = z.object({
  name: z.string().min(1).max(128).optional(),
  summary: z.string().max(512).nullable().optional(),
  description: z.string().max(32_000).nullable().optional(),
  license: z.string().max(64).nullable().optional(),
  repoUrl: z.string().url().nullable().optional(),
  homepageUrl: z.string().url().nullable().optional(),
  category: modCategorySchema.nullable().optional(),
  tags: z.array(z.string().max(32)).max(16).optional(),
  imageUrl: z.string().url().nullable().optional(),
  screenshots: z.array(z.string().url()).max(12).optional(),
  videos: z.array(z.string().url()).max(8).optional(),
});

export type ModPatch = z.infer<typeof modPatchSchema>;

/** Owner-only: presign a new version upload. Changelog is per-version. */
export const modVersionCreateSchema = z.object({
  version: semverSchema,
  sha256: z.string().regex(/^[a-f0-9]{64}$/),
  sizeBytes: z.number().int().positive(),
  manifest: modManifestSchema,
  changelog: z.string().max(16_000).optional(),
});

export type ModVersionCreate = z.infer<typeof modVersionCreateSchema>;

/** Owner-only: presign a cover-image upload. */
export const modImagePresignSchema = z.object({
  contentType: z.enum(['image/png', 'image/jpeg', 'image/webp']),
  sizeBytes: z
    .number()
    .int()
    .positive()
    .max(8_000_000, 'image must be ≤ 8 MB'),
});

export type ModImagePresign = z.infer<typeof modImagePresignSchema>;
