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
  type ReviewUpsert,
  type TelemetryRun,
  collectionDetailSchema,
  collectionReviewsResponseSchema,
  collectionSchema,
  guideListItemSchema,
  guideReviewsResponseSchema,
  modListItemSchema,
  modVersionSchema,
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

  const modListResponseSchema = z.object({
    items: z.array(modListItemSchema),
    total: z.number().int().nonnegative(),
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
      joinedAt: z.string(),
    }),
    mods: z.array(modListItemSchema),
    totalDownloads: z.number().int().nonnegative(),
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
          limit?: number;
          offset?: number;
          featured?: boolean;
          owner?: string;
          sort?: 'recent' | 'popular' | 'featured';
        } = {},
      ) => {
        const qs = new URLSearchParams();
        if (params.q) qs.set('q', params.q);
        if (params.tag) qs.set('tag', params.tag);
        if (params.limit) qs.set('limit', String(params.limit));
        if (params.offset) qs.set('offset', String(params.offset));
        if (params.featured) qs.set('featured', 'true');
        if (params.owner) qs.set('owner', params.owner);
        if (params.sort) qs.set('sort', params.sort);
        return request<{ items: ModListItem[]; total: number }>(
          `/api/mods?${qs}`,
          { method: 'GET' },
          modListResponseSchema,
        );
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
