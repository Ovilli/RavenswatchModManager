import type { Collection, ModListItem } from '@rsmm/schemas';
import { describe, expect, it } from 'vitest';
import {
  type ModFilter,
  TAG_FACET_LIMIT,
  computeFacets,
  countActiveFilters,
  filterCollections,
  filterMods,
} from './browse-filter';

function mod(over: Partial<ModListItem> & { slug: string }): ModListItem {
  return {
    name: over.slug,
    summary: null,
    author: null,
    category: null,
    tags: [],
    downloads: 0,
    rating: null,
    nsfw: false,
    updatedAt: '2026-01-01T00:00:00.000Z',
    ...over,
  } as ModListItem;
}

const BASE: ModFilter = {
  q: '',
  sort: 'recent',
  showNsfw: true,
  category: null,
  tags: [],
  minRating: 0,
  hideInstalled: false,
  installed: [],
};

const slugs = (list: ModListItem[]) => list.map((m) => m.slug);

describe('filterMods search', () => {
  const items = [
    mod({ slug: 'a', name: 'Damage Meter' }),
    mod({ slug: 'b', name: 'Quiet HUD', summary: 'Shows damage numbers' }),
    mod({ slug: 'c', name: 'Skins', author: 'DamageDev' }),
    mod({ slug: 'd', name: 'Unrelated' }),
  ];

  it('matches name, summary and author, case-insensitively', () => {
    expect(slugs(filterMods(items, { ...BASE, q: 'damage' }))).toEqual(['a', 'b', 'c']);
  });

  it('ignores surrounding whitespace and an empty query', () => {
    expect(slugs(filterMods(items, { ...BASE, q: '   ' }))).toEqual(['a', 'b', 'c', 'd']);
    expect(slugs(filterMods(items, { ...BASE, q: '  meter  ' }))).toEqual(['a']);
  });

  it('tolerates a null summary and author', () => {
    expect(slugs(filterMods([mod({ slug: 'x' })], { ...BASE, q: 'anything' }))).toEqual([]);
  });
});

describe('filterMods filters', () => {
  const items = [
    mod({ slug: 'ui-a', category: 'qol', tags: ['hud', 'perf'], rating: 5 }),
    mod({ slug: 'ui-b', category: 'qol', tags: ['hud'], rating: 3 }),
    mod({ slug: 'gp', category: 'gameplay', tags: ['perf'], rating: null }),
    mod({ slug: 'spicy', nsfw: true, tags: ['hud', 'perf'], rating: 5 }),
  ];

  it('requires EVERY selected tag, not any of them', () => {
    expect(slugs(filterMods(items, { ...BASE, tags: ['hud'] }))).toEqual(['ui-a', 'ui-b', 'spicy']);
    // Two tags must narrow, never widen.
    expect(slugs(filterMods(items, { ...BASE, tags: ['hud', 'perf'] }))).toEqual(['ui-a', 'spicy']);
  });

  it('filters by category', () => {
    expect(slugs(filterMods(items, { ...BASE, category: 'qol' }))).toEqual(['ui-a', 'ui-b']);
  });

  it('drops unrated mods once a minimum rating is set', () => {
    expect(slugs(filterMods(items, { ...BASE, minRating: 4 }))).toEqual(['ui-a', 'spicy']);
    // …but a minimum of 0 means "no filter", so they come back.
    expect(filterMods(items, { ...BASE, minRating: 0 })).toHaveLength(4);
  });

  it('hides nsfw mods unless they are asked for', () => {
    expect(slugs(filterMods(items, { ...BASE, showNsfw: false }))).toEqual(['ui-a', 'ui-b', 'gp']);
  });

  it('hides installed mods only when asked', () => {
    const f = { ...BASE, installed: ['ui-a', 'gp'] };
    expect(filterMods(items, f)).toHaveLength(4);
    expect(slugs(filterMods(items, { ...f, hideInstalled: true }))).toEqual(['ui-b', 'spicy']);
  });

  it('combines every filter with AND', () => {
    expect(
      slugs(
        filterMods(items, {
          ...BASE,
          showNsfw: false,
          category: 'qol',
          tags: ['hud'],
          minRating: 4,
        }),
      ),
    ).toEqual(['ui-a']);
  });
});

