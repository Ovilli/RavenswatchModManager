import type { ModCategory } from '@rsmm/schemas';
import type { Route } from 'next';

export const REGISTRY_CATEGORIES: { id: ModCategory; label: string }[] = [
  { id: 'gameplay', label: 'Gameplay' },
  { id: 'balance', label: 'Balance' },
  { id: 'cosmetic', label: 'Cosmetics' },
  { id: 'qol', label: 'Quality of life' },
  { id: 'audio', label: 'Audio' },
  { id: 'difficulty', label: 'Difficulty' },
  { id: 'speedrun', label: 'Speedrunning' },
  { id: 'utility', label: 'Utilities' },
];

export const REGISTRY_RATINGS = [0, 3, 4, 4.5];
export type RegistrySort = 'popular' | 'recent' | 'rating';
export type RegistryFilters = {
  category: ModCategory | 'all';
  tags: string[];
  minRating: number;
  featuredOnly: boolean;
  showNsfw: boolean;
};

export const EMPTY_REGISTRY_FILTERS: RegistryFilters = {
  category: 'all',
  tags: [],
  minRating: 0,
  featuredOnly: false,
  showNsfw: false,
};

export function readRegistryQuery(query: string) {
  const params = new URLSearchParams(query);
  const category = REGISTRY_CATEGORIES.find(({ id }) => id === params.get('category'));
  const rating = Number(params.get('rating'));
  const sort = params.get('sort');
  const page = Number(params.get('page'));
  const filters: RegistryFilters = {
    category: category?.id ?? 'all',
    tags: [
      ...new Set(
        (params.get('tags') ?? '')
          .split(',')
          .map((tag) => tag.trim())
          .filter(Boolean),
      ),
    ],
    minRating: REGISTRY_RATINGS.includes(rating) ? rating : 0,
    featuredOnly: params.get('featured') === '1',
    showNsfw: params.get('nsfw') === '1',
  };
  return {
    query: params.get('q') ?? '',
    filters,
    sort: (sort === 'recent' || sort === 'rating' ? sort : 'popular') as RegistrySort,
    page: Number.isSafeInteger(page) && page > 0 ? page : 1,
  };
}

export function registryHref(params: URLSearchParams): Route {
  const query = params.toString();
  return (query ? `/registry?${query}` : '/registry') as Route;
}

export function registryFilterHref(query: string, filters: RegistryFilters): Route {
  const params = new URLSearchParams(query);
  for (const key of ['category', 'tags', 'rating', 'featured', 'nsfw', 'page']) params.delete(key);
  if (filters.category !== 'all') params.set('category', filters.category);
  if (filters.tags.length) params.set('tags', filters.tags.join(','));
  if (filters.minRating > 0) params.set('rating', String(filters.minRating));
  if (filters.featuredOnly) params.set('featured', '1');
  if (filters.showNsfw) params.set('nsfw', '1');
  return registryHref(params);
}

export function registrySearchHref(query: string, value: string): Route {
  const params = new URLSearchParams(query);
  params.delete('page');
  if (value.trim()) params.set('q', value.trim());
  else params.delete('q');
  return registryHref(params);
}

export function registryFilterCount(filters: RegistryFilters): number {
  return (
    Number(filters.category !== 'all') +
    filters.tags.length +
    Number(filters.minRating > 0) +
    Number(filters.featuredOnly) +
    Number(filters.showNsfw)
  );
}
