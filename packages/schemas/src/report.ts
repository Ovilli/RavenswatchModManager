import { z } from 'zod';

export const reportReasonSchema = z.enum([
  'malware',
  'stolen',
  'broken',
  'inappropriate',
  'spam',
  'other',
]);
export type ReportReason = z.infer<typeof reportReasonSchema>;

export const reportStatusSchema = z.enum(['open', 'reviewing', 'resolved', 'dismissed']);
export type ReportStatus = z.infer<typeof reportStatusSchema>;

/** Body a user submits to file a report against a mod. */
export const reportCreateSchema = z.object({
  reason: reportReasonSchema,
  detail: z.string().max(2000).optional().nullable(),
});
export type ReportCreate = z.infer<typeof reportCreateSchema>;

/** Body an admin submits to triage a report. */
export const reportResolveSchema = z.object({
  status: reportStatusSchema,
  resolutionNote: z.string().max(2000).optional().nullable(),
});
export type ReportResolve = z.infer<typeof reportResolveSchema>;

/** Body an admin submits to take a mod down (or restore). */
export const modTakedownSchema = z.object({
  takedownStatus: z.enum(['active', 'hidden', 'removed']),
  reason: z.string().max(2000).optional().nullable(),
});
export type ModTakedown = z.infer<typeof modTakedownSchema>;

/** Body an admin submits to ban (or unban) a user. */
export const userBanSchema = z.object({
  banned: z.boolean(),
  reason: z.string().max(2000).optional().nullable(),
});
export type UserBan = z.infer<typeof userBanSchema>;
