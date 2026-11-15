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
        'q=scarlet&category=cosmetic&tags=hero,skin,hero&rating=4.5&sort=recent&featured=1&nsfw=1&hidePrivateOnly=1&page=3',
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
        hidePrivateOnly: true,
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
      hidePrivateOnly: true,
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
        hidePrivateOnly: true,
      },
    });
  });
  it('clears filters without clearing the search or sort', () => {
    expect(
      registryFilterHref(
        'q=hero&sort=recent&category=cosmetic&tags=skin&rating=4&featured=1&nsfw=1&hidePrivateOnly=1&page=3',
        EMPTY_REGISTRY_FILTERS,
      ),
    ).toBe('/registry?q=hero&sort=recent');
  });
  it('keeps filters when searching, escapes punctuation, and resets pagination', () => {
    const href = registrySearchHref(
      'category=cosmetic&tags=hero&hidePrivateOnly=1&page=4',
      '  scarlet & snow  ',
    );
    const result = readRegistryQuery(href.split('?')[1] ?? '');
    expect(result.query).toBe('scarlet & snow');
    expect(result.page).toBe(1);
    expect(result.filters.category).toBe('cosmetic');
    expect(result.filters.tags).toEqual(['hero']);
    expect(result.filters.hidePrivateOnly).toBe(true);
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
        hidePrivateOnly: true,
      }),
    ).toBe(7);
    expect(registryFilterCount(EMPTY_REGISTRY_FILTERS)).toBe(0);
  });
  it('drops retired private-only tag choices without reversing the old filter intent', () => {
    const query = 'tags=hero,private-only,Private%20games%20only,%20CHEATS%20';
    expect(readRegistryQuery(query).filters).toEqual({
      ...EMPTY_REGISTRY_FILTERS,
      tags: ['hero'],
    });
    const href = registryFilterHref(query, {
      ...EMPTY_REGISTRY_FILTERS,
      tags: ['hero', 'private-only', 'Private only', ' CHEAT '],
      hidePrivateOnly: true,
    });
    expect(href).toBe('/registry?tags=hero&hidePrivateOnly=1');
    expect(registryFilterCount(readRegistryQuery(href.split('?')[1] ?? '').filters)).toBe(2);
  });
});
