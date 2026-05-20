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
