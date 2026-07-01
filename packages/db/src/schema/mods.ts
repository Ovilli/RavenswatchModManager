import { relations, sql } from 'drizzle-orm';
import {
  bigint,
  boolean,
  date,
  index,
  integer,
  jsonb,
  numeric,
  pgEnum,
  pgTable,
  primaryKey,
  text,
  timestamp,
  uniqueIndex,
  uuid,
  varchar,
} from 'drizzle-orm/pg-core';
import { users } from './auth';

export const modCategoryEnum = pgEnum('mod_category', [
  'gameplay',
  'balance',
  'cosmetic',
  'qol',
  'audio',
  'difficulty',
  'speedrun',
  'utility',
]);

export const mods = pgTable(
  'mods',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    slug: varchar('slug', { length: 64 }).notNull(),
    name: text('name').notNull(),
    summary: text('summary'),
    description: text('description'),
    license: varchar('license', { length: 64 }),
    repoUrl: text('repo_url'),
    homepageUrl: text('homepage_url'),
    tags: text('tags').array(),
    category: modCategoryEnum('category'),
    authorName: varchar('author_name', { length: 128 }),
    imageUrl: text('image_url'),
    // Array of { url, caption? } objects. Used to be text[]; the JSONB
    // form lets us attach captions per screenshot without a join table.
    screenshots: jsonb('screenshots').$type<{ url: string; caption?: string }[]>(),
    videos: text('videos').array(),
    rating: numeric('rating', { precision: 3, scale: 2 }),
    ownerId: text('owner_id').references(() => users.id, { onDelete: 'set null' }),
    featured: boolean('featured').notNull().default(false),
    featuredAt: timestamp('featured_at', { withTimezone: true }),
    nsfw: boolean('nsfw').notNull().default(false),
    // Admin moderation gate, independent of the per-version malware scan.
    //   active  — normal, publicly listed/downloadable
    //   hidden  — delisted but kept (owner/admin can still see it)
    //   removed — taken down (e.g. DMCA / malware / stolen assets)
    // The public list/detail/download routes serve only 'active' mods.
    takedownStatus: varchar('takedown_status', { length: 16 }).notNull().default('active'),
    takedownReason: text('takedown_reason'),
    createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp('updated_at', { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    slugIdx: uniqueIndex('mods_slug_idx').on(table.slug),
    ownerIdx: index('mods_owner_idx').on(table.ownerId),
    categoryIdx: index('mods_category_idx').on(table.category),
    featuredIdx: index('mods_featured_idx').on(table.featured),
    takedownIdx: index('mods_takedown_idx').on(table.takedownStatus),
  }),
);

export const modVersions = pgTable(
  'mod_versions',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    modId: uuid('mod_id')
      .notNull()
      .references(() => mods.id, { onDelete: 'cascade' }),
    version: varchar('version', { length: 32 }).notNull(),
    sha256: varchar('sha256', { length: 64 }).notNull(),
    sizeBytes: bigint('size_bytes', { mode: 'number' }).notNull(),
    manifestJson: jsonb('manifest_json').notNull(),
    assetUrl: text('asset_url').notNull(),
    changelog: text('changelog'),
    createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
    // Malware-scan gate (VirusTotal). FAIL-CLOSED: the public gate serves a
    // version ONLY when scan_status is 'clean' or 'skipped' (see
    // scan-service.ts::isServable). Everything else is withheld, so freshly
    // uploaded bytes are never downloadable before a scan clears.
    //   queued   — waiting for the in-process scan worker to pick it up (withheld)
    //   pending  — submitted, verdict not yet resolved (withheld, HTTP 409)
    //   clean    — VT analysis completed, no detections (servable)
    //   flagged  — VT reported malicious/suspicious > 0 (withheld, HTTP 451; S3 object deleted)
    //   skipped  — scanning not configured on this server (servable)
    //   error    — submission/poll failed (withheld; rescan loop retries)
    scanStatus: varchar('scan_status', { length: 16 }).notNull().default('pending'),
    scanId: text('scan_id'),
    scanStats: jsonb('scan_stats').$type<Record<string, number>>(),
    // When the version entered the scan queue — drives FIFO drain order and the
    // "position N in queue" the publish UI shows.
    scanQueuedAt: timestamp('scan_queued_at', { withTimezone: true }),
    scannedAt: timestamp('scanned_at', { withTimezone: true }),
  },
  (table) => ({
    modVersionIdx: uniqueIndex('mod_versions_mod_version_idx').on(table.modId, table.version),
  }),
);

export const modAuthors = pgTable(
  'mod_authors',
  {
    modId: uuid('mod_id')
      .notNull()
      .references(() => mods.id, { onDelete: 'cascade' }),
    userId: text('user_id')
      .notNull()
      .references(() => users.id, { onDelete: 'cascade' }),
    role: varchar('role', { length: 16 }).notNull().default('contrib'),
    createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    pk: primaryKey({ columns: [table.modId, table.userId] }),
  }),
);

