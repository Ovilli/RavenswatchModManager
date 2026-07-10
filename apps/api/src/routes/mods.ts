import { zValidator } from '@hono/zod-validator';
import { getDb, schema } from '@rsmm/db';
import {
  modCategorySchema,
  modImagePresignSchema,
  modPatchSchema,
  modUploadRequestSchema,
  modVersionCreateSchema,
  reportCreateSchema,
  reviewUpsertSchema,
} from '@rsmm/schemas';
import { and, asc, desc, eq, gte, ilike, or, sql } from 'drizzle-orm';
import { Hono } from 'hono';
import { z } from 'zod';
import { isAdmin } from '../admin.js';
import { isPgErrorCode } from '../db-errors.js';
import { errString } from '../logger.js';
import { s3Configured, virusTotalConfigured } from '../env.js';
import { canManageMod } from '../mod-access.js';
import { notify, notifyFollowers } from '../notify.js';
import { createRateLimiter } from '../rate-limit.js';
import { enqueueScan, isServable, markScan, queueInfo } from '../scan-service.js';
import { kickScanWorker } from '../scan-worker.js';
import { presignModImage, presignModUpload, remoteObjectExists } from '../storage.js';
import type { AppEnv } from '../types.js';

export const modsRouter = new Hono<AppEnv>();

// Outer-row reference for correlated subqueries, spelled out as raw SQL.
// Drizzle renders interpolated columns UNQUALIFIED in single-table selects,
// so `${schema.mods.id}` inside a subquery resolves against the inner table
// when it has its own `id` (mod_versions does) and the correlation silently
// never matches — every mod's latestVersion came back null.
const outerModId = sql.raw('"mods"."id"');

// Per-IP rate limiter for the download redirect endpoint. Without it,
// a script can spin the download counter (and the underlying S3 bill)
// arbitrarily fast. 120/min is well above any legitimate launcher
// install loop and small enough to make brute-forcing slug/version
// combos expensive.
const downloadLimiter = createRateLimiter({ name: 'mod-download', windowMs: 60_000, maxHits: 120 });

const listQuerySchema = z.object({
  q: z.string().optional(),
  tag: z.string().optional(),
  category: modCategorySchema.optional(),
  featured: z
    .union([z.literal('true'), z.literal('false'), z.literal('1'), z.literal('0')])
    .optional()
    .transform((v) => (v === 'true' || v === '1' ? true : v === undefined ? undefined : false)),
  // nsfw=false excludes mature-flagged mods. Absent (default) includes them,
  // matching the pre-existing behavior for CLI/desktop consumers.
  nsfw: z
    .union([z.literal('true'), z.literal('false'), z.literal('1'), z.literal('0')])
    .optional()
    .transform((v) => (v === 'true' || v === '1' ? true : v === undefined ? undefined : false)),
  owner: z.string().optional(),
  sort: z.enum(['recent', 'popular', 'featured', 'rating']).default('recent'),
  // Time window for the 'popular' sort: rank by downloads within the last N
  // days instead of all time (a trending list). Ignored for other sorts.
  window: z.enum(['7d', '30d']).optional(),
  limit: z.coerce.number().int().min(1).max(100).default(24),
  offset: z.coerce.number().int().min(0).default(0),
});

const slugParamSchema = z.object({
  slug: z
    .string()
    .min(1)
    .max(128)
    .regex(/^[a-z0-9_-]+$/),
});

const downloadParamSchema = z.object({
  slug: z
    .string()
    .min(1)
    .max(128)
    .regex(/^[a-z0-9_-]+$/),
  version: z.string().regex(/^\d+\.\d+\.\d+(?:[-+][\w.]+)?$/),
});

const versionScanParamSchema = z.object({
  versionId: z.string().uuid(),
});

