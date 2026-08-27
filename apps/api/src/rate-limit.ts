/**
 * Rate limiter for Hono.
 *
 * Two backends:
 *  - In-memory sliding window (default). Zero deps, but per-process: on a
 *    horizontally-scaled / serverless deploy each instance keeps its own
 *    counters, so the effective limit is `maxHits × instances`.
 *  - Upstash Redis (REST) fixed window, used automatically when
 *    `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN` are set. This makes
 *    limits correct across every instance. Dependency-free (uses fetch).
 *
 * Every limiter MUST be given a unique `name`. The bucket key is
 * `${name}:${keyFrom(c)}` so distinct limiters (auth vs upload vs download)
 * never share a counter — previously they all keyed on the bare IP and
 * clobbered each other's windows.
 */

interface Bucket {
  hits: number;
  resetAt: number;
}

const store = new Map<string, Bucket>();

// Prune expired entries every 5 minutes so a burst of unique IPs
// doesn't permanently leak memory.
setInterval(() => {
  const now = Date.now();
  for (const [key, bucket] of store) {
    if (now > bucket.resetAt) store.delete(key);
  }
}, 300_000).unref();

const DEFAULT_WINDOW_MS = 60_000;
const DEFAULT_MAX_HITS = 30;

/**
 * Upstash REST credentials, under either name they arrive as.
 *
 * `UPSTASH_REDIS_REST_*` is what Upstash's own docs use and what a
 * hand-configured deploy sets. The Vercel Marketplace integration
 * (`upstash/upstash-kv`) instead injects `KV_REST_API_URL` /
 * `KV_REST_API_TOKEN` and is the thing that ROTATES them, so reading only the
 * first pair means provisioning the integration correctly and still silently
 * falling back to per-instance counters. Copying the values across by hand
 * would fix that for exactly as long as the credentials stay put.
 *
 * `KV_REST_API_READ_ONLY_TOKEN` is deliberately not consulted: the limiter
 * INCRs, so a read-only token would fail every call and disable the limiter
 * in the least obvious way possible.
 *
 * Takes the environment as an argument rather than reading `process.env`
 * directly so it is testable: Vitest inlines `process.env.X` at transform
 * time, which makes a test that deletes a variable at runtime pass or fail
 * depending on what happens to be in the developer's own `.env.local`.
 */
export function resolveUpstashCredentials(env: Record<string, string | undefined>): {
  url: string;
  token: string;
} {
  return {
    url: (env.UPSTASH_REDIS_REST_URL || env.KV_REST_API_URL || '').trim().replace(/\/$/, ''),
    token: (env.UPSTASH_REDIS_REST_TOKEN || env.KV_REST_API_TOKEN || '').trim(),
  };
}

const { url: UPSTASH_URL, token: UPSTASH_TOKEN } = resolveUpstashCredentials(process.env);
const upstashEnabled = Boolean(UPSTASH_URL && UPSTASH_TOKEN);

/**
 * Atomic fixed-window increment via an Upstash REST pipeline:
 *   INCR key            → current count in this window
 *   EXPIRE key ttl NX   → set the window TTL only on the first hit
 * Returns the post-increment count, or null if the call failed (caller
 * then falls back to the in-memory limiter so a Redis outage can't take
 * the whole API down).
 */
async function upstashIncr(key: string, ttlSeconds: number): Promise<number | null> {
  try {
    const res = await fetch(`${UPSTASH_URL}/pipeline`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${UPSTASH_TOKEN}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify([
        ['INCR', key],
        ['EXPIRE', key, String(ttlSeconds), 'NX'],
      ]),
      // Don't let a slow store stall every request indefinitely.
      signal: AbortSignal.timeout(2_000),
    });
    if (!res.ok) return null;
    const out = (await res.json()) as Array<{ result?: number; error?: string }>;
    const count = out?.[0]?.result;
    return typeof count === 'number' ? count : null;
  } catch {
    return null;
  }
}

export function createRateLimiter(opts: {
  /** Unique limiter name; namespaces the counter key. Required. */
  name: string;
  windowMs?: number;
  maxHits?: number;
  keyFrom?: (c: import('hono').Context) => string;
}) {
  const name = opts.name;
  const windowMs = opts?.windowMs ?? DEFAULT_WINDOW_MS;
  const maxHits = opts?.maxHits ?? DEFAULT_MAX_HITS;
  const keyFrom =
    opts?.keyFrom ??
    ((c) => {
      // Prefer x-real-ip (set by the reverse proxy / platform, not
      // client-spoofable) over x-forwarded-for (which a client can forge
      // when the proxy doesn't strip the incoming header).
      const ip =
        c.req.header('x-real-ip') ??
        c.req.header('x-forwarded-for')?.split(',').pop()?.trim() ??
        'unknown';
      return ip;
    });

  function memoryLimit(c: import('hono').Context, key: string): Response | null {
    const now = Date.now();
    const bucket = store.get(key);
    if (!bucket || now > bucket.resetAt) {
      store.set(key, { hits: 1, resetAt: now + windowMs });
      return null;
    }
    bucket.hits++;
    if (bucket.hits > maxHits) {
      c.header('Retry-After', String(Math.ceil((bucket.resetAt - now) / 1000)));
      return c.json({ error: 'too many requests' }, 429);
    }
    return null;
  }

  return async function rateLimit(c: import('hono').Context, next: () => Promise<void>) {
    const key = `${name}:${keyFrom(c)}`;

    if (upstashEnabled) {
      const count = await upstashIncr(key, Math.ceil(windowMs / 1000));
      if (count !== null) {
        if (count > maxHits) {
          c.header('Retry-After', String(Math.ceil(windowMs / 1000)));
          return c.json({ error: 'too many requests' }, 429);
        }
        await next();
        return;
      }
      // Upstash unreachable — fall through to the in-memory limiter.
    }

    const blocked = memoryLimit(c, key);
    if (blocked) return blocked;
    await next();
  };
}
