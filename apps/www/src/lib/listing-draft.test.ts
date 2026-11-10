import { modDetailResponseSchema } from '@rsmm/api-client';
import { modPatchSchema } from '@rsmm/schemas';
import { describe, expect, it } from 'vitest';
import { listingChanges, readListingDraft } from './listing-draft';
import type { Screenshot } from './screenshot-gallery';

const detail = modDetailResponseSchema.parse({
  mod: {
    id: '89fcd3ae-bceb-4152-bcb0-6b1c6f314b5d',
    slug: 'sample',
    name: 'Sample mod',
    author: 'Author',
    summary: 'Summary',
    description: 'Saved description',
    license: 'MIT',
    repoUrl: 'https://github.com/example/mod',
    homepageUrl: 'https://example.com',
    latestVersion: null,
    downloads: 0,
    updatedAt: '2026-11-10T10:00:00.000Z',
    category: null,
    imageUrl: 'https://example.com/cover.png',
    rating: null,
    tags: ['qol'],
    screenshots: [{ url: 'https://example.com/other.png', caption: 'Gameplay' }],
    videos: [],
  },
  versions: [],
});
const saved = readListingDraft(detail);
const [cover, other] = saved.photos as [Screenshot, Screenshot];

describe('listing draft', () => {
  it('loads stored text, URLs and an unset category without making the listing dirty', () => {
    expect(saved.description).toBe('Saved description');
    expect(saved.repoUrl).toBe('https://github.com/example/mod');
    expect(saved.homepageUrl).toBe('https://example.com');
    expect(saved.category).toBeNull();
    expect(listingChanges(saved, readListingDraft(detail))).toEqual({});
  });

  it('does not replace a deliberately cleared description with a manifest fallback', () => {
    expect(
      readListingDraft({ ...detail, mod: { ...detail.mod, description: null } }).description,
    ).toBe('');
  });

  it('only patches changed fields, preserving unedited remote text and URLs', () => {
    expect(listingChanges(saved, { ...saved, name: 'Updated name' })).toEqual({
      name: 'Updated name',
    });
    expect(listingChanges(saved, { ...saved, summary: '', repoUrl: '' })).toEqual({
      summary: null,
      repoUrl: null,
    });
  });

  it('combines metadata, videos, captions and cover ordering in one valid patch', () => {
    const draft = {
      ...saved,
      name: 'Updated',
      videos: ['https://youtu.be/example'],
      photos: [{ ...other, caption: ' New caption ' }, cover],
    };
    const patch = listingChanges(saved, draft);
    expect(modPatchSchema.safeParse(patch).success).toBe(true);
    expect(patch).toEqual({
      name: 'Updated',
      videos: draft.videos,
      imageUrl: other.url,
      screenshots: [{ ...other, caption: 'New caption' }, cover],
    });
    expect(cover.url).toBe(detail.mod.imageUrl);
  });

  it('clears both cover and gallery when all photos are removed', () => {
    expect(listingChanges(saved, { ...saved, photos: [] })).toEqual({
      imageUrl: null,
      screenshots: [],
    });
  });

  it('becomes clean when edits are reverted, including caption whitespace', () => {
    expect(
      listingChanges(saved, {
        ...saved,
        tags: ' qol, ',
        name: ' Sample mod ',
        photos: saved.photos.map((p) => ({ ...p, caption: p.caption ? ` ${p.caption} ` : '' })),
      }),
    ).toEqual({});
    expect(listingChanges(saved, structuredClone(saved))).toEqual({});
  });

  it('keeps newer edits dirty when an earlier submitted snapshot becomes the baseline', () => {
    const submitted = { ...saved, summary: 'Submitted' };
    const editedWhileSaving = {
      ...submitted,
      summary: 'Still editing',
      photos: [...saved.photos].reverse(),
    };
    const remaining = listingChanges(submitted, editedWhileSaving);
    expect(remaining.summary).toBe('Still editing');
    expect(remaining.imageUrl).toBe(other.url);
    expect(listingChanges(submitted, structuredClone(submitted))).toEqual({});
  });

  it('validates invalid URLs and excessive tags instead of silently truncating edits', () => {
    expect(
      modPatchSchema.safeParse(listingChanges(saved, { ...saved, repoUrl: 'invalid' })).success,
    ).toBe(false);
    expect(
      modPatchSchema.safeParse(
        listingChanges(saved, {
          ...saved,
          tags: Array.from({ length: 17 }, (_, i) => `tag-${i}`).join(','),
        }),
      ).success,
    ).toBe(false);
  });
});
