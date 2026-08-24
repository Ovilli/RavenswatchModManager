import { z } from 'zod';

/**
 * How much a signed-in user lets one telemetry stream carry.
 *
 *   off       — the API discards the submission; nothing is stored at all.
 *   anonymous — the row is stored with `user_id` NULL, so it still counts
 *               toward aggregate health/usage figures but cannot be traced
 *               back to the account.
 *   linked    — the row keeps `user_id`, so a maintainer can follow up on a
 *               specific crash with the person who hit it.
 *
 * `anonymous` is the default: useful in aggregate, not personal data.
 */
export const telemetryLevelSchema = z.enum(['off', 'anonymous', 'linked']);
export type TelemetryLevel = z.infer<typeof telemetryLevelSchema>;

export const TELEMETRY_LEVEL_DEFAULT: TelemetryLevel = 'anonymous';

export const privacySettingsSchema = z.object({
  /** Usage pings: which RSMM version, OS, whether an apply succeeded. */
  telemetryLevel: telemetryLevelSchema,
  /** Unhandled errors and stack traces from the desktop client. */
  crashReportLevel: telemetryLevelSchema,
  /** Appear on /u/<id> and have your display name shown next to your mods. */
  publicProfile: z.boolean(),
  /** Show per-mod download counts on the public page for mods you own. */
  publicDownloadCounts: z.boolean(),
  /**
   * Non-essential email — release announcements and similar. Opt-IN by
   * default-false: consent to marketing mail has to be given, not withdrawn.
   * Security, password-reset and moderation mail is transactional and always
   * sends regardless of this flag.
   */
  emailAnnouncements: z.boolean(),
});
export type PrivacySettings = z.infer<typeof privacySettingsSchema>;

/** PATCH body — every field optional, so the UI can send one toggle at a time. */
export const privacySettingsUpdateSchema = privacySettingsSchema
  .partial()
  .refine((v) => Object.keys(v).length > 0, 'at least one field must be provided');
export type PrivacySettingsUpdate = z.infer<typeof privacySettingsUpdateSchema>;

export const PRIVACY_DEFAULTS: PrivacySettings = {
  telemetryLevel: TELEMETRY_LEVEL_DEFAULT,
  crashReportLevel: TELEMETRY_LEVEL_DEFAULT,
  publicProfile: true,
  publicDownloadCounts: true,
  emailAnnouncements: false,
};