export const modDownloads = pgTable(
  'mod_downloads',
  {
    modId: uuid('mod_id')
      .notNull()
      .references(() => mods.id, { onDelete: 'cascade' }),
    versionId: uuid('version_id').references(() => modVersions.id, {
      onDelete: 'set null',
    }),
    day: date('day').notNull().default(sql`CURRENT_DATE`),
    count: integer('count').notNull().default(0),
  },
  (table) => ({
    pk: primaryKey({ columns: [table.modId, table.day] }),
  }),
);

export const modReviews = pgTable(
  'mod_reviews',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    modId: uuid('mod_id')
      .notNull()
      .references(() => mods.id, { onDelete: 'cascade' }),
    userId: text('user_id')
      .notNull()
      .references(() => users.id, { onDelete: 'cascade' }),
    rating: integer('rating').notNull(),
    title: varchar('title', { length: 120 }),
    body: text('body'),
    createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp('updated_at', { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    modUserIdx: uniqueIndex('mod_reviews_mod_user_idx').on(table.modId, table.userId),
    modIdx: index('mod_reviews_mod_idx').on(table.modId),
  }),
);

export const modReportReasonEnum = pgEnum('mod_report_reason', [
  'malware',
  'stolen',
  'broken',
  'inappropriate',
  'spam',
  'other',
]);

// User-submitted reports against a mod. Triaged by admins in the moderation
// console (apps/api/src/routes/reports.ts). Anonymous reports are allowed
// (reporterId nullable) so a logged-out user can still flag malware.
export const modReports = pgTable(
  'mod_reports',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    modId: uuid('mod_id')
      .notNull()
      .references(() => mods.id, { onDelete: 'cascade' }),
    reporterId: text('reporter_id').references(() => users.id, { onDelete: 'set null' }),
    reason: modReportReasonEnum('reason').notNull(),
    detail: text('detail'),
    // open → reviewing → resolved | dismissed
    status: varchar('status', { length: 16 }).notNull().default('open'),
    resolutionNote: text('resolution_note'),
    handledBy: text('handled_by').references(() => users.id, { onDelete: 'set null' }),
    createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp('updated_at', { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    modIdx: index('mod_reports_mod_idx').on(table.modId),
    statusIdx: index('mod_reports_status_idx').on(table.status),
    // One open report per (reporter, mod) — upsert target. Anonymous reports
    // (null reporter) are not deduped by this partial index.
    reporterModIdx: uniqueIndex('mod_reports_reporter_mod_idx')
      .on(table.reporterId, table.modId)
      .where(sql`${table.reporterId} is not null and ${table.status} = 'open'`),
  }),
);

// A user following a mod — drives new-version notifications (fan-out on
// publish). PK (userId, modId); modId index so we can list followers cheaply.
export const modFollows = pgTable(
  'mod_follows',
  {
    userId: text('user_id')
      .notNull()
      .references(() => users.id, { onDelete: 'cascade' }),
    modId: uuid('mod_id')
      .notNull()
      .references(() => mods.id, { onDelete: 'cascade' }),
    createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    pk: primaryKey({ columns: [table.userId, table.modId] }),
    modIdx: index('mod_follows_mod_idx').on(table.modId),
  }),
);

// In-app notifications (with optional email fan-out at emit time). `type` is a
// free string enum (mod_flagged / mod_takedown / report_resolved / mod_review /
// mod_new_version); `link` is an in-app path the UI routes to; `readAt` null =
// unread.
export const notifications = pgTable(
  'notifications',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    userId: text('user_id')
      .notNull()
      .references(() => users.id, { onDelete: 'cascade' }),
    type: varchar('type', { length: 32 }).notNull(),
    title: text('title').notNull(),
    body: text('body'),
    link: text('link'),
    readAt: timestamp('read_at', { withTimezone: true }),
    createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index('notifications_user_idx').on(table.userId, table.createdAt),
  }),
);

export const collections = pgTable(
  'collections',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    slug: varchar('slug', { length: 64 }).notNull(),
    ownerId: text('owner_id')
      .notNull()
      .references(() => users.id, { onDelete: 'cascade' }),
    name: text('name').notNull(),
    summary: text('summary'),
    description: text('description'),
    imageUrl: text('image_url'),
    screenshots: jsonb('screenshots').$type<{ url: string; caption?: string }[]>(),
    isPublic: boolean('is_public').notNull().default(true),
    createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp('updated_at', { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    slugIdx: uniqueIndex('collections_slug_idx').on(table.slug),
    ownerIdx: index('collections_owner_idx').on(table.ownerId),
  }),
);