modsRouter.get('/', zValidator('query', listQuerySchema), async (c) => {
  const { q, tag, category, featured, nsfw, owner, sort, window, limit, offset } =
    c.req.valid('query');
  const db = getDb();

  const qEsc = q ? q.replace(/[%_\\]/g, '\\$&') : undefined;
  const conditions = [
    // Admin takedown gate: delisted/removed mods never appear in the public list.
    eq(schema.mods.takedownStatus, 'active'),
    qEsc
      ? or(
          ilike(schema.mods.name, `%${qEsc}%`),
          ilike(schema.mods.slug, `%${qEsc}%`),
          ilike(schema.mods.summary, `%${qEsc}%`),
          ilike(schema.mods.authorName, `%${qEsc}%`),
        )
      : undefined,
    tag ? sql`${tag} = ANY(${schema.mods.tags})` : undefined,
    category ? eq(schema.mods.category, category) : undefined,
    featured === true ? eq(schema.mods.featured, true) : undefined,
    nsfw === false ? eq(schema.mods.nsfw, false) : undefined,
    owner ? eq(schema.mods.ownerId, owner) : undefined,
  ].filter(Boolean);

  const windowDays = window === '7d' ? 7 : window === '30d' ? 30 : null;
  const orderBy =
    sort === 'popular'
      ? sql`coalesce((
          select sum(${schema.modDownloads.count})
          from ${schema.modDownloads}
          where ${schema.modDownloads.modId} = ${outerModId}
          ${windowDays ? sql`and ${schema.modDownloads.day} >= current_date - ${windowDays}::int` : sql``}
        ), 0) desc`
      : sort === 'rating'
        ? sql`${schema.mods.rating} desc nulls last, ${schema.mods.updatedAt} desc`
        : sort === 'featured'
          ? sql`${schema.mods.featured} desc, ${schema.mods.featuredAt} desc nulls last, ${schema.mods.updatedAt} desc`
          : desc(schema.mods.updatedAt);

  const rows = await db
    .select({
      id: schema.mods.id,
      slug: schema.mods.slug,
      name: schema.mods.name,
      summary: schema.mods.summary,
      license: schema.mods.license,
      updatedAt: schema.mods.updatedAt,
      category: schema.mods.category,
      authorName: schema.mods.authorName,
      imageUrl: schema.mods.imageUrl,
      screenshots: schema.mods.screenshots,
      videos: schema.mods.videos,
      rating: schema.mods.rating,
      tags: schema.mods.tags,
      featured: schema.mods.featured,
      nsfw: schema.mods.nsfw,
      ownerId: schema.mods.ownerId,
      latestVersion: sql<string | null>`(
        select ${schema.modVersions.version}
        from ${schema.modVersions}
        where ${schema.modVersions.modId} = ${outerModId}
          and ${schema.modVersions.scanStatus} in ('clean', 'skipped')
        order by ${schema.modVersions.createdAt} desc
        limit 1
      )`,
      downloads: sql<number>`coalesce((
        select sum(${schema.modDownloads.count})::int
        from ${schema.modDownloads}
        where ${schema.modDownloads.modId} = ${outerModId}
      ), 0)`,
    })
    .from(schema.mods)
    .where(conditions.length ? and(...conditions) : undefined)
    .orderBy(orderBy)
    .limit(limit)
    .offset(offset);

  const totals = await db
    .select({
      total: sql<number>`count(*)::int`,
      totalDownloads: sql<number>`coalesce(sum((
        select sum(${schema.modDownloads.count})
        from ${schema.modDownloads}
        where ${schema.modDownloads.modId} = ${outerModId}
      )), 0)::int`,
    })
    .from(schema.mods)
    .where(conditions.length ? and(...conditions) : undefined);
  const total = totals[0]?.total ?? 0;
  const totalDownloads = totals[0]?.totalDownloads ?? 0;

  return c.json({
    items: rows.map((r) => ({
      id: r.id,
      slug: r.slug,
      name: r.name,
      author: r.authorName,
      summary: r.summary,
      license: r.license,
      latestVersion: r.latestVersion,
      downloads: r.downloads,
      updatedAt: r.updatedAt.toISOString(),
      category: r.category,
      imageUrl: r.imageUrl,
      screenshots: r.screenshots ?? [],
      videos: r.videos ?? [],
      rating: r.rating != null ? Number(r.rating) : null,
      tags: r.tags ?? [],
      featured: r.featured,
      nsfw: r.nsfw,
      ownerId: r.ownerId,
    })),
    total,
    totalDownloads,
  });
});

modsRouter.get('/:slug', zValidator('param', slugParamSchema), async (c) => {
  const { slug } = c.req.valid('param');
  const db = getDb();

  const mod = await db.query.mods.findFirst({
    where: eq(schema.mods.slug, slug),
    with: { versions: true },
  });
  if (!mod) return c.json({ error: 'not found' }, 404);

  // Admin takedown gate: a delisted/removed mod is 404 to the public. The owner
  // and admins can still load it (to see the takedown reason / appeal).
  const viewer = c.get('user');
  if (mod.takedownStatus !== 'active' && mod.ownerId !== viewer?.id && !isAdmin(viewer?.id)) {
    return c.json({ error: 'not found' }, 404);
  }

  // Aggregate downloads across all days for this mod. Mirrors the
  // expression used by the list endpoint so the same number shows up
  // everywhere; previously this route hard-coded `downloads: 0` and
  // the mod-detail page was permanently stuck at zero even after
  // hundreds of installs.
  const downloadAgg = await db
    .select({
      total: sql<number>`coalesce(sum(${schema.modDownloads.count})::int, 0)`,
    })
    .from(schema.modDownloads)
    .where(eq(schema.modDownloads.modId, mod.id));
  const downloads = downloadAgg[0]?.total ?? 0;

  // Fail-CLOSED: only versions scanned clean (or explicitly skipped when
  // scanning is disabled server-side) are shown publicly. Un-scanned
  // ('pending'/'queued'), 'flagged', and 'error' versions are withheld so a
  // freshly uploaded mod is never downloadable before its scan clears.
  // Managers (owner/co-authors) and admins see every version with its scan
  // status, so an upload still in review isn't invisible to its author —
  // the download route re-checks the gate, so this reveals state, not bytes.
  const sortedVersions = [...mod.versions].sort(
    (a, b) => b.createdAt.getTime() - a.createdAt.getTime(),
  );
  const servableVersions = sortedVersions.filter((v) => isServable(v.scanStatus));
  const canManage = viewer ? isAdmin(viewer.id) || (await canManageMod(mod, viewer.id)) : false;
  const visibleVersions = canManage ? sortedVersions : servableVersions;

  // Follow state for the current viewer + total follower count (both cheap).
  const followerRows = await db
    .select({ userId: schema.modFollows.userId })
    .from(schema.modFollows)
    .where(eq(schema.modFollows.modId, mod.id));
  const followerCount = followerRows.length;
  const isFollowing = viewer ? followerRows.some((f) => f.userId === viewer.id) : false;

  return c.json({
    mod: {
      id: mod.id,
      slug: mod.slug,
      name: mod.name,
      author: mod.authorName,
      summary: mod.summary,
      description: mod.description,
      license: mod.license,
      repoUrl: mod.repoUrl,
      homepageUrl: mod.homepageUrl,
      latestVersion: servableVersions[0]?.version ?? null,
      downloads,
      updatedAt: mod.updatedAt.toISOString(),
      category: mod.category,
      imageUrl: mod.imageUrl,
      screenshots: mod.screenshots ?? [],
      videos: mod.videos ?? [],
      rating: mod.rating != null ? Number(mod.rating) : null,
      tags: mod.tags ?? [],
      featured: mod.featured,
      nsfw: mod.nsfw,
      ownerId: mod.ownerId,
      takedownStatus: mod.takedownStatus,
      takedownReason: mod.takedownReason,
      isFollowing,
      followerCount,
      dependencies:
        (servableVersions[0]?.manifestJson as { dependencies?: Record<string, string> } | undefined)
          ?.dependencies ?? undefined,
    },
    versions: visibleVersions.map((v) => ({
      id: v.id,
      modId: v.modId,
      version: v.version,
      sha256: v.sha256,
      sizeBytes: v.sizeBytes,
      manifestJson: v.manifestJson,
      assetUrl: v.assetUrl,
      createdAt: v.createdAt.toISOString(),
      scanStatus: v.scanStatus,
      changelog: v.changelog,
    })),
  });
});

