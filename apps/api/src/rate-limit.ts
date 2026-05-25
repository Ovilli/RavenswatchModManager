/**
 * Simple in-memory sliding-window rate limiter for Hono.
 * No external dependencies. Resets on server restart.
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

export function createRateLimiter(opts?: {
  windowMs?: number;
  maxHits?: number;
  keyFrom?: (c: import('hono').Context) => string;
}) {
  const windowMs = opts?.windowMs ?? DEFAULT_WINDOW_MS;
  const maxHits = opts?.maxHits ?? DEFAULT_MAX_HITS;
  const keyFrom = opts?.keyFrom ?? ((c) => {
    // Prefer x-real-ip (set by nginx/reverse-proxy, cannot be spoofed
    // by the client) over x-forwarded-for (which the client can forge
    // when the proxy doesn't strip the incoming header).
    const ip = c.req.header('x-real-ip')
      ?? c.req.header('x-forwarded-for')?.split(',').pop()?.trim()
      ?? 'unknown';
    return ip;
  });

  return async function rateLimit(c: import('hono').Context, next: () => Promise<void>) {
    const key = keyFrom(c);
    const now = Date.now();
    let bucket = store.get(key);

    if (!bucket || now > bucket.resetAt) {
      bucket = { hits: 1, resetAt: now + windowMs };
      store.set(key, bucket);
      await next();
      return;
    }

    bucket.hits++;
    if (bucket.hits > maxHits) {
      c.header('Retry-After', String(Math.ceil((bucket.resetAt - now) / 1000)));
      return c.json({ error: 'too many requests' }, 429);
    }

    await next();
  };
}
