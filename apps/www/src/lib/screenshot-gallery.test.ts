import { MAX_MOD_PHOTOS, modPatchSchema } from '@rsmm/schemas';
import { describe, expect, it, vi } from 'vitest';
import {
  type Screenshot,
  getListingPhotos,
  listingPhotoPatch,
  moveScreenshot,
  selectScreenshotFiles,
  uploadScreenshotBatch,
} from './screenshot-gallery';

function file(name: string, type = 'image/png', size = 100) {
  return new File([new Uint8Array(size)], name, { type });
}

describe('screenshot selection', () => {
  it('keeps picker order and only accepts files that fit the remaining slots', () => {
    const files = [file('first.png'), file('second.png'), file('third.png')];
    const result = selectScreenshotFiles(files, MAX_MOD_PHOTOS - 2);
    expect(result.accepted).toEqual(files.slice(0, 2));
    expect(result.issues).toEqual([{ file: files[2], message: expect.stringContaining('13') }]);
  });

  it('rejects unsupported, empty and oversized files before upload without consuming a slot', () => {
    const invalid = [file('gif.gif', 'image/gif'), file('empty.png', 'image/png', 0)];
    const large = file('large.png', 'image/png', 8_000_001);
    const valid = file('valid.webp', 'image/webp', 8_000_000);
    const result = selectScreenshotFiles([...invalid, large, valid], 11);
    expect(result.accepted).toEqual([valid]);
    expect(result.issues.map((issue) => issue.file)).toEqual([...invalid, large]);
  });

  it('accepts JPEG and rejects every file when the gallery is full', () => {
    const jpeg = file('photo.jpg', 'image/jpeg');
    expect(selectScreenshotFiles([jpeg], 0).accepted).toEqual([jpeg]);
    expect(selectScreenshotFiles([jpeg], MAX_MOD_PHOTOS).accepted).toEqual([]);
    expect(selectScreenshotFiles([], 0)).toEqual({ accepted: [], issues: [] });
  });
});

describe('batch upload', () => {
  it('continues after a failed file, keeps selection order, and returns only failures for retry', async () => {
    const files = [file('one.png'), file('two.png'), file('three.png')];
    const error = new Error('Storage unavailable');
    const upload = vi.fn(async (image: File) => {
      if (image === files[1]) throw error;
      return `https://cdn.example.com/${image.name}`;
    });
    const onFile = vi.fn();
    const result = await uploadScreenshotBatch(files, upload, onFile);
    expect(result.screenshots).toEqual([
      { url: 'https://cdn.example.com/one.png' },
      { url: 'https://cdn.example.com/three.png' },
    ]);
    expect(result.failures).toEqual([{ file: files[1], error }]);
    expect(onFile.mock.calls).toEqual(files.map((image, index) => [image, index]));
    expect(upload).toHaveBeenCalledTimes(3);
  });

  it('never starts the next upload until the current one finishes', async () => {
    let finish = (_url: string) => {};
    const upload = vi
      .fn<(_: File) => Promise<string>>()
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      )
      .mockResolvedValue('https://cdn.example.com/two.png');
    const result = uploadScreenshotBatch([file('one.png'), file('two.png')], upload, () => {});
    expect(upload).toHaveBeenCalledTimes(1);
    finish('https://cdn.example.com/one.png');
    expect((await result).screenshots).toHaveLength(2);
    expect(upload).toHaveBeenCalledTimes(2);
  });
});

describe('screenshot ordering and persistence', () => {
  const shots: [Screenshot, Screenshot, Screenshot] = [
    { url: 'https://cdn.example.com/a.png', caption: 'First' },
    { url: 'https://cdn.example.com/b.png', caption: 'Second' },
    { url: 'https://cdn.example.com/c.png', caption: 'Third' },
  ];

  it('moves the image and its caption together without mutating the original', () => {
    expect(moveScreenshot(shots, shots[1].url, 0)).toEqual([shots[1], shots[0], shots[2]]);
    expect(moveScreenshot(shots, shots[1].url, 2)).toEqual([shots[0], shots[2], shots[1]]);
    expect(shots.map((shot) => shot.caption)).toEqual(['First', 'Second', 'Third']);
  });

  it('moves across multiple positions in either direction', () => {
    expect(moveScreenshot(shots, shots[0].url, 2)).toEqual([shots[1], shots[2], shots[0]]);
    expect(moveScreenshot(shots, shots[2].url, 0)).toEqual([shots[2], shots[0], shots[1]]);
  });

  it('leaves unchanged drops, invalid positions and missing images alone', () => {
    expect(moveScreenshot(shots, shots[1].url, 1)).toBe(shots);
    expect(moveScreenshot(shots, shots[1].url, Number.NaN)).toBe(shots);
    expect(moveScreenshot(shots, shots[1].url, 0.5)).toBe(shots);
    expect(moveScreenshot(shots, shots[0].url, -1)).toBe(shots);
    expect(moveScreenshot(shots, shots[2].url, 3)).toBe(shots);
    expect(moveScreenshot(shots, 'missing', -1)).toBe(shots);
    expect(moveScreenshot([], 'missing', 1)).toEqual([]);
  });
});

describe('unified listing photos', () => {
  const cover = { url: 'https://cdn.example.com/cover.png', caption: 'Cover caption' };
  const other = { url: 'https://cdn.example.com/other.png', caption: 'Gameplay' };

  it('puts the legacy cover first, deduplicates URLs, and preserves its existing caption', () => {
    expect(getListingPhotos(cover.url, [other, cover, { url: other.url }])).toEqual([cover, other]);
    expect(getListingPhotos(cover.url)).toEqual([{ url: cover.url }]);
    expect(getListingPhotos(null, [other])).toEqual([other]);
    expect(getListingPhotos(undefined)).toEqual([]);
  });

  it('preserves a separate legacy cover and all 12 screenshots through a save and reload', () => {
    const screenshots = Array.from({ length: 12 }, (_, index) => ({
      url: `https://cdn.example.com/${index}.png`,
      caption: `Photo ${index}`,
    }));
    const photos = getListingPhotos(cover.url, screenshots);
    expect(photos).toHaveLength(MAX_MOD_PHOTOS);
    const patch = modPatchSchema.parse(listingPhotoPatch(photos));
    expect(getListingPhotos(patch.imageUrl, patch.screenshots)).toEqual(photos);
    expect(modPatchSchema.safeParse(listingPhotoPatch([...photos, other])).success).toBe(false);
  });

  it('changes the cover and gallery atomically and keeps both captions after a cover swap', () => {
    const next = moveScreenshot([cover, other], other.url, 0);
    const patch = listingPhotoPatch(next);
    expect(patch).toEqual({ imageUrl: other.url, screenshots: [other, cover] });
    expect(getListingPhotos(patch.imageUrl, patch.screenshots)).toEqual([other, cover]);
  });

  it('promotes the next photo when deleting the cover and clears both fields when empty', () => {
    expect(listingPhotoPatch([cover, other].filter((photo) => photo.url !== cover.url))).toEqual({
      imageUrl: other.url,
      screenshots: [other],
    });
    expect(listingPhotoPatch([])).toEqual({ imageUrl: null, screenshots: [] });
    expect(listingPhotoPatch([other])).toEqual({ imageUrl: other.url, screenshots: [other] });
  });
});