modsRouter.use('/:slug/:version/download', downloadLimiter);
modsRouter.get('/:slug/:version/download', zValidator('param', downloadParamSchema), async (c) => {
  const { slug, version } = c.req.valid('param');
  const db = getDb();

  const mod = await db.query.mods.findFirst({
    where: eq(schema.mods.slug, slug),
    with: {
      versions: {
        where: eq(schema.modVersions.version, version),
        limit: 1,
      },
    },
  });

  if (!mod || !mod.versions[0]) return c.json({ error: 'not found' }, 404);

  // Admin takedown gate: a delisted/removed mod is never downloadable, even by
  // direct URL. 404 (not 451) so the takedown isn't advertised.
  if (mod.takedownStatus !== 'active') return c.json({ error: 'not found' }, 404);

  const ver = mod.versions[0];

  // Malware-scan gate (fail-CLOSED): only hand out versions scanned clean or
  // explicitly skipped. A flagged version is withheld with 451 (Unavailable
  // For Legal Reasons); an un-scanned ('pending'/'queued') or errored version
  // is withheld with 409 (Conflict) — it exists but is not yet cleared for
  // download, so there is no window in which un-scanned bytes are servable.
  if (ver.scanStatus === 'flagged') {
    return c.json({ error: 'this version was flagged by malware scanning' }, 451);
  }
  if (!isServable(ver.scanStatus)) {
    return c.json({ error: 'this version has not passed malware scanning yet' }, 409);
  }

  // Record the download. `mod_downloads` is bucketed by day with a
  // composite PK (mod_id, day), so the conflict path bumps today's
  // counter instead of inserting a duplicate row. We fire-and-forget
  // before the redirect so a tracker hiccup never blocks the actual
  // file download.
  void db
    .insert(schema.modDownloads)
    .values({
      modId: mod.id,
      versionId: ver.id,
      // `day` defaults to CURRENT_DATE in the schema.
      count: 1,
    })
    .onConflictDoUpdate({
      target: [schema.modDownloads.modId, schema.modDownloads.day],
      set: { count: sql`${schema.modDownloads.count} + 1` },
    })
    .catch((err: unknown) => {
      c.get('log').error('download-count upsert failed', { err: errString(err) });
    });

  // In dev without S3, serve a placeholder file
  if (!s3Configured() || ver.assetUrl.startsWith('https://example.invalid')) {
    const name = `${slug}-${version}.zip`;
    const content = `RSMM Mod Archive\n${slug} v${version}\nPlaceholder — replace with real mod files.\n`;
    c.header('Content-Type', 'application/octet-stream');
    c.header('Content-Disposition', `attachment; filename="${name}"`);
    return c.body(content);
  }

  return c.redirect(ver.assetUrl);
});

// ─────────── Reporting ───────────
// Anyone (even logged-out) can report a mod — flagging malware must not require
// an account. Rate-limited hard to stop report-spam. A logged-in user gets one
// OPEN report per mod (re-filing updates it); anonymous reports always insert.
const reportLimiter = createRateLimiter({
  name: 'mod-report',
  windowMs: 3_600_000,
  maxHits: 10,
  keyFrom: (c) => {
    const user = c.get('user');
    return (
      user?.id ??
      c.req.header('x-real-ip') ??
      c.req.header('x-forwarded-for')?.split(',').pop()?.trim() ??
      'anon'
    );
  },
});

