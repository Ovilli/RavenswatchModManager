import { createHash } from 'node:crypto';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchPublicObject } from '../src/storage.js';

// The scanner's fallback read. A verdict is only worth something for bytes
// that were hashed, so this must hash EVERY byte — including past the point
// where it stops buffering — and report a failed read as null, never a hash.
const sha = (b: Buffer) => createHash('sha256').update(b).digest('hex');

function serve(body: Buffer, status = 200) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(status === 200 ? new Uint8Array(body) : null, { status })),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe('fetchPublicObject', () => {
  const body = Buffer.from('x'.repeat(4096));

  it('hashes and keeps an object within the cap', async () => {
    serve(body);
    const r = await fetchPublicObject('https://cdn.example/mods/a.zip', body.length);
    expect(r?.sha256).toBe(sha(body));
    expect(r?.bytes?.equals(body)).toBe(true);
  });

  it('still hashes the whole object past the cap, but drops the bytes', async () => {
    serve(body);
    const r = await fetchPublicObject('https://cdn.example/mods/a.zip', 100);
    expect(r?.sha256).toBe(sha(body));
    expect(r?.bytes).toBeNull();
  });

  it('returns null for a missing object instead of hashing the error page', async () => {
    serve(Buffer.from('NoSuchKey'), 404);
    expect(await fetchPublicObject('https://cdn.example/mods/a.zip', 1024)).toBeNull();
  });
});
