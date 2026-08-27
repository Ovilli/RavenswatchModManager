import { describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  ApiTimeoutError,
  RateLimitError,
  createApiClient,
  isRateLimited,
} from '../index';

/** A minimal, well-formed `/api/mods` page — the schema's happy path. */
const EMPTY_PAGE = { items: [], total: 0 };

function json(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

/**
 * A fetch stub that replays a scripted sequence of outcomes, one per call, and
 * records what it was asked for. A plain `Response` is returned; an `Error` is
 * thrown (the network-level failure shape).
 */
function scriptedFetch(steps: (Response | Error | (() => Response | Error))[]) {
  const calls: { url: string; init: RequestInit }[] = [];
  const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init: init ?? {} });
    const step = steps[Math.min(calls.length - 1, steps.length - 1)] as
      | Response
      | Error
      | (() => Response | Error);
    const value = typeof step === 'function' ? step() : step;
    if (value instanceof Error) throw value;
    return value;
  }) as unknown as typeof fetch;
  return {
    fetchImpl,
    calls,
    get count() {
      return calls.length;
    },
    /** The nth call, asserted to exist so the assertions below read plainly. */
    call(n: number) {
      const c = calls[n];
      if (!c) throw new Error(`expected at least ${n + 1} fetch calls, saw ${calls.length}`);
      return c;
    },
  };
}

function client(
  steps: (Response | Error | (() => Response | Error))[],
  overrides: Partial<Parameters<typeof createApiClient>[0]> = {},
) {
  const script = scriptedFetch(steps);
  const sleep = vi.fn(async (_ms: number) => {});
  const api = createApiClient({
    baseUrl: 'https://api.example.com/',
    fetch: script.fetchImpl,
    sleep,
    retryBackoffMs: 100,
    ...overrides,
  });
  return { api, script, sleep };
}

