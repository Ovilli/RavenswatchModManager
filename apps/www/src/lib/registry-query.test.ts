import { describe, expect, it } from 'vitest';
import {
  EMPTY_REGISTRY_FILTERS,
  readRegistryQuery,
  registryFilterCount,
  registryFilterHref,
  registrySearchHref,
} from './registry-query';

describe('registry browse URLs', () => {
  it('restores shared searches, sorting, filters, and pagination', () => {
    expect(
      readRegistryQuery(
        'q=scarlet&category=cosmetic&tags=hero,skin,hero&rating=4.5&sort=recent&featured=1&nsfw=1&page=3',
      ),
    ).toEqual({
      query: 'scarlet',
      sort: 'recent',
      page: 3,
      filters: {
        category: 'cosmetic',
        tags: ['hero', 'skin'],
        minRating: 4.5,
        featuredOnly: true,
        showNsfw: true,
      },
    });
  });
  it('rejects malformed filters and non-integer pagination without opting into mature content', () => {
    for (const page of ['-1', '2.5', 'NaN', 'Infinity']) {
      expect(
        readRegistryQuery(`category=unknown&rating=99&sort=unknown&nsfw=true&page=${page}`),
      ).toEqual({ query: '', filters: EMPTY_REGISTRY_FILTERS, page: 1, sort: 'popular' });
    }
  });
  it('applies modal filters together, preserving search and sort while returning to page one', () => {
    const href = registryFilterHref('q=carmilla&sort=rating&page=3', {
      ...EMPTY_REGISTRY_FILTERS,
      category: 'cosmetic',
      tags: ['hero', 'skin'],
      minRating: 4,
      featuredOnly: true,
    });
    expect(readRegistryQuery(href.split('?')[1] ?? '')).toEqual({
      query: 'carmilla',
      sort: 'rating',
      page: 1,
      filters: {
        ...EMPTY_REGISTRY_FILTERS,
        category: 'cosmetic',
        tags: ['hero', 'skin'],
        minRating: 4,
        featuredOnly: true,
      },
    });
  });
  it('clears filters without clearing the search or sort', () => {
    expect(
      registryFilterHref(
        'q=hero&sort=recent&category=cosmetic&tags=skin&rating=4&featured=1&nsfw=1&page=3',
        EMPTY_REGISTRY_FILTERS,
      ),
    ).toBe('/registry?q=hero&sort=recent');
  });
  it('keeps filters when searching, escapes punctuation, and resets pagination', () => {
    const href = registrySearchHref('category=cosmetic&tags=hero&page=4', '  scarlet & snow  ');
    const result = readRegistryQuery(href.split('?')[1] ?? '');
    expect(result.query).toBe('scarlet & snow');
    expect(result.page).toBe(1);
    expect(result.filters.category).toBe('cosmetic');
    expect(result.filters.tags).toEqual(['hero']);
    expect(registrySearchHref('q=hero&page=4', '')).toBe('/registry');
  });
  it('counts every active modal filter', () => {
    expect(
      registryFilterCount({
        category: 'cosmetic',
        tags: ['hero', 'skin'],
        minRating: 4,
        featuredOnly: true,
        showNsfw: true,
      }),
    ).toBe(6);
    expect(registryFilterCount(EMPTY_REGISTRY_FILTERS)).toBe(0);
  });
});
