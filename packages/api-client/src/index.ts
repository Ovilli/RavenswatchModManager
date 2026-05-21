import {
  type CrashReport,
  type ModListItem,
  modListItemSchema,
  type ModUploadRequest,
  type ModVersion,
  modVersionSchema,
  type TelemetryRun,
} from '@rsmm/schemas';
import { z } from 'zod';

export interface ApiClientOptions {
  baseUrl: string;
  fetch?: typeof fetch;
  getToken?: () => string | null | undefined;
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

export function createApiClient(options: ApiClientOptions) {
  const f = options.fetch ?? fetch;
  const headers = (): Record<string, string> => {
    const h: Record<string, string> = { 'Content-Type': 'application/json' };
    const tok = options.getToken?.();
    if (tok) h.Authorization = `Bearer ${tok}`;
    return h;
  };

  async function request<T>(path: string, init: RequestInit, schema: z.ZodType<T>): Promise<T> {
    const baseUrl = options.baseUrl.replace(/\/+$/, '');
    const res = await f(`${baseUrl}${path}`, {
      ...init,
      headers: { ...headers(), ...(init.headers ?? {}) },
      credentials: 'include',
    });
    const json = await res.json().catch(() => null);
    if (!res.ok) throw new ApiError(`${res.status} ${path}`, res.status, json);
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
    mod: modListItemSchema,
    versions: z.array(modVersionSchema),
  });
  const okSchema = z.object({ ok: z.literal(true) });
  const uploadResponseSchema = z.object({
    uploadUrl: z.string().url(),
    publicUrl: z.string().url(),
    versionId: z.string().uuid(),
    expiresIn: z.number().int().positive(),
  });

  return {
    mods: {
      list: (params: { q?: string; tag?: string; limit?: number; offset?: number } = {}) => {
        const qs = new URLSearchParams();
        if (params.q) qs.set('q', params.q);
        if (params.tag) qs.set('tag', params.tag);
        if (params.limit) qs.set('limit', String(params.limit));
        if (params.offset) qs.set('offset', String(params.offset));
        return request<{ items: ModListItem[]; total: number }>(
          `/api/mods?${qs}`,
          { method: 'GET' },
          modListResponseSchema,
        );
      },
      get: (slug: string) =>
        request<{ mod: ModListItem; versions: ModVersion[] }>(
          `/api/mods/${encodeURIComponent(slug)}`,
          { method: 'GET' },
          modDetailResponseSchema,
        ),
      upload: (body: ModUploadRequest) =>
        request('/api/mods/upload', { method: 'POST', body: JSON.stringify(body) }, uploadResponseSchema),
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