describe('filterMods sorting', () => {
  const items = [
    mod({ slug: 'old', downloads: 900, rating: 2, updatedAt: '2025-01-01T00:00:00.000Z' }),
    mod({ slug: 'mid', downloads: 100, rating: 5, updatedAt: '2026-06-01T00:00:00.000Z' }),
    mod({ slug: 'new', downloads: 500, rating: null, updatedAt: '2026-08-01T00:00:00.000Z' }),
  ];

  it('sorts by downloads, rating or recency', () => {
    expect(slugs(filterMods(items, { ...BASE, sort: 'popular' }))).toEqual(['old', 'new', 'mid']);
    expect(slugs(filterMods(items, { ...BASE, sort: 'rating' }))).toEqual(['mid', 'old', 'new']);
    expect(slugs(filterMods(items, { ...BASE, sort: 'recent' }))).toEqual(['new', 'mid', 'old']);
  });

  it('never mutates the caller’s array', () => {
    // `modData.items` is react-query's cache object; sorting it in place would
    // reorder every other consumer of the same query.
    const input = [...items];
    filterMods(input, { ...BASE, sort: 'popular' });
    expect(slugs(input)).toEqual(['old', 'mid', 'new']);
  });
});

describe('computeFacets', () => {
  const items = [
    mod({ slug: 'a', category: 'qol', tags: ['hud', 'perf'] }),
    mod({ slug: 'b', category: 'qol', tags: ['hud'] }),
    mod({ slug: 'c', category: 'gameplay', tags: ['perf'] }),
    mod({ slug: 'd', tags: [] }),
  ];

  it('counts categories and tags, most-used first then alphabetical', () => {
    const f = computeFacets(items, true);
    expect(f.categories).toEqual([
      ['qol', 2],
      ['gameplay', 1],
    ]);
    expect(f.tags).toEqual([
      ['hud', 2],
      ['perf', 2],
    ]);
  });

  it('leaves a mod with no category out of the category facets entirely', () => {
    expect(computeFacets([mod({ slug: 'd' })], true).categories).toEqual([]);
  });

  it('excludes nsfw mods from the counts when they are hidden', () => {
    const withSpicy = [...items, mod({ slug: 'x', category: 'qol', tags: ['hud'], nsfw: true })];
    // Advertising "qol (3)" while the list can only ever show 2 is a lie the
    // user has no way to resolve.
    expect(computeFacets(withSpicy, false).categories).toEqual([
      ['qol', 2],
      ['gameplay', 1],
    ]);
    expect(computeFacets(withSpicy, true).categories[0]).toEqual(['qol', 3]);
  });

  it('caps the tag list so the filter bar cannot outgrow the page', () => {
    const many = Array.from({ length: TAG_FACET_LIMIT + 8 }, (_, i) =>
      mod({ slug: `m${i}`, tags: [`t${String(i).padStart(2, '0')}`] }),
    );
    expect(computeFacets(many, true).tags).toHaveLength(TAG_FACET_LIMIT);
  });

  it('handles an empty page', () => {
    expect(computeFacets([], true)).toEqual({ categories: [], tags: [] });
  });
});

describe('filterCollections', () => {
  const items = [
    { slug: 'a', name: 'Speedrun Pack', summary: null },
    { slug: 'b', name: 'Cosmetics', summary: 'A speedrun-friendly set' },
    { slug: 'c', name: 'Other', summary: null },
  ] as unknown as Collection[];

  it('searches name and summary', () => {
    expect(filterCollections(items, 'SPEEDRUN').map((c) => c.slug)).toEqual(['a', 'b']);
  });

  it('returns the input untouched for an empty query', () => {
    expect(filterCollections(items, '  ')).toBe(items);
  });
});

describe('countActiveFilters', () => {
  it('counts each tag separately and ignores a zero rating', () => {
    expect(
      countActiveFilters({ category: null, tags: [], minRating: 0, hideInstalled: false }),
    ).toBe(0);
    expect(
      countActiveFilters({
        category: 'qol',
        tags: ['hud', 'perf'],
        minRating: 4,
        hideInstalled: true,
      }),
    ).toBe(5);
  });
});
