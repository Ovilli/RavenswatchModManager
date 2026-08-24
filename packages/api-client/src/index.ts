import {
  type CollectionCreate,
  type CollectionImagePresign,
  type CollectionPatch,
  type CollectionReviewUpsert,
  type CrashReport,
  type GuideCreate,
  type GuideImagePresign,
  type GuidePatch,
  type GuideReviewUpsert,
  type ModImagePresign,
  type ModListItem,
  type ModPatch,
  type ModUploadRequest,
  type ModVersion,
  type ModVersionCreate,
  type PrivacySettingsUpdate,
  type ReviewUpsert,
  type TelemetryRun,
  collectionDetailSchema,
  collectionReviewsResponseSchema,
  collectionSchema,
  guideListItemSchema,
  guideReviewsResponseSchema,
  modListItemSchema,
  modVersionSchema,
  privacySettingsSchema,
  reviewsResponseSchema,
} from '@rsmm/schemas';
import { z } from 'zod';

export interface ApiClientOptions {
  baseUrl: string;
  fetch?: typeof fetch;
  getToken?: () => string | null | undefined;
  /** Wallclock timeout for each request. Defaults to 30s. */
  timeoutMs?: number;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export class ApiTimeoutError extends ApiError {
  constructor(path: string, timeoutMs: number) {
    super(`${path} timed out after ${timeoutMs}ms`, 0, { timeoutMs });
    this.name = 'ApiTimeoutError';
  }
}

export class RateLimitError extends ApiError {
  readonly retryAfter: number;
  constructor(path: string, retryAfter: number, body: unknown) {
    super(`rate limited on ${path}`, 429, body);
    this.name = 'RateLimitError';
    this.retryAfter = retryAfter;
  }
}

export function isRateLimited(err: unknown): err is RateLimitError {
  return err instanceof RateLimitError;
}

const DEFAULT_TIMEOUT_MS = 30_000;

export function createApiClient(options: ApiClientOptions) {
  const f = options.fetch ?? fetch;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const headers = (): Record<string, string> => {
    const h: Record<string, string> = { 'Content-Type': 'application/json' };
    const tok = options.getToken?.();
    if (tok) h.Authorization = `Bearer ${tok}`;
    return h;
  };

  async function request<T>(path: string, init: RequestInit, schema: z.ZodType<T>): Promise<T> {
    const baseUrl = options.baseUrl.replace(/\/+$/, '');
    const ctrl = new AbortController();
    // Compose caller's signal (if any) with our timeout so explicit
    // cancellation still works.
    if (init.signal) {
      if (init.signal.aborted) ctrl.abort(init.signal.reason);
      else
        init.signal.addEventListener('abort', () => ctrl.abort(init.signal?.reason), {
          once: true,
        });
    }
    const timer = setTimeout(() => ctrl.abort('timeout'), timeoutMs);
    let res: Response;
    try {
      res = await f(`${baseUrl}${path}`, {
        ...init,
        signal: ctrl.signal,
        headers: { ...headers(), ...(init.headers ?? {}) },
        credentials: 'include',
      });
    } catch (err) {
      if (
        (err instanceof DOMException && err.name === 'AbortError') ||
        (err instanceof Error && err.name === 'AbortError')
      ) {
        if (ctrl.signal.reason === 'timeout') {
          throw new ApiTimeoutError(path, timeoutMs);
        }
      }
      throw err;
    } finally {
      clearTimeout(timer);
    }
    const json = await res.json().catch(() => null);
    if (!res.ok) {
      if (res.status === 429) {
        const retryAfter = Number.parseInt(res.headers.get('Retry-After') ?? '', 10) || 60;
        throw new RateLimitError(path, retryAfter, json);
      }
      throw new ApiError(`${res.status} ${path}`, res.status, json);
    }
    try {
      return schema.parse(json);
    } catch (err) {
      throw new ApiError(`response validation failed for ${path}`, res.status, {
        error: err instanceof Error ? err.message : 'invalid response',
      });
    }
  }

  const facetSchema = z.array(z.object({ name: z.string(), count: z.number().int() }));
  const modListResponseSchema = z.object({
    items: z.array(modListItemSchema),
    total: z.number().int().nonnegative(),
    // Present only when the caller asked for `facets`; optional as well as
    // nullable so an older API build still validates.
    facets: z.object({ categories: facetSchema, tags: facetSchema }).nullable().optional(),
  });
  const modDetailResponseSchema = z.object({
    mod: modListItemSchema.and(
      z.object({
        isFollowing: z.boolean().optional(),
        followerCount: z.number().int().optional(),
        // Present for the owner/admin viewing a delisted mod; public callers
        // never receive a non-active mod so these default to active.
        takedownStatus: z.enum(['active', 'hidden', 'removed']).optional(),
        takedownReason: z.string().nullable().optional(),
      }),
    ),
    versions: z.array(modVersionSchema),
  });
  const notificationsResponseSchema = z.object({
    unread: z.number().int().nonnegative(),
    items: z.array(
      z.object({
        id: z.string(),
        type: z.string(),
        title: z.string(),
        body: z.string().nullable(),
        link: z.string().nullable(),
        read: z.boolean(),
        createdAt: z.string(),
      }),
    ),
  });
  const followsResponseSchema = z.object({
    items: z.array(
      z.object({
        slug: z.string(),
        name: z.string(),
        imageUrl: z.string().nullable(),
        followedAt: z.string(),
        // Enriched card fields — optional for back-compat with older APIs.
        summary: z.string().nullable().optional(),
        category: z.string().nullable().optional(),
        authorName: z.string().nullable().optional(),
        rating: z.number().nullable().optional(),
        nsfw: z.boolean().optional(),
        updatedAt: z.string().optional(),
        latestVersion: z.string().nullable().optional(),
        downloads: z.number().int().optional(),
      }),
    ),
  });
  const okSchema = z.object({ ok: z.literal(true) });
  const uploadResponseSchema = z.object({
    uploadUrl: z.string().url(),
    publicUrl: z.string().url(),
    versionId: z.string().uuid(),
    expiresIn: z.number().int().positive(),
  });
  // Scanning is async: POST /scan enqueues and returns status 'queued' with a
  // place in line; the worker resolves it later. 'skipped' when scanning is off.
  const scanStatusEnum = z.enum(['queued', 'pending', 'clean', 'flagged', 'skipped', 'error']);
  const virusTotalScanResponseSchema = z.object({
    ok: z.boolean(),
    status: scanStatusEnum.optional(),
    flagged: z.boolean().optional(),
    reason: z.string().optional(),
    position: z.number().int().nullable().optional(),
    etaSeconds: z.number().int().nullable().optional(),
  });
  // Live scan state for polling (GET /scan-status).
  const scanStatusResponseSchema = z.object({
    status: scanStatusEnum,
    position: z.number().int().nullable(),
    etaSeconds: z.number().int().nullable(),
    stats: z.record(z.number()).optional(),
  });
  const imagePresignResponseSchema = z.object({
    uploadUrl: z.string().url(),
    publicUrl: z.string().url(),
    expiresIn: z.number().int().positive(),
  });
  const myModItemSchema = z.object({
    id: z.string().uuid(),
    slug: z.string(),
    name: z.string(),
    summary: z.string().nullable(),
    description: z.string().nullable(),
    license: z.string().nullable(),
    repoUrl: z.string().nullable(),
    homepageUrl: z.string().nullable(),
    tags: z.array(z.string()),
    category: z.string().nullable(),
    authorName: z.string().nullable(),
    imageUrl: z.string().nullable(),
    updatedAt: z.string(),
    createdAt: z.string(),
    latestVersion: z.string().nullable(),
    downloads: z.number().int().nonnegative(),
  });
  const myModsResponseSchema = z.object({ items: z.array(myModItemSchema) });
  const patchResponseSchema = z.object({ mod: z.unknown() });
  const userProfileResponseSchema = z.object({
    user: z.object({
      id: z.string(),
      name: z.string(),
      handle: z.string().nullable(),
      image: z.string().nullable(),
      // Optional because the API deliberately does not send it: GET
      // /api/users/:id trims timestamps so a profile does not leak account age.
      // It was declared required here, which made `schema.parse` throw on every
      // single author page — the profile route has never returned the field.
      joinedAt: z.string().optional(),
    }),
    mods: z.array(modListItemSchema),
    // null when the author has turned off public download counts.
    totalDownloads: z.number().int().nonnegative().nullable(),
  });

  const countBucket = z.object({ n: z.number().int() });
  const daySeries = z.array(z.object({ day: z.string(), n: z.number().int() }));

  // Admin business overview. Kept permissive on the nested blocks (`.nullable()`
  // rather than exhaustive shapes) so a server that gains a field does not fail
  // validation in an older web build — the console renders what it recognises.
  const adminStatsResponseSchema = z.object({
    generatedAt: z.string(),
    users: z.object({
      total: z.number().int(),
      new1d: z.number().int(),
      new7d: z.number().int(),
      new30d: z.number().int(),
      banned: z.number().int(),
      verified: z.number().int(),
      active: z.number().int(),
      creators: z.number().int(),
    }),
    consent: z.object({
      telemetryOff: z.number().int(),
      telemetryAnonymous: z.number().int(),
      telemetryLinked: z.number().int(),
      announcementOptIn: z.number().int(),
    }),
    mods: z
      .object({
        total: z.number().int(),
        active: z.number().int(),
        hidden: z.number().int(),
        removed: z.number().int(),
        featured: z.number().int(),
        nsfw: z.number().int(),
        new7d: z.number().int(),
        new30d: z.number().int(),
        noSummary: z.number().int(),
      })
      .nullable(),
    versions: z
      .object({
        total: z.number().int(),
        new7d: z.number().int(),
        awaitingScan: z.number().int(),
        flagged: z.number().int(),
        scanErrors: z.number().int(),
      })
      .nullable(),
    downloads: z
      .object({
        total: z.number().int(),
        d1: z.number().int(),
        d7: z.number().int(),
        d30: z.number().int(),
      })
      .nullable(),
    reviews: z.object({
      total: z.number().int(),
      new7d: z.number().int(),
      avgRating: z.number().nullable(),
    }),
    reports: z
      .object({ open: z.number().int(), reviewing: z.number().int(), new7d: z.number().int() })
      .nullable(),
    guides: z
      .object({ total: z.number().int(), approved: z.number().int(), pending: z.number().int() })
      .nullable(),
    collections: z.number().int(),
    follows: z.number().int(),
    client: z.object({
      runs7d: z.number().int(),
      runs30d: z.number().int(),
      successRate7d: z.number().nullable(),
      crashes7d: z.number().int(),
      crashes30d: z.number().int(),
      osSplit: z.array(z.object({ os: z.string(), n: z.number().int() })),
      versionSplit: z.array(z.object({ version: z.string(), n: z.number().int() })),
    }),
    topMods: z.array(z.object({ slug: z.string(), name: z.string(), downloads: z.number().int() })),
    series: z.object({ signups: daySeries, downloads: daySeries }),
  });

  const statsResponseSchema = z.object({
    days: z.number().int(),
    totalDownloads: z.number().int().nonnegative(),
    series: z.array(z.object({ day: z.string(), count: z.number().int() })),
    perVersion: z.array(z.object({ version: z.string(), count: z.number().int() })),
  });
  const authorsResponseSchema = z.object({
    ownerId: z.string().nullable(),
    authors: z.array(
      z.object({
        userId: z.string(),
        role: z.string(),
        name: z.string().nullable(),
        handle: z.string().nullable(),
        image: z.string().nullable(),
      }),
    ),
  });
  const reportItemSchema = z.object({
    id: z.string(),
    modId: z.string(),
    modSlug: z.string(),
    modName: z.string(),
    takedownStatus: z.string(),
    reporterId: z.string().nullable(),
    reporterName: z.string().nullable(),
    reason: z.string(),
    detail: z.string().nullable(),
    status: z.string(),
    resolutionNote: z.string().nullable(),
    createdAt: z.string(),
    updatedAt: z.string(),
  });
  const reportsResponseSchema = z.object({ items: z.array(reportItemSchema) });

  return {
    mods: {
      list: (
        params: {
          q?: string;
          tag?: string;
          /** AND semantics: a mod must carry every tag listed. */
          tags?: string[];
          /** Minimum star rating; unrated mods are excluded once set. */
          minRating?: number;
          /** Ask for category/tag facet counts alongside the page. */
          facets?: boolean;
          category?: string;
          limit?: number;
          offset?: number;
          featured?: boolean;
          /** false = exclude NSFW mods; absent/true = include (server default). */
          nsfw?: boolean;
          owner?: string;
          sort?: 'recent' | 'popular' | 'featured' | 'rating';
          /** Trending window for sort=popular (downloads within last N days). */
          window?: '7d' | '30d';
        } = {},
      ) => {
        const qs = new URLSearchParams();
        if (params.q) qs.set('q', params.q);
        if (params.tag) qs.set('tag', params.tag);
        if (params.tags?.length) qs.set('tags', params.tags.join(','));
        if (params.minRating) qs.set('minRating', String(params.minRating));
        if (params.facets) qs.set('facets', '1');
        if (params.category) qs.set('category', params.category);
        if (params.limit) qs.set('limit', String(params.limit));
        if (params.offset) qs.set('offset', String(params.offset));
        if (params.featured) qs.set('featured', 'true');
        if (params.nsfw === false) qs.set('nsfw', 'false');
        if (params.owner) qs.set('owner', params.owner);
        if (params.sort) qs.set('sort', params.sort);
        if (params.window) qs.set('window', params.window);
        return request<{
          items: ModListItem[];
          total: number;
          facets?: {
            categories: { name: string; count: number }[];
            tags: { name: string; count: number }[];
          } | null;
        }>(`/api/mods?${qs}`, { method: 'GET' }, modListResponseSchema);
      },
      get: (slug: string) =>
        request(
          `/api/mods/${encodeURIComponent(slug)}`,
          { method: 'GET' },
          modDetailResponseSchema,
        ),
      upload: (body: ModUploadRequest) =>
        request(
          '/api/mods/upload',
          { method: 'POST', body: JSON.stringify(body) },
          uploadResponseSchema,
        ),
      scanVersion: (versionId: string) =>
        request(
          `/api/mods/versions/${encodeURIComponent(versionId)}/scan`,
          { method: 'POST' },
          virusTotalScanResponseSchema,
        ),
      scanStatus: (versionId: string) =>
        request(
          `/api/mods/versions/${encodeURIComponent(versionId)}/scan-status`,
          { method: 'GET' },
          scanStatusResponseSchema,
        ),
      patch: (slug: string, body: ModPatch) =>
        request(
          `/api/mods/${encodeURIComponent(slug)}/edit`,
          { method: 'PATCH', body: JSON.stringify(body) },
          patchResponseSchema,
        ),
      presignImage: (slug: string, body: ModImagePresign) =>
        request(
          `/api/mods/${encodeURIComponent(slug)}/image`,
          { method: 'POST', body: JSON.stringify(body) },
          imagePresignResponseSchema,
        ),
      createVersion: (slug: string, body: ModVersionCreate) =>
        request(
          `/api/mods/${encodeURIComponent(slug)}/versions`,
          { method: 'POST', body: JSON.stringify(body) },
          uploadResponseSchema,
        ),
      remove: (slug: string) =>
        request(`/api/mods/${encodeURIComponent(slug)}/delete`, { method: 'DELETE' }, okSchema),
      reviews: (slug: string) =>
        request(
          `/api/mods/${encodeURIComponent(slug)}/reviews`,
          { method: 'GET' },
          reviewsResponseSchema,
        ),
      upsertReview: (slug: string, body: ReviewUpsert) =>
        request(
          `/api/mods/${encodeURIComponent(slug)}/reviews`,
          { method: 'PUT', body: JSON.stringify(body) },
          okSchema,
        ),
      deleteReview: (slug: string) =>
        request(`/api/mods/${encodeURIComponent(slug)}/reviews`, { method: 'DELETE' }, okSchema),
      report: (slug: string, body: { reason: string; detail?: string | null }) =>
        request(
          `/api/mods/${encodeURIComponent(slug)}/report`,
          { method: 'POST', body: JSON.stringify(body) },
          okSchema,
        ),
      stats: (slug: string, days = 30) =>
        request(
          `/api/mods/${encodeURIComponent(slug)}/stats?days=${days}`,
          { method: 'GET' },
          statsResponseSchema,
        ),
      follow: (slug: string) =>
        request(
          `/api/mods/${encodeURIComponent(slug)}/follow`,
          { method: 'POST' },
          z.object({ ok: z.literal(true), following: z.boolean() }),
        ),
      unfollow: (slug: string) =>
        request(
          `/api/mods/${encodeURIComponent(slug)}/follow`,
          { method: 'DELETE' },
          z.object({ ok: z.literal(true), following: z.boolean() }),
        ),
      authors: {
        list: (slug: string) =>
          request(
            `/api/mods/${encodeURIComponent(slug)}/authors`,
            { method: 'GET' },
            authorsResponseSchema,
          ),
        add: (slug: string, handle: string) =>
          request(
            `/api/mods/${encodeURIComponent(slug)}/authors`,
            { method: 'POST', body: JSON.stringify({ handle }) },
            okSchema,
          ),
        remove: (slug: string, userId: string) =>
          request(
            `/api/mods/${encodeURIComponent(slug)}/authors/${encodeURIComponent(userId)}`,
            { method: 'DELETE' },
            okSchema,
          ),
      },
    },
    moderation: {
      /** Admin-only business overview powering the console's Overview tab. */
      stats: () => request('/api/moderation/stats', { method: 'GET' }, adminStatsResponseSchema),
      reports: (status?: 'open' | 'reviewing' | 'resolved' | 'dismissed') =>
        request(
          `/api/moderation/reports${status ? `?status=${status}` : ''}`,
          { method: 'GET' },
          reportsResponseSchema,
        ),
      resolveReport: (
        id: string,
        body: {
          status: 'open' | 'reviewing' | 'resolved' | 'dismissed';
          resolutionNote?: string | null;
        },
      ) =>
        request(
          `/api/moderation/reports/${encodeURIComponent(id)}`,
          { method: 'PATCH', body: JSON.stringify(body) },
          z.object({ ok: z.literal(true), report: z.unknown() }),
        ),
      takedown: (
        slug: string,
        body: { takedownStatus: 'active' | 'hidden' | 'removed'; reason?: string | null },
      ) =>
        request(
          `/api/moderation/mods/${encodeURIComponent(slug)}/takedown`,
          { method: 'POST', body: JSON.stringify(body) },
          z.object({ ok: z.literal(true), mod: z.unknown() }),
        ),
      feature: (slug: string, featured: boolean) =>
        request(
          `/api/moderation/mods/${encodeURIComponent(slug)}/feature`,
          { method: 'POST', body: JSON.stringify({ featured }) },
          z.object({ ok: z.literal(true), mod: z.unknown() }),
        ),
      banUser: (id: string, body: { banned: boolean; reason?: string | null }) =>
        request(
          `/api/moderation/users/${encodeURIComponent(id)}/ban`,
          { method: 'POST', body: JSON.stringify(body) },
          z.object({ ok: z.literal(true), user: z.unknown() }),
        ),
    },
    // Ban-aware session probe. Returns banned=true (with reason) even though the
    // Better Auth cookie still reads as signed-in, so the UI can show a notice.
    session: () =>
      request(
        '/api/session',
        { method: 'GET' },
        z.object({ banned: z.boolean(), reason: z.string().nullable() }),
      ),
    me: {
      whoami: () =>
        request('/api/me', { method: 'GET' }, z.object({ id: z.string(), isAdmin: z.boolean() })),
      mods: () => request('/api/me/mods', { method: 'GET' }, myModsResponseSchema),
      privacy: () => request('/api/me/privacy', { method: 'GET' }, privacySettingsSchema),
      updatePrivacy: (body: PrivacySettingsUpdate) =>
        request(
          '/api/me/privacy',
          { method: 'PATCH', body: JSON.stringify(body) },
          privacySettingsSchema,
        ),
      presignAvatar: (body: ModImagePresign) =>
        request(
          '/api/me/avatar',
          { method: 'POST', body: JSON.stringify(body) },
          imagePresignResponseSchema,
        ),
      notifications: () =>
        request('/api/me/notifications', { method: 'GET' }, notificationsResponseSchema),
      markNotificationsRead: (id?: string) =>
        request(
          '/api/me/notifications/read',
          { method: 'POST', body: JSON.stringify(id ? { id } : {}) },
          okSchema,
        ),
      follows: () => request('/api/me/follows', { method: 'GET' }, followsResponseSchema),
    },
    users: {
      profile: (idOrHandle: string) =>
        request(
          `/api/users/${encodeURIComponent(idOrHandle)}`,
          { method: 'GET' },
          userProfileResponseSchema,
        ),
    },
    collections: {
      list: () =>
        request(
          '/api/collections',
          { method: 'GET' },
          z.object({ items: z.array(collectionSchema) }),
        ),
      mine: () =>
        request(
          '/api/collections/mine',
          { method: 'GET' },
          z.object({ items: z.array(collectionSchema) }),
        ),
      get: (slug: string) =>
        request(
          `/api/collections/${encodeURIComponent(slug)}`,
          { method: 'GET' },
          collectionDetailSchema,
        ),
      create: (body: CollectionCreate) =>
        request(
          '/api/collections',
          { method: 'POST', body: JSON.stringify(body) },
          z.object({ collection: z.unknown() }),
        ),
      patch: (slug: string, body: CollectionPatch) =>
        request(
          `/api/collections/${encodeURIComponent(slug)}`,
          { method: 'PATCH', body: JSON.stringify(body) },
          okSchema,
        ),
      remove: (slug: string) =>
        request(`/api/collections/${encodeURIComponent(slug)}`, { method: 'DELETE' }, okSchema),
      addMod: (slug: string, modSlug: string) =>
        request(
          `/api/collections/${encodeURIComponent(slug)}/mods`,
          { method: 'POST', body: JSON.stringify({ modSlug }) },
          okSchema,
        ),
      removeMod: (slug: string, modSlug: string) =>
        request(
          `/api/collections/${encodeURIComponent(slug)}/mods/${encodeURIComponent(modSlug)}`,
          { method: 'DELETE' },
          okSchema,
        ),
      presignImage: (slug: string, body: CollectionImagePresign) =>
        request(
          `/api/collections/${encodeURIComponent(slug)}/image`,
          { method: 'POST', body: JSON.stringify(body) },
          imagePresignResponseSchema,
        ),
      reviews: {
        list: (slug: string) =>
          request(
            `/api/collections/${encodeURIComponent(slug)}/reviews`,
            { method: 'GET' },
            collectionReviewsResponseSchema,
          ),
        upsert: (slug: string, body: CollectionReviewUpsert) =>
          request(
            `/api/collections/${encodeURIComponent(slug)}/reviews`,
            { method: 'PUT', body: JSON.stringify(body) },
            okSchema,
          ),
        remove: (slug: string) =>
          request(
            `/api/collections/${encodeURIComponent(slug)}/reviews`,
            { method: 'DELETE' },
            okSchema,
          ),
      },
    },
    guides: {
      list: (params?: {
        q?: string;
        sort?: 'recent' | 'rating' | 'popular' | 'title';
        limit?: number;
        offset?: number;
      }) => {
        const qs = new URLSearchParams();
        if (params?.q) qs.set('q', params.q);
        if (params?.sort) qs.set('sort', params.sort);
        if (params?.limit != null) qs.set('limit', String(params.limit));
        if (params?.offset != null) qs.set('offset', String(params.offset));
        const suffix = qs.toString() ? `?${qs}` : '';
        return request(
          `/api/guides${suffix}`,
          { method: 'GET' },
          z.object({ items: z.array(guideListItemSchema) }),
        );
      },
      mine: () =>
        request(
          '/api/guides/mine',
          { method: 'GET' },
          z.object({ items: z.array(guideListItemSchema) }),
        ),
      pending: () =>
        request(
          '/api/guides/pending',
          { method: 'GET' },
          z.object({ items: z.array(guideListItemSchema) }),
        ),
      get: (slug: string) =>
        request(`/api/guides/${encodeURIComponent(slug)}`, { method: 'GET' }, guideListItemSchema),
      create: (body: GuideCreate) =>
        request(
          '/api/guides',
          { method: 'POST', body: JSON.stringify(body) },
          z.object({ guide: z.unknown() }),
        ),
      patch: (slug: string, body: GuidePatch) =>
        request(
          `/api/guides/${encodeURIComponent(slug)}`,
          { method: 'PATCH', body: JSON.stringify(body) },
          okSchema,
        ),
      remove: (slug: string) =>
        request(`/api/guides/${encodeURIComponent(slug)}`, { method: 'DELETE' }, okSchema),
      approve: (slug: string) =>
        request(`/api/guides/${encodeURIComponent(slug)}/approve`, { method: 'POST' }, okSchema),
      reject: (slug: string) =>
        request(`/api/guides/${encodeURIComponent(slug)}/reject`, { method: 'POST' }, okSchema),
      presignImage: (slug: string, body: GuideImagePresign) =>
        request(
          `/api/guides/${encodeURIComponent(slug)}/image`,
          { method: 'POST', body: JSON.stringify(body) },
          imagePresignResponseSchema,
        ),
      reviews: {
        list: (slug: string) =>
          request(
            `/api/guides/${encodeURIComponent(slug)}/reviews`,
            { method: 'GET' },
            guideReviewsResponseSchema,
          ),
        upsert: (slug: string, body: GuideReviewUpsert) =>
          request(
            `/api/guides/${encodeURIComponent(slug)}/reviews`,
            { method: 'PUT', body: JSON.stringify(body) },
            okSchema,
          ),
        remove: (slug: string) =>
          request(
            `/api/guides/${encodeURIComponent(slug)}/reviews`,
            { method: 'DELETE' },
            okSchema,
          ),
      },
    },
    telemetry: {
      run: (body: TelemetryRun) =>
        request('/api/telemetry/run', { method: 'POST', body: JSON.stringify(body) }, okSchema),
      crash: (body: CrashReport) =>
        request('/api/telemetry/crash', { method: 'POST', body: JSON.stringify(body) }, okSchema),
    },
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
