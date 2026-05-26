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
    createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp('updated_at', { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    slugIdx: uniqueIndex('mods_slug_idx').on(table.slug),
    ownerIdx: index('mods_owner_idx').on(table.ownerId),
    categoryIdx: index('mods_category_idx').on(table.category),
    featuredIdx: index('mods_featured_idx').on(table.featured),
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
    collectionUserIdx: uniqueIndex('collection_reviews_collection_user_idx').on(table.collectionId, table.userId),
    collectionIdx: index('collection_reviews_collection_idx').on(table.collectionId),
  }),
);

export const modsRelations = relations(mods, ({ many, one }) => ({
  versions: many(modVersions),
  authors: many(modAuthors),
  owner: one(users, { fields: [mods.ownerId], references: [users.id] }),
  reviews: many(modReviews),
  inCollections: many(collectionMods),
}));

export const modReviewsRelations = relations(modReviews, ({ one }) => ({
  mod: one(mods, { fields: [modReviews.modId], references: [mods.id] }),
  user: one(users, { fields: [modReviews.userId], references: [users.id] }),
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
