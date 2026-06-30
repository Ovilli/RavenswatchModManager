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

const UPSTASH_URL = process.env.UPSTASH_REDIS_REST_URL?.replace(/\/$/, '') ?? '';
const UPSTASH_TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN ?? '';
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
