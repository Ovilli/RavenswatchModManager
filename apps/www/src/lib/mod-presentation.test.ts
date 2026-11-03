import { describe, expect, it } from 'vitest';
import { formatFileSize, formatModDate, getDownloadVersion, getModMedia } from './mod-presentation';

describe('mod media', () => {
  it('combines cover, screenshots and videos without duplicating the cover, preserving captions', () => {
    expect(
      getModMedia({
        name: 'Example',
        imageUrl: 'https://example.com/cover.png',
        screenshots: [
          { url: 'https://example.com/cover.png', caption: 'In-game overview' },
          { url: 'https://example.com/detail.png', caption: 'A closer look' },
        ],
        videos: ['https://example.com/video', 'https://example.com/video'],
      }),
    ).toEqual([
      { kind: 'image', url: 'https://example.com/cover.png', label: 'In-game overview' },
      { kind: 'image', url: 'https://example.com/detail.png', label: 'A closer look' },
      { kind: 'video', url: 'https://example.com/video', label: 'Example video 1' },
    ]);
  });

  it('can use a screenshot without a cover and does not invent media for empty listings', () => {
    expect(
      getModMedia({
        name: 'Example',
        imageUrl: null,
        screenshots: [{ url: 'https://example.com/a.png' }],
      }),
    ).toEqual([{ kind: 'image', url: 'https://example.com/a.png', label: 'Example screenshot 1' }]);
    expect(getModMedia({ name: 'Example', imageUrl: null })).toEqual([]);
  });
});

describe('download presentation', () => {
  it('does not invent a downloadable release from a stale latestVersion field', () => {
    expect(getDownloadVersion([], '1.0.0')).toBeUndefined();
  });
  it('keeps small files legible instead of rounding them to 0.00 MB', () => {
    expect(formatFileSize(400)).toBe('400 B');
    expect(formatFileSize(34303)).toBe('33.5 KB');
    expect(formatFileSize(1024 * 1024)).toBe('1 MB');
  });
  it('formats the same publication date on the server and in any client timezone', () => {
    expect(formatModDate('2026-10-17T00:01:00.000Z')).toBe('Oct 17, 2026');
  });
});
