import { afterEach, describe, expect, it } from 'vitest';
import { cleanApiUrl, getApiUrl } from './api-url';

const saved = process.env.NEXT_PUBLIC_API_URL;
afterEach(() => {
  process.env.NEXT_PUBLIC_API_URL = saved;
});

describe('NEXT_PUBLIC_API_URL', () => {
  it.each([
    ['https://api.rsmm.me', 'https://api.rsmm.me'],
    ['https://api.rsmm.me/\n', 'https://api.rsmm.me'],
    ['"https://api.rsmm.me"', 'https://api.rsmm.me'],
    ['  https://staging.rsmm.me  ', 'https://staging.rsmm.me'],
  ])('%j is used as %s', (raw, want) => {
    expect(cleanApiUrl(raw)).toBe(want);
  });

  it.each(['', '   ', 'api.rsmm.me', 'ftp://api.rsmm.me', 'not a url', undefined])(
    '%j is treated as unset',
    (raw) => {
      expect(cleanApiUrl(raw)).toBeUndefined();
    },
  );

  it('a malformed value falls back to production during the build (SSR)', () => {
    process.env.NEXT_PUBLIC_API_URL = 'api.rsmm.me\n';
    expect(getApiUrl()).toBe('https://api.rsmm.me');
  });
});
