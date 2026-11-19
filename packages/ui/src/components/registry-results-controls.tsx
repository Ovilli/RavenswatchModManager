'use client';

import { ChevronDown, LayoutGrid, Rows3 } from 'lucide-react';

export type RegistrySortValue = 'popular' | 'recent' | 'rating';
export type RegistryViewValue = 'grid' | 'list';

/** The registry's sort treatment, with options supplied by the listing. */
export function RegistrySortControl<Sort extends string>({
  value,
  options,
  onChange,
  label = 'Sort by',
  ariaLabel = 'Sort mods',
}: {
  value: Sort;
  options: { value: Sort; label: string }[];
  onChange: (value: Sort) => void;
  label?: string;
  ariaLabel?: string;
}) {
  return (
    <label className="registry-sort">
      <span>{label}</span>
      <select
        aria-label={ariaLabel}
        value={value}
        onChange={(event) => onChange(event.target.value as Sort)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <ChevronDown size={14} aria-hidden />
    </label>
  );
}

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
      <RegistrySortControl
        value={sort}
        onChange={onSortChange}
        label={labels.sortBy}
        ariaLabel={labels.sort}
        options={[
          { value: 'popular', label: labels.popular ?? 'Popular' },
          { value: 'recent', label: labels.recent ?? 'Recent' },
          { value: 'rating', label: labels.rating ?? 'Top rated' },
        ]}
      />
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