export const collectionMods = pgTable(
  'collection_mods',
  {
    collectionId: uuid('collection_id')
      .notNull()
      .references(() => collections.id, { onDelete: 'cascade' }),
    modId: uuid('mod_id')
      .notNull()
      .references(() => mods.id, { onDelete: 'cascade' }),
    position: integer('position').notNull().default(0),
    addedAt: timestamp('added_at', { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    pk: primaryKey({ columns: [table.collectionId, table.modId] }),
    collIdx: index('collection_mods_coll_idx').on(table.collectionId),
  }),
);

export const collectionReviews = pgTable(
  'collection_reviews',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    collectionId: uuid('collection_id')
      .notNull()
      .references(() => collections.id, { onDelete: 'cascade' }),
    userId: text('user_id')
      .notNull()
      .references(() => users.id, { onDelete: 'cascade' }),
    rating: integer('rating').notNull(),
    title: varchar('title', { length: 120 }),
    body: text('body'),
    createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp('updated_at', { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    collectionUserIdx: uniqueIndex('collection_reviews_collection_user_idx').on(
      table.collectionId,
      table.userId,
    ),
    collectionIdx: index('collection_reviews_collection_idx').on(table.collectionId),
  }),
);

// User-published guides/tutorials (original editorial content). Mirrors the
// collections shape. `status` gates visibility: only 'approved' guides are
// public/indexed (see apps/api/src/routes/guides.ts). `body` is markdown.
export const guides = pgTable(
  'guides',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    slug: varchar('slug', { length: 80 }).notNull(),
    ownerId: text('owner_id')
      .notNull()
      .references(() => users.id, { onDelete: 'cascade' }),
    title: text('title').notNull(),
    summary: text('summary'),
    body: text('body').notNull(),
    imageUrl: text('image_url'),
    screenshots: jsonb('screenshots').$type<{ url: string; caption?: string }[]>(),
    status: varchar('status', { length: 16 }).notNull().default('draft'),
    createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp('updated_at', { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    slugIdx: uniqueIndex('guides_slug_idx').on(table.slug),
    ownerIdx: index('guides_owner_idx').on(table.ownerId),
    statusIdx: index('guides_status_idx').on(table.status),
  }),
);

export const guideReviews = pgTable(
  'guide_reviews',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    guideId: uuid('guide_id')
      .notNull()
      .references(() => guides.id, { onDelete: 'cascade' }),
    userId: text('user_id')
      .notNull()
      .references(() => users.id, { onDelete: 'cascade' }),
    rating: integer('rating').notNull(),
    title: varchar('title', { length: 120 }),
    body: text('body'),
    createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp('updated_at', { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    guideUserIdx: uniqueIndex('guide_reviews_guide_user_idx').on(table.guideId, table.userId),
    guideIdx: index('guide_reviews_guide_idx').on(table.guideId),
  }),
);

export const modsRelations = relations(mods, ({ many, one }) => ({
  versions: many(modVersions),
  authors: many(modAuthors),
  owner: one(users, { fields: [mods.ownerId], references: [users.id] }),
  reviews: many(modReviews),
  reports: many(modReports),
  follows: many(modFollows),
  inCollections: many(collectionMods),
}));

export const modReviewsRelations = relations(modReviews, ({ one }) => ({
  mod: one(mods, { fields: [modReviews.modId], references: [mods.id] }),
  user: one(users, { fields: [modReviews.userId], references: [users.id] }),
}));

export const modReportsRelations = relations(modReports, ({ one }) => ({
  mod: one(mods, { fields: [modReports.modId], references: [mods.id] }),
  reporter: one(users, { fields: [modReports.reporterId], references: [users.id] }),
}));

export const modFollowsRelations = relations(modFollows, ({ one }) => ({
  mod: one(mods, { fields: [modFollows.modId], references: [mods.id] }),
  user: one(users, { fields: [modFollows.userId], references: [users.id] }),
}));

export const notificationsRelations = relations(notifications, ({ one }) => ({
  user: one(users, { fields: [notifications.userId], references: [users.id] }),
}));

export const collectionsRelations = relations(collections, ({ many, one }) => ({
  owner: one(users, { fields: [collections.ownerId], references: [users.id] }),
  mods: many(collectionMods),
  reviews: many(collectionReviews),
}));

export const collectionReviewsRelations = relations(collectionReviews, ({ one }) => ({
  collection: one(collections, {
    fields: [collectionReviews.collectionId],
    references: [collections.id],
  }),
  user: one(users, { fields: [collectionReviews.userId], references: [users.id] }),
}));

export const guidesRelations = relations(guides, ({ many, one }) => ({
  owner: one(users, { fields: [guides.ownerId], references: [users.id] }),
  reviews: many(guideReviews),
}));

export const guideReviewsRelations = relations(guideReviews, ({ one }) => ({
  guide: one(guides, { fields: [guideReviews.guideId], references: [guides.id] }),
  user: one(users, { fields: [guideReviews.userId], references: [users.id] }),
}));

export const collectionModsRelations = relations(collectionMods, ({ one }) => ({
  collection: one(collections, {
    fields: [collectionMods.collectionId],
    references: [collections.id],
  }),
  mod: one(mods, { fields: [collectionMods.modId], references: [mods.id] }),
}));

export const modVersionsRelations = relations(modVersions, ({ one }) => ({
  mod: one(mods, { fields: [modVersions.modId], references: [mods.id] }),
}));

export const modAuthorsRelations = relations(modAuthors, ({ one }) => ({
  mod: one(mods, { fields: [modAuthors.modId], references: [mods.id] }),
  user: one(users, { fields: [modAuthors.userId], references: [users.id] }),
}));
