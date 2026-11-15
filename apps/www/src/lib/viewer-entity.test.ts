import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  cookies: vi.fn(),
  publicLookup: vi.fn(),
  fetch: vi.fn(),
}));
vi.mock('next/headers', () => ({ cookies: mocks.cookies }));
vi.mock('./api-url', () => ({ getApiUrl: () => 'https://api.example.com' }));
vi.mock('./entity', () => ({ fetchEntity: mocks.publicLookup }));
import { fetchViewerEntity } from './viewer-entity';

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubGlobal('fetch', mocks.fetch);
  mocks.publicLookup.mockResolvedValue({ state: 'missing' });
  mocks.cookies.mockResolvedValue({ toString: () => 'session=test-session' });
});
afterEach(() => vi.unstubAllGlobals());

describe('viewer-specific listing fallback', () => {
  it('keeps public pages anonymous and cacheable', async () => {
    const result = { state: 'ok', data: { name: 'Public listing', canEdit: false } };
    mocks.publicLookup.mockResolvedValue(result);
    expect(await fetchViewerEntity('/api/collections/sample')).toEqual(result);
    expect(mocks.cookies).not.toHaveBeenCalled();
    expect(mocks.fetch).not.toHaveBeenCalled();
  });

  it('does not retry anonymous 404s or transient public API failures', async () => {
    mocks.cookies.mockResolvedValue({ toString: () => '' });
    expect(await fetchViewerEntity('/api/collections/sample')).toEqual({ state: 'missing' });
    mocks.publicLookup.mockResolvedValue({ state: 'error' });
    expect(await fetchViewerEntity('/api/mods/sample')).toEqual({ state: 'error' });
    expect(mocks.fetch).not.toHaveBeenCalled();
  });

  it('retries a private collection or delisted mod with an uncached session request', async () => {
    for (const path of ['/api/collections/sample', '/api/mods/sample']) {
      mocks.fetch.mockResolvedValue(Response.json({ name: 'Private listing', canEdit: true }));
      expect(await fetchViewerEntity(path)).toEqual({
        state: 'ok',
        data: { name: 'Private listing', canEdit: true },
      });
      expect(mocks.fetch).toHaveBeenLastCalledWith(`https://api.example.com${path}`, {
        headers: { cookie: 'session=test-session' },
        cache: 'no-store',
      });
    }
  });

  it('keeps denied or missing listings as 404s and failures as errors', async () => {
    for (const status of [404, 410, 500]) {
      mocks.fetch.mockResolvedValue(new Response(null, { status }));
      expect(await fetchViewerEntity('/api/collections/sample')).toEqual({
        state: status === 500 ? 'error' : 'missing',
      });
    }
    mocks.fetch.mockRejectedValue(new Error('Network unavailable'));
    expect(await fetchViewerEntity('/api/collections/sample')).toEqual({ state: 'error' });
  });
});
