import { z } from 'zod';

export const reviewRatingSchema = z.number().int().min(1).max(5);

export const reviewSchema = z.object({
  id: z.string().uuid(),
  modId: z.string().uuid(),
  userId: z.string(),
  userName: z.string().nullable(),
  userImage: z.string().nullable(),
  rating: reviewRatingSchema,
  title: z.string().max(120).nullable(),
  body: z.string().nullable(),
  ownerReply: z.string().nullable().optional(),
  ownerReplyAt: z.string().datetime().nullable().optional(),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime(),
});

export type Review = z.infer<typeof reviewSchema>;

export const reviewUpsertSchema = z.object({
  rating: reviewRatingSchema,
  title: z.string().max(120).optional().nullable(),
  body: z.string().max(4000).optional().nullable(),
});

export type ReviewUpsert = z.infer<typeof reviewUpsertSchema>;

export const reviewReplySchema = z.object({
  body: z.string().trim().min(1).max(2000),
});

export type ReviewReply = z.infer<typeof reviewReplySchema>;

export const reviewsResponseSchema = z.object({
  items: z.array(reviewSchema),
  total: z.number().int().nonnegative(),
  averageRating: z.number().min(0).max(5).nullable(),
});
