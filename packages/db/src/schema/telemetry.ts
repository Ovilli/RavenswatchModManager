import {
  boolean,
  index,
  integer,
  jsonb,
  pgTable,
  text,
  timestamp,
  uuid,
  varchar,
} from 'drizzle-orm/pg-core';
import { users } from './auth';

export const telemetryRuns = pgTable(
  'telemetry_runs',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    userId: text('user_id').references(() => users.id, { onDelete: 'set null' }),
    rsmmVersion: varchar('rsmm_version', { length: 32 }).notNull(),
    os: varchar('os', { length: 16 }).notNull(),
    gameBuild: varchar('game_build', { length: 64 }),
    ok: boolean('ok').notNull(),
    durationMs: integer('duration_ms'),
    payload: jsonb('payload'),
    createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    createdIdx: index('telemetry_runs_created_idx').on(table.createdAt),
    okIdx: index('telemetry_runs_ok_idx').on(table.ok),
  }),
);

export const crashReports = pgTable(
  'crash_reports',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    userId: text('user_id').references(() => users.id, { onDelete: 'set null' }),
    rsmmVersion: varchar('rsmm_version', { length: 32 }).notNull(),
    os: varchar('os', { length: 16 }).notNull(),
    errorClass: varchar('error_class', { length: 128 }).notNull(),
    message: text('message').notNull(),
    stacktrace: text('stacktrace').notNull(),
    context: jsonb('context'),
    createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    createdIdx: index('crash_reports_created_idx').on(table.createdAt),
    classIdx: index('crash_reports_class_idx').on(table.errorClass),
  }),
);

/**
 * User-initiated diagnostic log shares.
 *
 * Distinct from `crashReports` in both direction and consent: a crash report
 * is pushed automatically and gated on the account's `crashReportLevel`, while
 * a share is an explicit "upload this and give me a link" action, so it is
 * stored on the strength of that action alone. Rows expire — `expiresAt` is
 * set at write time and the retention cron deletes past it — because a support
 * link is useful for days, not forever.
 *
 * `id` is the URL slug (random, unguessable): the viewer is unlisted rather
 * than access-controlled, so an anonymous uploader can still hand the link to
 * whoever is helping them.
 */
export const sharedLogs = pgTable(
  'shared_logs',
  {
    id: varchar('id', { length: 32 }).primaryKey(),
    userId: text('user_id').references(() => users.id, { onDelete: 'set null' }),
    source: varchar('source', { length: 16 }).notNull(),
    rsmmVersion: varchar('rsmm_version', { length: 32 }).notNull(),
    os: varchar('os', { length: 16 }).notNull(),
    content: text('content').notNull(),
    meta: jsonb('meta'),
    bytes: integer('bytes').notNull(),
    lineCount: integer('line_count').notNull(),
    views: integer('views').notNull().default(0),
    createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
    expiresAt: timestamp('expires_at', { withTimezone: true }).notNull(),
  },
  (table) => ({
    expiresIdx: index('shared_logs_expires_idx').on(table.expiresAt),
    userIdx: index('shared_logs_user_idx').on(table.userId),
  }),
);
