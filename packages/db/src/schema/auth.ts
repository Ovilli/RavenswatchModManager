import { boolean, pgTable, text, timestamp, varchar } from 'drizzle-orm/pg-core';

// Better Auth core tables. Names and columns match Better Auth defaults.
export const users = pgTable('user', {
  id: text('id').primaryKey(),
  name: text('name').notNull(),
  email: text('email').notNull().unique(),
  emailVerified: boolean('email_verified').notNull().default(false),
  image: text('image'),
  handle: text('handle').unique(),
  // Moderation: a banned user's session is nulled out by the API session
  // middleware (apps/api/src/app.ts) so they can neither publish nor act.
  banned: boolean('banned').notNull().default(false),
  bannedReason: text('banned_reason'),
  // ─── Privacy preferences ───
  // Account-level and server-enforced, not a client-side courtesy: the
  // telemetry routes read these before writing a row, so a modified or
  // out-of-date client cannot store more than the account allows. Shape and
  // semantics live in `@rsmm/schemas` (privacySettingsSchema) — 'off' drops the
  // submission, 'anonymous' stores it with user_id NULL, 'linked' keeps the id.
  telemetryLevel: varchar('telemetry_level', { length: 16 }).notNull().default('anonymous'),
  crashReportLevel: varchar('crash_report_level', { length: 16 }).notNull().default('anonymous'),
  // Hide the /u/<id> profile and the display name shown beside owned mods.
  publicProfile: boolean('public_profile').notNull().default(true),
  // Hide per-mod download counts on the public page. Aggregates still count them.
  publicDownloadCounts: boolean('public_download_counts').notNull().default(true),
  // Non-essential mail. Defaults to false: marketing consent is opt-in.
  emailAnnouncements: boolean('email_announcements').notNull().default(false),
  createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp('updated_at', { withTimezone: true }).notNull().defaultNow(),
});

export const sessions = pgTable('session', {
  id: text('id').primaryKey(),
  userId: text('user_id')
    .notNull()
    .references(() => users.id, { onDelete: 'cascade' }),
  token: text('token').notNull().unique(),
  expiresAt: timestamp('expires_at', { withTimezone: true }).notNull(),
  ipAddress: text('ip_address'),
  userAgent: text('user_agent'),
  createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp('updated_at', { withTimezone: true }).notNull().defaultNow(),
});

export const accounts = pgTable('account', {
  id: text('id').primaryKey(),
  userId: text('user_id')
    .notNull()
    .references(() => users.id, { onDelete: 'cascade' }),
  accountId: text('account_id').notNull(),
  providerId: text('provider_id').notNull(),
  accessToken: text('access_token'),
  refreshToken: text('refresh_token'),
  idToken: text('id_token'),
  accessTokenExpiresAt: timestamp('access_token_expires_at', { withTimezone: true }),
  refreshTokenExpiresAt: timestamp('refresh_token_expires_at', { withTimezone: true }),
  scope: text('scope'),
  password: text('password'),
  createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp('updated_at', { withTimezone: true }).notNull().defaultNow(),
});

export const verifications = pgTable('verification', {
  id: text('id').primaryKey(),
  identifier: text('identifier').notNull(),
  value: text('value').notNull(),
  expiresAt: timestamp('expires_at', { withTimezone: true }).notNull(),
  createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp('updated_at', { withTimezone: true }).notNull().defaultNow(),
});
