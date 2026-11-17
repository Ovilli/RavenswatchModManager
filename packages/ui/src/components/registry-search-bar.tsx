'use client';

import { Search, SlidersHorizontal, X } from 'lucide-react';
import { useRef } from 'react';

export function RegistrySearchBar({
  query,
  onQueryChange,
  onSubmit,
  placeholder = 'Search mods, authors, and more',
  searchLabel = 'Search mods',
  activeFilters = 0,
  filtersOpen = false,
  onOpenFilters,
}: {
  query: string;
  onQueryChange: (query: string) => void;
  onSubmit?: () => void;
  placeholder?: string;
  searchLabel?: string;
  activeFilters?: number;
  filtersOpen?: boolean;
  onOpenFilters?: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <search className="registry-search-slot">
      <form className="registry-search" onSubmit={(event) => { event.preventDefault(); onSubmit?.(); }}>
        <button className="registry-search-submit" type="submit" aria-label={searchLabel}>
          <Search size={20} aria-hidden />
        </button>
        <input
          ref={input}
          type="search"
          aria-label={searchLabel}
          placeholder={placeholder}
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
        />
        {query ? (
          <button
            className="registry-search-clear"
            type="button"
            aria-label="Clear search"
            onClick={() => { onQueryChange(''); input.current?.focus(); }}
          >
            <X size={16} aria-hidden />
          </button>
        ) : null}
        {onOpenFilters ? (
          <button
            className="registry-search-filters"
            type="button"
            aria-haspopup="dialog"
            aria-expanded={filtersOpen}
            aria-label={activeFilters ? `Filters, ${activeFilters} active` : 'Filters'}
            data-active={activeFilters > 0}
            onClick={onOpenFilters}
          >
            <SlidersHorizontal size={16} aria-hidden />
            Filters
            {activeFilters ? (
              <span className="registry-search-filter-count" aria-hidden>
                {activeFilters}
              </span>
            ) : null}
          </button>
        ) : null}
      </form>
    </search>
  );
}
