import { z } from 'zod';

export const userSchema = z.object({
  id: z.string(),
  email: z.string().email(),
  handle: z.string().min(2).max(32).nullable(),
  emailVerified: z.boolean(),
  image: z.string().url().nullable(),
  createdAt: z.string().datetime(),
});

export type User = z.infer<typeof userSchema>;
