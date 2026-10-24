import { afterEach, describe, expect, it, vi } from 'vitest';
import { freshListUrl } from './api';

const store = new Map<string, string>();

function browser(lastWrite: number | null) {
  store.clear();
  if (lastWrite != null) store.set('rsmm:lastWrite', String(lastWrite));
  vi.stubGlobal('window', { location: { href: 'https://rsmm.me/' } });
  vi.stubGlobal('localStorage', { getItem: (k: string) => store.get(k) ?? null });
}

afterEach(() => vi.unstubAllGlobals());

describe('freshListUrl', () => {
  it('busts the CDN-cached lists right after a write', () => {
    const t = Date.now() - 1000;
    browser(t);
    expect(freshListUrl('https://api.rsmm.me/api/mods?limit=20')).toBe(
      `https://api.rsmm.me/api/mods?limit=20&fresh=${t}`,
    );
    expect(freshListUrl('https://api.rsmm.me/api/guides')).toContain(`fresh=${t}`);
  });

  it('leaves other routes, old writes and no writes alone', () => {
    browser(Date.now() - 1000);
    expect(freshListUrl('https://api.rsmm.me/api/mods/x')).toBe('https://api.rsmm.me/api/mods/x');
    browser(Date.now() - 7 * 60_000);
    expect(freshListUrl('https://api.rsmm.me/api/mods')).toBe('https://api.rsmm.me/api/mods');
    browser(null);
    expect(freshListUrl('https://api.rsmm.me/api/mods')).toBe('https://api.rsmm.me/api/mods');
  });
});