modsRouter.use('/:slug/report', reportLimiter);
modsRouter.post(
  '/:slug/report',
  zValidator('param', slugParamSchema),
  zValidator('json', reportCreateSchema),
  async (c) => {
    const { slug } = c.req.valid('param');
    const { reason, detail } = c.req.valid('json');
    const user = c.get('user');
    const db = getDb();

    const mod = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
    if (!mod) return c.json({ error: 'not found' }, 404);

    // Logged-in: fold repeat reports into the existing open one so a single
    // user can't stack the queue. Anonymous: always a fresh row.
    if (user) {
      const existing = await db.query.modReports.findFirst({
        where: and(
          eq(schema.modReports.modId, mod.id),
          eq(schema.modReports.reporterId, user.id),
          eq(schema.modReports.status, 'open'),
        ),
      });
      if (existing) {
        await db
          .update(schema.modReports)
          .set({ reason, detail: detail ?? null, updatedAt: new Date() })
          .where(eq(schema.modReports.id, existing.id));
        return c.json({ ok: true, updated: true });
      }
    }

    await db.insert(schema.modReports).values({
      modId: mod.id,
      reporterId: user?.id ?? null,
      reason,
      detail: detail ?? null,
    });
    return c.json({ ok: true });
  },
);

modsRouter.post('/upload', zValidator('json', modUploadRequestSchema), async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  if (!s3Configured()) {
    return c.json({ error: 'object storage is not configured on this server' }, 503);
  }
  const body = c.req.valid('json');

  const MAX_MOD_SIZE_BYTES = 500_000_000;
  if (body.sizeBytes > MAX_MOD_SIZE_BYTES) {
    return c.json({ error: 'mod exceeds maximum size' }, 413);
  }

  const db = getDb();

  const signed = await presignModUpload({
    slug: body.slug,
    version: body.version,
    sha256: body.sha256,
    sizeBytes: body.sizeBytes,
  });

  // Declared outside the try so the catch block can read it after the
  // transaction throws to abort itself on ownership conflict.
  let ownerConflict = false;
  try {
    const result = await db.transaction(async (tx) => {
      // Re-do the ownership check inside the transaction with a row
      // lock so two concurrent uploads can't both pass a stale check
      // and then both upsert. The old code did the SELECT outside the
      // transaction, leaving a window where two callers could each
      // see the row as "free" and race to claim it.
      const lockedExisting = await tx
        .select()
        .from(schema.mods)
        .where(eq(schema.mods.slug, body.slug))
        .for('update');
      const existing = lockedExisting[0];
      // Any pre-existing row that isn't owned by the caller is off-limits —
      // including rows with a null owner (seed/legacy data). Previously
      // null-owner rows could be claimed and overwritten by any authenticated
      // user. New slugs (existing === undefined) fall through and are created.
      if (existing && existing.ownerId !== user.id) {
        ownerConflict = true;
        // Throwing aborts the transaction; the catch below converts
        // this signal into a clean 403 instead of a 500.
        throw new Error('owner conflict');
      }

      const modRows = await tx
        .insert(schema.mods)
        .values({
          slug: body.slug,
          name: body.manifest.name,
          summary: body.manifest.summary,
          description: body.manifest.description,
          license: body.manifest.license,
          repoUrl: body.manifest.repo_url,
          homepageUrl: body.manifest.homepage_url,
          tags: body.manifest.tags,
          authorName: body.manifest.author,
          ownerId: user.id,
        })
        .onConflictDoUpdate({
          target: schema.mods.slug,
          set: {
            name: body.manifest.name,
            summary: body.manifest.summary,
            description: body.manifest.description,
            license: body.manifest.license,
            repoUrl: body.manifest.repo_url,
            homepageUrl: body.manifest.homepage_url,
            tags: body.manifest.tags,
            authorName: body.manifest.author,
            ownerId: user.id,
            updatedAt: new Date(),
          },
        })
        .returning();
      const mod = modRows[0];
      if (!mod) throw new Error('failed to upsert mod');

      // Idempotent: re-presigning the same (mod_id, version) tuple
      // refreshes the row instead of dying on the unique-key. Without
      // this, a failed object-store PUT (e.g. browser hit Cloudflare's
      // Bot Fight Mode) would orphan the row and every subsequent
      // upload would 23505 forever. Retries now just rewrite the
      // asset_url / sha256 / size in-place.
      const versionRows = await tx
        .insert(schema.modVersions)
        .values({
          modId: mod.id,
          version: body.version,
          sha256: body.sha256,
          sizeBytes: body.sizeBytes,
          manifestJson: body.manifest,
          assetUrl: signed.publicUrl,
        })
        .onConflictDoUpdate({
          target: [schema.modVersions.modId, schema.modVersions.version],
          set: {
            sha256: body.sha256,
            sizeBytes: body.sizeBytes,
            manifestJson: body.manifest,
            assetUrl: signed.publicUrl,
          },
        })
        .returning();
      const version = versionRows[0];
      if (!version) throw new Error('failed to insert version');

      return { mod, version };
    });

    return c.json({
      uploadUrl: signed.uploadUrl,
      publicUrl: signed.publicUrl,
      versionId: result.version.id,
      expiresIn: signed.expiresIn,
    });
  } catch (err) {
    // The transaction throws "owner conflict" when the slug already
    // belongs to a different user. Surface that as a 403 instead of
    // a 500 — `ownerConflict` is set inside the transaction body.
    if (ownerConflict) {
      return c.json({ error: 'slug owned by another user' }, 403);
    }
    // Unique constraint violation (PostgreSQL error code 23505).
    // Drizzle wraps the underlying pg error in `DrizzleQueryError`, so
    // the PG `code` lives on `err.cause.code`. Older code only checked
    // `err.code` and let dupes leak through as a generic 500.
    if (isPgErrorCode(err, '23505')) {
      return c.json({ error: 'version already exists' }, 409);
    }
    c.get('log').error('upload error', { err: errString(err) });
    return c.json({ error: 'failed to create mod version' }, 500);
  }
});

