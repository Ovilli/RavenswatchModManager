import { z } from 'zod';

/** Create a personal API token. The plaintext comes back once, in the response. */
export const apiTokenCreateSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1)
    .max(64)
    // Printable text only: the name is shown back in lists and in the security
    // notice email, so control characters have no business in it.
    .regex(/^[^\p{Cc}]+$/u, 'name must be printable text'),
  expiresInDays: z.number().int().min(1).max(365).default(90),
});

export type ApiTokenCreate = z.infer<typeof apiTokenCreateSchema>;

/** A token as listed back to its owner. Never carries the secret. */
export const apiTokenSummarySchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  prefix: z.string(),
  createdAt: z.string(),
  expiresAt: z.string(),
  lastUsedAt: z.string().nullable(),
  revokedAt: z.string().nullable(),
});

export type ApiTokenSummary = z.infer<typeof apiTokenSummarySchema>;

export const apiTokenCreatedSchema = apiTokenSummarySchema.extend({
  /** The plaintext token. Returned exactly once; the server keeps only a hash. */
  token: z.string().startsWith('rsmm_pat_'),
});

export type ApiTokenCreated = z.infer<typeof apiTokenCreatedSchema>;
