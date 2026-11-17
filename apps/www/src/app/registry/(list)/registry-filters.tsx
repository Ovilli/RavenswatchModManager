'use client';

import { isPrivateOnlyTag } from '@rsmm/schemas';
import { RegistryFilterDialog as SharedRegistryFilterDialog, type RegistryFilterValue } from '@rsmm/ui';
import {
  EMPTY_REGISTRY_FILTERS,
  REGISTRY_CATEGORIES,
  type RegistryFilters,
} from '../../../lib/registry-query';

export type RegistryFacet = { name: string; count: number };

export function RegistryFilterDialog({
  filters,
  categories,
  tags,
  onApply,
  onClose,
}: {
  filters: RegistryFilters;
  categories: RegistryFacet[];
  tags: RegistryFacet[];
  onApply: (filters: RegistryFilters) => void;
  onClose: () => void;
}) {
  const toShared = (value: RegistryFilters): RegistryFilterValue => ({
    category: value.category === 'all' ? '' : value.category,
    tags: value.tags,
    minRating: value.minRating,
    toggles: {
      hidePrivateOnly: value.hidePrivateOnly,
      featuredOnly: value.featuredOnly,
      showNsfw: value.showNsfw,
    },
  });
  const convert = (value: RegistryFilterValue): RegistryFilters => ({
    category: (value.category || 'all') as RegistryFilters['category'],
    tags: value.tags.filter((tag) => !isPrivateOnlyTag(tag)),
    minRating: value.minRating,
    hidePrivateOnly: value.toggles.hidePrivateOnly ?? filters.hidePrivateOnly,
    featuredOnly: value.toggles.featuredOnly ?? filters.featuredOnly,
    showNsfw: value.toggles.showNsfw ?? filters.showNsfw,
  });
  const tagOptions = [...new Set([...tags.map((tag) => tag.name), ...filters.tags])]
    .filter((tag) => !isPrivateOnlyTag(tag))
    .map((name) => ({ name, count: tags.find((tag) => tag.name === name)?.count }));

  return (
    <SharedRegistryFilterDialog
      value={toShared(filters)}
      categories={REGISTRY_CATEGORIES.filter(
        (category) =>
          !categories.length ||
          categories.some((facet) => facet.name === category.id) ||
          filters.category === category.id,
      ).map((category) => ({ value: category.id, label: category.label }))}
      tags={tagOptions.map(({ name, count }) => ({ value: name, label: name, count }))}
      ratings={[0, 3, 4, 4.5].map((rating) => ({
        value: rating,
        label: rating ? `${rating}+` : 'Any rating',
      }))}
      toggles={[
        { id: 'hidePrivateOnly', label: 'Hide private only mods', checked: filters.hidePrivateOnly },
        { id: 'featuredOnly', label: 'Featured mods only', checked: filters.featuredOnly },
        { id: 'showNsfw', label: 'Include mature content', checked: filters.showNsfw },
      ]}
      onApply={(next) => onApply(convert(next))}
      onClose={onClose}
      onClear={() => toShared(EMPTY_REGISTRY_FILTERS)}
    />
  );
}