// ─────────────────────────────────────────────────────────────────────
// Owner-scoped mod management routes. All require an authenticated
// session and verify that `mod.ownerId === user.id` before mutating.
// ─────────────────────────────────────────────────────────────────────

const ownerLimiter = createRateLimiter({
  name: 'mod-owner',
  windowMs: 60_000,
  maxHits: 60,
  keyFrom: (c) => {
    const user = c.get('user');
    return (
      user?.id ??
      c.req.header('x-real-ip') ??
      c.req.header('x-forwarded-for')?.split(',').pop()?.trim() ??
      'anon'
    );
  },
});

// Enqueue a version for malware scanning. Publishing does NOT scan inline —
// the free tier is 4 lookups/min and a scan can take ~18s — so this just marks
// the version 'queued' and the in-process worker (scan-worker.ts) drains it
// ~1/min. Returns the queue position + ETA so the UI can show progress and the
// author can close the page.
modsRouter.use('/versions/:versionId/scan', ownerLimiter);
modsRouter.post(
  '/versions/:versionId/scan',
  zValidator('param', versionScanParamSchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);

    const { versionId } = c.req.valid('param');
    const db = getDb();

    const rows = await db
      .select({
        assetUrl: schema.modVersions.assetUrl,
        modId: schema.mods.id,
        ownerId: schema.mods.ownerId,
      })
      .from(schema.modVersions)
      .innerJoin(schema.mods, eq(schema.modVersions.modId, schema.mods.id))
      .where(eq(schema.modVersions.id, versionId))
      .limit(1);
    const row = rows[0];
    if (!row) return c.json({ error: 'not found' }, 404);
    if (!(await canManageMod({ id: row.modId, ownerId: row.ownerId }, user.id))) {
      return c.json({ error: 'forbidden' }, 403);
    }

    // Finalize gate: the upload row is created before the client PUTs the zip to
    // S3. Confirm the object actually landed. Uses a public HTTP HEAD (bucket is
    // public) so a write-scoped S3 key can't make a present upload look missing.
    const exists = await remoteObjectExists(row.assetUrl);
    if (!exists) return c.json({ error: 'upload not completed' }, 400);

    // Scanning is optional (see env.ts): when VirusTotal isn't configured, mark
    // the version skipped so the client can proceed.
    if (!virusTotalConfigured()) {
      await markScan(versionId, 'skipped');
      return c.json({ ok: true, status: 'skipped', flagged: false, position: null });
    }

    await enqueueScan(versionId);
    // Nudge the worker now — on serverless the interval tick alone can starve
    // the queue (it only fires while an instance stays warm).
    kickScanWorker();
    const info = await queueInfo(versionId);
    return c.json({
      ok: true,
      status: 'queued',
      flagged: false,
      position: info?.position ?? null,
      etaSeconds: info?.etaSeconds ?? null,
    });
  },
);

// Poll a version's scan state: status + place in the queue + ETA. Used by the
// publish / my-mods UI to show live progress without blocking.
modsRouter.use('/versions/:versionId/scan-status', ownerLimiter);
modsRouter.get(
  '/versions/:versionId/scan-status',
  zValidator('param', versionScanParamSchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);

    const { versionId } = c.req.valid('param');
    const db = getDb();
    const rows = await db
      .select({ modId: schema.mods.id, ownerId: schema.mods.ownerId })
      .from(schema.modVersions)
      .innerJoin(schema.mods, eq(schema.modVersions.modId, schema.mods.id))
      .where(eq(schema.modVersions.id, versionId))
      .limit(1);
    const row = rows[0];
    if (!row) return c.json({ error: 'not found' }, 404);
    if (!(await canManageMod({ id: row.modId, ownerId: row.ownerId }, user.id))) {
      return c.json({ error: 'forbidden' }, 403);
    }

    const info = await queueInfo(versionId);
    if (!info) return c.json({ error: 'not found' }, 404);
    // Progress polls double as queue nudges: while the publisher watches the
    // status UI, each poll advances the queue even if no worker tick fires.
    if (info.status === 'queued' || info.status === 'pending') kickScanWorker();
    return c.json({
      status: info.status,
      position: info.position,
      etaSeconds: info.etaSeconds,
      stats: info.stats,
    });
  },
);

