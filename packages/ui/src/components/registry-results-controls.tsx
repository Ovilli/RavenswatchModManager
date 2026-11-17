'use client';

import { ChevronDown, LayoutGrid, Rows3 } from 'lucide-react';

export type RegistrySortValue = 'popular' | 'recent' | 'rating';
export type RegistryViewValue = 'grid' | 'list';

export function RegistryResultsControls({
  sort,
  view,
  onSortChange,
  onViewChange,
  labels = {},
}: {
  sort: RegistrySortValue;
  view: RegistryViewValue;
  onSortChange: (sort: RegistrySortValue) => void;
  onViewChange: (view: RegistryViewValue) => void;
  labels?: {
    sortBy?: string;
    sort?: string;
    popular?: string;
    recent?: string;
    rating?: string;
    layout?: string;
    cards?: string;
    list?: string;
  };
}) {
  return (
    <div className="registry-result-controls">
      <label className="registry-sort">
        <span>{labels.sortBy ?? 'Sort by'}</span>
        <select
          aria-label={labels.sort ?? 'Sort mods'}
          value={sort}
          onChange={(event) => onSortChange(event.target.value as RegistrySortValue)}
        >
          <option value="popular">{labels.popular ?? 'Popular'}</option>
          <option value="recent">{labels.recent ?? 'Recent'}</option>
          <option value="rating">{labels.rating ?? 'Top rated'}</option>
        </select>
        <ChevronDown size={14} aria-hidden />
      </label>
      <fieldset className="registry-view-switch">
        <legend className="sr-only">{labels.layout ?? 'Layout'}</legend>
        <button
          type="button"
          className="registry-icon-button"
          aria-label={labels.cards ?? 'Cards'}
          aria-pressed={view === 'grid'}
          onClick={() => onViewChange('grid')}
        >
          <LayoutGrid size={18} aria-hidden />
        </button>
        <button
          type="button"
          className="registry-icon-button"
          aria-label={labels.list ?? 'List'}
          aria-pressed={view === 'list'}
          onClick={() => onViewChange('list')}
        >
          <Rows3 size={18} aria-hidden />
        </button>
      </fieldset>
    </div>
  );
}
