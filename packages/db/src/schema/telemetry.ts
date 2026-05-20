import { boolean, index, integer, jsonb, pgTable, text, timestamp, uuid, varchar } from 'drizzle-orm/pg-core';
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