modsRouter.use('/:slug/edit', ownerLimiter);
modsRouter.patch(
  '/:slug/edit',
  zValidator('param', slugParamSchema),
  zValidator('json', modPatchSchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    const { slug } = c.req.valid('param');
    const patch = c.req.valid('json');
    const db = getDb();

    const existing = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
    if (!existing) return c.json({ error: 'not found' }, 404);
    if (!(await canManageMod(existing, user.id))) return c.json({ error: 'forbidden' }, 403);

    // Build an update object that only sets keys the caller sent. The
    // `?? undefined` dance is needed because zod returns `null` for
    // fields the caller explicitly cleared and we want those nulls to
    // persist to the DB.
    const updates: Partial<typeof schema.mods.$inferInsert> = { updatedAt: new Date() };
    if (patch.name !== undefined) updates.name = patch.name;
    if (patch.summary !== undefined) updates.summary = patch.summary;
    if (patch.description !== undefined) updates.description = patch.description;
    if (patch.license !== undefined) updates.license = patch.license;
    if (patch.repoUrl !== undefined) updates.repoUrl = patch.repoUrl;
    if (patch.homepageUrl !== undefined) updates.homepageUrl = patch.homepageUrl;
    if (patch.category !== undefined) updates.category = patch.category;
    if (patch.tags !== undefined) updates.tags = patch.tags;
    if (patch.imageUrl !== undefined) updates.imageUrl = patch.imageUrl;
    if (patch.screenshots !== undefined) updates.screenshots = patch.screenshots;
    if (patch.videos !== undefined) updates.videos = patch.videos;
    if (patch.nsfw !== undefined) updates.nsfw = patch.nsfw;
    if (patch.nsfw !== undefined) updates.nsfw = patch.nsfw;

    const rows = await db
      .update(schema.mods)
      .set(updates)
      .where(eq(schema.mods.id, existing.id))
      .returning();
    return c.json({ mod: rows[0] });
  },
);

modsRouter.use('/:slug/image', ownerLimiter);
modsRouter.post(
  '/:slug/image',
  zValidator('param', slugParamSchema),
  zValidator('json', modImagePresignSchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    if (!s3Configured()) return c.json({ error: 'object storage not configured' }, 503);
    const { slug } = c.req.valid('param');
    const body = c.req.valid('json');
    const db = getDb();

    const existing = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
    if (!existing) return c.json({ error: 'not found' }, 404);
    if (!(await canManageMod(existing, user.id))) return c.json({ error: 'forbidden' }, 403);

    const signed = await presignModImage({
      slug,
      contentType: body.contentType,
      sizeBytes: body.sizeBytes,
    });
    return c.json({
      uploadUrl: signed.uploadUrl,
      publicUrl: signed.publicUrl,
      expiresIn: signed.expiresIn,
    });
  },
);

modsRouter.use('/:slug/versions', ownerLimiter);
modsRouter.post(
  '/:slug/versions',
  zValidator('param', slugParamSchema),
  zValidator('json', modVersionCreateSchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    if (!s3Configured()) return c.json({ error: 'object storage not configured' }, 503);
    const { slug } = c.req.valid('param');
    const body = c.req.valid('json');

    const MAX_MOD_SIZE_BYTES = 500_000_000;
    if (body.sizeBytes > MAX_MOD_SIZE_BYTES) {
      return c.json({ error: 'mod exceeds maximum size' }, 413);
    }

    const db = getDb();
    const existing = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
    if (!existing) return c.json({ error: 'not found' }, 404);
    if (!(await canManageMod(existing, user.id))) return c.json({ error: 'forbidden' }, 403);

    // Only a genuinely new version fans out to followers — re-uploading an
    // existing version (onConflictDoUpdate) must not re-notify.
    const priorVersion = await db.query.modVersions.findFirst({
      where: and(
        eq(schema.modVersions.modId, existing.id),
        eq(schema.modVersions.version, body.version),
      ),
    });

    const signed = await presignModUpload({
      slug,
      version: body.version,
      sha256: body.sha256,
      sizeBytes: body.sizeBytes,
    });

    try {
      const rows = await db
        .insert(schema.modVersions)
        .values({
          modId: existing.id,
          version: body.version,
          sha256: body.sha256,
          sizeBytes: body.sizeBytes,
          manifestJson: body.manifest,
          assetUrl: signed.publicUrl,
          changelog: body.changelog ?? null,
        })
        .onConflictDoUpdate({
          target: [schema.modVersions.modId, schema.modVersions.version],
          set: {
            sha256: body.sha256,
            sizeBytes: body.sizeBytes,
            manifestJson: body.manifest,
            assetUrl: signed.publicUrl,
            changelog: body.changelog ?? null,
          },
        })
        .returning();

      await db
        .update(schema.mods)
        .set({ updatedAt: new Date() })
        .where(eq(schema.mods.id, existing.id));

      if (!priorVersion) {
        await notifyFollowers(
          existing.id,
          {
            type: 'mod_new_version',
            title: `${existing.name} released v${body.version}`,
            body: body.changelog ?? null,
            link: `/registry/${existing.slug}`,
          },
          user.id,
        );
      }

      return c.json({
        uploadUrl: signed.uploadUrl,
        publicUrl: signed.publicUrl,
        versionId: rows[0]?.id,
        expiresIn: signed.expiresIn,
      });
    } catch (err) {
      c.get('log').error('version create error', { err: errString(err) });
      return c.json({ error: 'failed to create version' }, 500);
    }
  },
);

modsRouter.use('/:slug/delete', ownerLimiter);
modsRouter.delete('/:slug/delete', zValidator('param', slugParamSchema), async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const { slug } = c.req.valid('param');
  const db = getDb();

  const existing = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
  if (!existing) return c.json({ error: 'not found' }, 404);
  if (existing.ownerId !== user.id) return c.json({ error: 'forbidden' }, 403);

  // Cascade removes mod_versions, mod_authors, mod_downloads via FK.
  await db.delete(schema.mods).where(eq(schema.mods.id, existing.id));
  return c.json({ ok: true });
});

