import { describe, expect, it } from 'vitest';
import { detectDownloadPlatform } from './download-platform';

describe('download platform detection', () => {
  it.each([
    ['Windows Chrome', 'Win32', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Windows'],
    ['Windows Firefox', 'Win32', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0)', 'Windows'],
    ['Linux', 'Linux x86_64', 'Mozilla/5.0 (X11; Linux x86_64)', 'Linux'],
    ['Steam Deck', 'Linux x86_64', 'Mozilla/5.0 (X11; Linux x86_64; Steam Deck)', 'Linux'],
    ['macOS', 'MacIntel', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', 'unsupported'],
    ['Android', 'Linux armv8l', 'Mozilla/5.0 (Linux; Android 14; Pixel 8)', 'unsupported'],
    ['iPhone', 'iPhone', 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)', 'unsupported'],
    [
      'iPad desktop mode',
      'MacIntel',
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15)',
      'unsupported',
    ],
    ['ChromeOS', 'Linux x86_64', 'Mozilla/5.0 (X11; CrOS x86_64 16093.0.0)', 'unsupported'],
    ['Windows Phone', 'Win32', 'Mozilla/5.0 (Windows Phone 10.0; Android 6.0.1)', 'unsupported'],
    ['hidden platform', '', '', 'unknown'],
    ['unrecognized platform', 'FreeBSD', 'Mozilla/5.0 (X11; FreeBSD amd64)', 'unknown'],
  ])('%s gets the appropriate download choice', (_, platform, userAgent, expected) => {
    expect(detectDownloadPlatform({ platform, userAgent })).toBe(expected);
  });

  it.each([
    ['Windows', false, 'Windows'],
    ['Linux', false, 'Linux'],
    ['macOS', false, 'unsupported'],
    ['Android', false, 'unsupported'],
    ['Chrome OS', false, 'unsupported'],
    ['Linux', true, 'unsupported'],
  ])('uses client hints for %s (mobile: %s)', (platform, mobile, expected) => {
    expect(
      detectDownloadPlatform({
        platform: '',
        userAgent: '',
        userAgentData: { platform, mobile },
      }),
    ).toBe(expected);
  });

  it('falls back to the user agent when the platform hint is unknown', () => {
    expect(
      detectDownloadPlatform({
        platform: '',
        userAgent: 'Mozilla/5.0 (X11; Linux x86_64)',
        userAgentData: { platform: 'Unknown' },
      }),
    ).toBe('Linux');
  });
});
