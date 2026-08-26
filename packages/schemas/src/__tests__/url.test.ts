import { describe, expect, it } from 'vitest';
import {
  collectionCreateSchema,
  collectionReviewUpsertSchema,
  guideCreateSchema,
  guideReviewUpsertSchema,
  httpUrlSchema,
  modListItemSchema,
  modManifestSchema,
  modPatchSchema,
  safeHttpUrl,
} from '../index';

// Schemes that parse as a URL but must never reach an href/src on a page we
// serve. `z.string().url()` accepted every one of these.
const DANGEROUS = [
  'javascript:alert(document.cookie)',
  'JavaScript:alert(1)',
  '  javascript:alert(1)', // leading whitespace: new URL() trims it
  'data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==',
  'vbscript:msgbox(1)',
  'file:///etc/passwd',
  'blob:https://rsmm.me/1234',
];

const SAFE = ['https://github.com/Ovilli/x', 'http://example.com/a?b=c#d'];

describe('httpUrlSchema', () => {
  for (const url of DANGEROUS) {
    it(`rejects ${url.slice(0, 32)}`, () => {
      expect(httpUrlSchema.safeParse(url).success).toBe(false);
    });
  }

  for (const url of SAFE) {
    it(`accepts ${url}`, () => {
      expect(httpUrlSchema.safeParse(url).success).toBe(true);
    });
  }

  it('rejects a url past the length cap', () => {
    expect(httpUrlSchema.safeParse(`https://x.example/${'a'.repeat(4000)}`).success).toBe(false);
  });
});

describe('safeHttpUrl', () => {
  it('nulls every dangerous scheme', () => {
    for (const url of DANGEROUS) expect(safeHttpUrl(url)).toBeNull();
  });
  it('passes http(s) through unchanged', () => {
    for (const url of SAFE) expect(safeHttpUrl(url)).toBe(url);
  });
  it('nulls empty and nullish input', () => {
    expect(safeHttpUrl(null)).toBeNull();
    expect(safeHttpUrl(undefined)).toBeNull();
    expect(safeHttpUrl('')).toBeNull();
    expect(safeHttpUrl('not a url at all')).toBeNull();
  });
});

describe('input schemas refuse dangerous urls', () => {
  it('modPatchSchema rejects a javascript: repo url', () => {
    expect(modPatchSchema.safeParse({ repoUrl: 'javascript:alert(1)' }).success).toBe(false);
  });

  it('modPatchSchema rejects a javascript: video url', () => {
    expect(modPatchSchema.safeParse({ videos: ['javascript:alert(1)'] }).success).toBe(false);
  });

  it('modPatchSchema rejects a javascript: screenshot url', () => {
    expect(
      modPatchSchema.safeParse({ screenshots: [{ url: 'javascript:alert(1)' }] }).success,
    ).toBe(false);
  });

  it('guideCreateSchema rejects a javascript: image url', () => {
    const base = { slug: 'guide-a', title: 'T', body: 'B' };
    expect(guideCreateSchema.safeParse({ ...base, imageUrl: 'javascript:alert(1)' }).success).toBe(
      false,
    );
    expect(
      guideCreateSchema.safeParse({ ...base, imageUrl: 'https://cdn.rsmm.me/a.png' }).success,
    ).toBe(true);
  });

  it('collectionCreateSchema rejects a javascript: image url', () => {
    const base = { slug: 'coll-a', name: 'N' };
    expect(
      collectionCreateSchema.safeParse({ ...base, imageUrl: 'javascript:alert(1)' }).success,
    ).toBe(false);
  });
});

describe('response schemas sanitize rather than reject', () => {
  // A stored row holding a dangerous URL must not fail the parse of the list it
  // sits in — that would turn one XSS payload into a site-wide outage. The bad
  // field is dropped and everything else survives.
  const row = {
    id: '11111111-1111-4111-8111-111111111111',
    slug: 'a-mod',
    name: 'A Mod',
    author: null,
    summary: null,
    license: null,
    latestVersion: null,
    downloads: 0,
    updatedAt: '2026-01-01T00:00:00.000Z',
    category: null,
    rating: null,
    tags: [],
  };

  it('nulls a dangerous imageUrl instead of failing', () => {
    const parsed = modListItemSchema.safeParse({ ...row, imageUrl: 'javascript:alert(1)' });
    expect(parsed.success).toBe(true);
    if (parsed.success) expect(parsed.data.imageUrl).toBeNull();
  });

  it('keeps a legitimate imageUrl', () => {
    const parsed = modListItemSchema.safeParse({ ...row, imageUrl: 'https://cdn.rsmm.me/a.png' });
    expect(parsed.success).toBe(true);
    if (parsed.success) expect(parsed.data.imageUrl).toBe('https://cdn.rsmm.me/a.png');
  });

  it('drops only the dangerous entries from videos and screenshots', () => {
    const parsed = modListItemSchema.safeParse({
      ...row,
      imageUrl: null,
      videos: ['javascript:alert(1)', 'https://youtu.be/abc'],
      screenshots: [{ url: 'javascript:alert(1)' }, { url: 'https://cdn.rsmm.me/s.png' }],
    });
    expect(parsed.success).toBe(true);
    if (parsed.success) {
      expect(parsed.data.videos).toEqual(['https://youtu.be/abc']);
      expect(parsed.data.screenshots).toEqual([{ url: 'https://cdn.rsmm.me/s.png' }]);
    }
  });

  it('leaves absent optional fields absent', () => {
    const parsed = modListItemSchema.safeParse({ ...row, imageUrl: null });
    expect(parsed.success).toBe(true);
    if (parsed.success) {
      expect(parsed.data.videos).toBeUndefined();
      expect(parsed.data.screenshots).toBeUndefined();
      expect(parsed.data.repoUrl).toBeUndefined();
    }
  });

  it('modManifestSchema drops a dangerous repo_url without failing the parse', () => {
    const parsed = modManifestSchema.safeParse({
      id: 'a-mod',
      name: 'A Mod',
      version: '1.0.0',
      repo_url: 'javascript:alert(1)',
    });
    expect(parsed.success).toBe(true);
    if (parsed.success) expect(parsed.data.repo_url).toBeUndefined();
  });
});

describe('free-text fields are bounded', () => {
  const huge = 'x'.repeat(200_000);

  it('collectionCreateSchema caps description', () => {
    expect(
      collectionCreateSchema.safeParse({ slug: 'coll-a', name: 'N', description: huge }).success,
    ).toBe(false);
  });

  it('collectionReviewUpsertSchema caps body', () => {
    expect(collectionReviewUpsertSchema.safeParse({ rating: 5, body: huge }).success).toBe(false);
  });

  it('guideReviewUpsertSchema caps body', () => {
    expect(guideReviewUpsertSchema.safeParse({ rating: 5, body: huge }).success).toBe(false);
  });
});