// ─────────── Co-authors / teams ───────────
// The owner manages the team; co-authors can edit/publish (canManageMod) but
// cannot add/remove other authors or delete the mod. mod_authors already
// existed in the schema — these routes wire it up.

modsRouter.use('/:slug/authors', ownerLimiter);
modsRouter.get('/:slug/authors', zValidator('param', slugParamSchema), async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const { slug } = c.req.valid('param');
  const db = getDb();

  const mod = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
  if (!mod) return c.json({ error: 'not found' }, 404);
  if (!(await canManageMod(mod, user.id))) return c.json({ error: 'forbidden' }, 403);

  const rows = await db
    .select({
      userId: schema.modAuthors.userId,
      role: schema.modAuthors.role,
      name: schema.users.name,
      handle: schema.users.handle,
      image: schema.users.image,
    })
    .from(schema.modAuthors)
    .innerJoin(schema.users, eq(schema.users.id, schema.modAuthors.userId))
    .where(eq(schema.modAuthors.modId, mod.id));

  return c.json({ ownerId: mod.ownerId, authors: rows });
});

const addAuthorSchema = z.object({ handle: z.string().min(1).max(64) });

modsRouter.post(
  '/:slug/authors',
  zValidator('param', slugParamSchema),
  zValidator('json', addAuthorSchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    const { slug } = c.req.valid('param');
    const { handle } = c.req.valid('json');
    const db = getDb();

    const mod = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
    if (!mod) return c.json({ error: 'not found' }, 404);
    // Owner-only: co-authors can't grow the team.
    if (mod.ownerId !== user.id) return c.json({ error: 'forbidden' }, 403);

    const target = await db.query.users.findFirst({ where: eq(schema.users.handle, handle) });
    if (!target) return c.json({ error: 'no user with that handle' }, 404);
    if (target.id === mod.ownerId) return c.json({ error: 'owner is already an author' }, 400);

    await db
      .insert(schema.modAuthors)
      .values({ modId: mod.id, userId: target.id, role: 'contrib' })
      .onConflictDoNothing();
    return c.json({ ok: true });
  },
);

modsRouter.delete(
  '/:slug/authors/:userId',
  zValidator('param', slugParamSchema.extend({ userId: z.string().min(1) })),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    const { slug, userId } = c.req.valid('param');
    const db = getDb();

    const mod = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
    if (!mod) return c.json({ error: 'not found' }, 404);
    // Owner-only. (The owner can never be in mod_authors, so this can't strip
    // ownership.)
    if (mod.ownerId !== user.id) return c.json({ error: 'forbidden' }, 403);

    await db
      .delete(schema.modAuthors)
      .where(and(eq(schema.modAuthors.modId, mod.id), eq(schema.modAuthors.userId, userId)));
    return c.json({ ok: true });
  },
);

// ─────────── Author analytics ───────────
// Time-series downloads for a mod. mod_downloads is already day-bucketed, so
// this is a cheap group-by. Manage-gated (owner or co-author).

const statsQuerySchema = z.object({
  days: z.coerce.number().int().min(1).max(365).default(30),
});

modsRouter.use('/:slug/stats', ownerLimiter);
modsRouter.get(
  '/:slug/stats',
  zValidator('param', slugParamSchema),
  zValidator('query', statsQuerySchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    const { slug } = c.req.valid('param');
    const { days } = c.req.valid('query');
    const db = getDb();

    const mod = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
    if (!mod) return c.json({ error: 'not found' }, 404);
    if (!(await canManageMod(mod, user.id))) return c.json({ error: 'forbidden' }, 403);

    // Inclusive cutoff = today - (days-1), as a YYYY-MM-DD string (the `day`
    // column is a DATE).
    const cutoff = new Date(Date.now() - (days - 1) * 86_400_000).toISOString().slice(0, 10);

    const series = await db
      .select({
        day: schema.modDownloads.day,
        count: sql<number>`sum(${schema.modDownloads.count})::int`,
      })
      .from(schema.modDownloads)
      .where(and(eq(schema.modDownloads.modId, mod.id), gte(schema.modDownloads.day, cutoff)))
      .groupBy(schema.modDownloads.day)
      .orderBy(asc(schema.modDownloads.day));

    const perVersion = await db
      .select({
        version: schema.modVersions.version,
        count: sql<number>`coalesce(sum(${schema.modDownloads.count}), 0)::int`,
      })
      .from(schema.modDownloads)
      .innerJoin(schema.modVersions, eq(schema.modDownloads.versionId, schema.modVersions.id))
      .where(eq(schema.modDownloads.modId, mod.id))
      .groupBy(schema.modVersions.version)
      .orderBy(desc(sql`sum(${schema.modDownloads.count})`));

    const totalRow = await db
      .select({ total: sql<number>`coalesce(sum(${schema.modDownloads.count}), 0)::int` })
      .from(schema.modDownloads)
      .where(eq(schema.modDownloads.modId, mod.id));

    return c.json({
      days,
      totalDownloads: totalRow[0]?.total ?? 0,
      series: series.map((s) => ({ day: s.day, count: s.count })),
      perVersion,
    });
  },
);

// ─────────── Follow / subscribe ───────────
// Following a mod subscribes the user to new-version notifications (fan-out
// happens in the /:slug/versions publish route).