describe('request plumbing', () => {
  it('joins the base url without doubling the slash and sends JSON headers', async () => {
    const { api, script } = client([json(EMPTY_PAGE)], { getToken: () => 'tok-123' });
    await api.mods.list();

    expect(script.call(0).url).toBe('https://api.example.com/api/mods?');
    const headers = script.call(0).init.headers as Record<string, string>;
    expect(headers['Content-Type']).toBe('application/json');
    expect(headers.Authorization).toBe('Bearer tok-123');
    // Better Auth's session cookie rides on this; dropping it logs every
    // desktop user out silently.
    expect(script.call(0).init.credentials).toBe('include');
  });

  it('omits Authorization when there is no token', async () => {
    const { api, script } = client([json(EMPTY_PAGE)]);
    await api.mods.list();
    expect((script.call(0).init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it('encodes list params into the query string', async () => {
    const { api, script } = client([json(EMPTY_PAGE)]);
    await api.mods.list({ q: 'damage meter', tags: ['ui', 'hud'], limit: 10, sort: 'popular' });

    const qs = new URL(script.call(0).url).searchParams;
    expect(qs.get('q')).toBe('damage meter');
    expect(qs.get('tags')).toBe('ui,hud');
    expect(qs.get('limit')).toBe('10');
    expect(qs.get('sort')).toBe('popular');
  });

  it('escapes a slug rather than letting it alter the path', async () => {
    const { api, script } = client([json({ mod: null, versions: [] })]);
    await api.mods.get('../admin').catch(() => {});
    expect(script.call(0).url).toBe('https://api.example.com/api/mods/..%2Fadmin');
  });
});

describe('error mapping', () => {
  it('maps a non-ok response to ApiError carrying status and body', async () => {
    const { api } = client([json({ error: 'nope' }, { status: 403 })]);
    await expect(api.mods.list()).rejects.toMatchObject({
      name: 'ApiError',
      status: 403,
      body: { error: 'nope' },
    });
  });

  it('maps 429 to RateLimitError and reads Retry-After', async () => {
    const { api } = client([
      json({ error: 'slow down' }, { status: 429, headers: { 'Retry-After': '42' } }),
    ]);
    const err = await api.mods.list().catch((e) => e);
    expect(err).toBeInstanceOf(RateLimitError);
    expect(isRateLimited(err)).toBe(true);
    expect((err as RateLimitError).retryAfter).toBe(42);
  });

  it('defaults Retry-After to 60 when the header is missing or junk', async () => {
    const cases: Record<string, string>[] = [
      {},
      { 'Retry-After': 'Wed, 21 Oct 2026 07:28:00 GMT' },
    ];
    for (const headers of cases) {
      const { api } = client([json({}, { status: 429, headers })]);
      const err = (await api.mods.list().catch((e) => e)) as RateLimitError;
      expect(err.retryAfter).toBe(60);
    }
  });

  it('rejects a 200 whose body does not match the schema', async () => {
    // A shape drift on the server must not reach callers as a half-typed
    // object — the desktop app renders these fields directly.
    const { api } = client([json({ items: [{ id: 1 }], total: 'lots' })]);
    const err = (await api.mods.list().catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toContain('response validation failed');
    expect(err.status).toBe(200);
  });

  it('treats an unparseable body as null rather than throwing raw', async () => {
    const { api } = client([
      new Response('<!doctype html><h1>502 Bad Gateway</h1>', {
        status: 500,
        headers: { 'Content-Type': 'text/html' },
      }),
    ]);
    await expect(api.mods.list()).rejects.toMatchObject({ status: 500, body: null });
  });

  it('raises ApiTimeoutError when the request outruns timeoutMs', async () => {
    const hang = vi.fn(
      (_url: string | URL | Request, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            reject(new DOMException('aborted', 'AbortError'));
          });
        }),
    ) as unknown as typeof fetch;
    const api = createApiClient({
      baseUrl: 'https://api.example.com',
      fetch: hang,
      timeoutMs: 5,
      retries: 0,
    });
    const err = (await api.mods.list().catch((e) => e)) as ApiTimeoutError;
    expect(err).toBeInstanceOf(ApiTimeoutError);
    expect(err.status).toBe(0);
    expect(err.message).toContain('timed out after 5ms');
  });
});

describe('retry policy', () => {
  it('retries a 503 on GET and returns the eventual success', async () => {
    const { api, script, sleep } = client([
      json({}, { status: 503 }),
      json({}, { status: 503 }),
      json(EMPTY_PAGE),
    ]);
    await expect(api.mods.list()).resolves.toEqual(EMPTY_PAGE);
    expect(script.count).toBe(3);
    // Exponential from retryBackoffMs, not a flat wait.
    expect(sleep.mock.calls.map((c) => c[0])).toEqual([100, 200]);
  });

  it('retries a network-level throw', async () => {
    const { api, script } = client([new TypeError('fetch failed'), json(EMPTY_PAGE)]);
    await expect(api.mods.list()).resolves.toEqual(EMPTY_PAGE);
    expect(script.count).toBe(2);
  });

  it('gives up after `retries` extra attempts and rethrows the last error', async () => {
    const { api, script } = client([json({}, { status: 502 })]);
    await expect(api.mods.list()).rejects.toMatchObject({ status: 502 });
    expect(script.count).toBe(3); // 1 + default 2 retries
  });

  it('honours retries: 0', async () => {
    const { api, script } = client([json({}, { status: 503 })], { retries: 0 });
    await expect(api.mods.list()).rejects.toMatchObject({ status: 503 });
    expect(script.count).toBe(1);
  });

  it('does not retry a 4xx, which would fail identically forever', async () => {
    for (const status of [400, 401, 403, 404, 409, 422]) {
      const { api, script } = client([json({}, { status })]);
      await expect(api.mods.list()).rejects.toMatchObject({ status });
      expect(script.count, `status ${status}`).toBe(1);
    }
  });

  it('does not retry a 500, which usually means a real server-side bug', async () => {
    const { api, script } = client([json({}, { status: 500 })]);
    await expect(api.mods.list()).rejects.toMatchObject({ status: 500 });
    expect(script.count).toBe(1);
  });

  it('does not retry a rate limit — the caller owns Retry-After', async () => {
    const { api, script } = client([json({}, { status: 429 })]);
    await expect(api.mods.list()).rejects.toBeInstanceOf(RateLimitError);
    expect(script.count).toBe(1);
  });

  it('does not retry a timeout — the wallclock bound was the caller’s choice', async () => {
    const hang = vi.fn(
      (_url: string | URL | Request, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            reject(new DOMException('aborted', 'AbortError'));
          });
        }),
    ) as unknown as typeof fetch;
    const api = createApiClient({
      baseUrl: 'https://api.example.com',
      fetch: hang,
      timeoutMs: 5,
      retryBackoffMs: 0,
    });
    await expect(api.mods.list()).rejects.toBeInstanceOf(ApiTimeoutError);
    expect(hang).toHaveBeenCalledTimes(1);
  });

  it('does not retry a schema failure — the body will not change', async () => {
    const { api, script } = client([json({ items: 'nope' })]);
    await expect(api.mods.list()).rejects.toBeInstanceOf(ApiError);
    expect(script.count).toBe(1);
  });

  it('never retries a write, which may already have taken effect', async () => {
    // A 503 from the edge does not prove the upload did not land; repeating it
    // would create a second version row.
    const { api, script } = client([json({}, { status: 503 })]);
    await expect(
      api.mods.upload({ slug: 'x', name: 'x', version: '1.0.0', size: 1 } as never),
    ).rejects.toMatchObject({ status: 503 });
    expect(script.count).toBe(1);
  });

  it('retries the retry-explicit statuses', async () => {
    for (const status of [408, 425, 502, 503, 504]) {
      const { api, script } = client([json({}, { status }), json(EMPTY_PAGE)]);
      await expect(api.mods.list()).resolves.toEqual(EMPTY_PAGE);
      expect(script.count, `status ${status}`).toBe(2);
    }
  });
});