modsRouter.use('/:slug/follow', ownerLimiter);
modsRouter.post('/:slug/follow', zValidator('param', slugParamSchema), async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const { slug } = c.req.valid('param');
  const db = getDb();
  const mod = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
  if (!mod || mod.takedownStatus !== 'active') return c.json({ error: 'not found' }, 404);
  await db
    .insert(schema.modFollows)
    .values({ userId: user.id, modId: mod.id })
    .onConflictDoNothing();
  return c.json({ ok: true, following: true });
});

modsRouter.delete('/:slug/follow', zValidator('param', slugParamSchema), async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const { slug } = c.req.valid('param');
  const db = getDb();
  const mod = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
  if (!mod) return c.json({ error: 'not found' }, 404);
  await db
    .delete(schema.modFollows)
    .where(and(eq(schema.modFollows.userId, user.id), eq(schema.modFollows.modId, mod.id)));
  return c.json({ ok: true, following: false });
});

// ─────────── Reviews ───────────

const reviewLimiter = createRateLimiter({
  name: 'mod-review',
  windowMs: 60_000,
  maxHits: 10,
  keyFrom: (c) => {
    const user = c.get('user');
    return (
      user?.id ??
      c.req.header('x-real-ip') ??
      c.req.header('x-forwarded-for')?.split(',').pop()?.trim() ??
      'anon'
    );
  },
});

async function recomputeRating(modId: string): Promise<void> {
  const db = getDb();
  const agg = await db
    .select({
      avg: sql<number | null>`avg(${schema.modReviews.rating})::numeric(3,2)`,
    })
    .from(schema.modReviews)
    .where(eq(schema.modReviews.modId, modId));
  const avg = agg[0]?.avg;
  await db
    .update(schema.mods)
    .set({ rating: avg == null ? null : String(avg) })
    .where(eq(schema.mods.id, modId));
}

modsRouter.get('/:slug/reviews', zValidator('param', slugParamSchema), async (c) => {
  const { slug } = c.req.valid('param');
  const db = getDb();
  const mod = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
  if (!mod) return c.json({ error: 'not found' }, 404);

  const rows = await db
    .select({
      id: schema.modReviews.id,
      modId: schema.modReviews.modId,
      userId: schema.modReviews.userId,
      rating: schema.modReviews.rating,
      title: schema.modReviews.title,
      body: schema.modReviews.body,
      createdAt: schema.modReviews.createdAt,
      updatedAt: schema.modReviews.updatedAt,
      userName: schema.users.name,
      userImage: schema.users.image,
    })
    .from(schema.modReviews)
    .innerJoin(schema.users, eq(schema.users.id, schema.modReviews.userId))
    .where(eq(schema.modReviews.modId, mod.id))
    .orderBy(desc(schema.modReviews.updatedAt));

  const items = rows.map((r) => ({
    id: r.id,
    modId: r.modId,
    userId: r.userId,
    userName: r.userName,
    userImage: r.userImage,
    rating: r.rating,
    title: r.title,
    body: r.body,
    createdAt: r.createdAt.toISOString(),
    updatedAt: r.updatedAt.toISOString(),
  }));

  const average = items.length ? items.reduce((s, r) => s + r.rating, 0) / items.length : null;

  return c.json({ items, total: items.length, averageRating: average });
});

modsRouter.use('/:slug/reviews', reviewLimiter);
modsRouter.put(
  '/:slug/reviews',
  zValidator('param', slugParamSchema),
  zValidator('json', reviewUpsertSchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    const { slug } = c.req.valid('param');
    const body = c.req.valid('json');
    const db = getDb();

    const mod = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
    if (!mod) return c.json({ error: 'not found' }, 404);
    if (mod.ownerId === user.id) {
      return c.json({ error: 'authors cannot review their own mod' }, 400);
    }

    const now = new Date();
    await db
      .insert(schema.modReviews)
      .values({
        modId: mod.id,
        userId: user.id,
        rating: body.rating,
        title: body.title ?? null,
        body: body.body ?? null,
        updatedAt: now,
      })
      .onConflictDoUpdate({
        target: [schema.modReviews.modId, schema.modReviews.userId],
        set: {
          rating: body.rating,
          title: body.title ?? null,
          body: body.body ?? null,
          updatedAt: now,
        },
      });

    await recomputeRating(mod.id);
    // Tell the owner someone reviewed their mod (in-app only).
    if (mod.ownerId) {
      await notify({
        userId: mod.ownerId,
        type: 'mod_review',
        title: `New review on ${mod.name}`,
        body: `${user.name ?? 'Someone'} rated it ${body.rating}/5.`,
        link: `/registry/${mod.slug}`,
      });
    }
    return c.json({ ok: true });
  },
);

modsRouter.delete('/:slug/reviews', zValidator('param', slugParamSchema), async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const { slug } = c.req.valid('param');
  const db = getDb();

  const mod = await db.query.mods.findFirst({ where: eq(schema.mods.slug, slug) });
  if (!mod) return c.json({ error: 'not found' }, 404);

  await db
    .delete(schema.modReviews)
    .where(and(eq(schema.modReviews.modId, mod.id), eq(schema.modReviews.userId, user.id)));
  await recomputeRating(mod.id);
  return c.json({ ok: true });
});
