'use client';

import { Search, SlidersHorizontal, X } from 'lucide-react';
import { useSearchParams } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { registrySearchHref } from '../../lib/registry-query';
import './registry-search.css';

export function RegistrySearch({
  activeFilters,
  filtersOpen,
  onOpenFilters,
}: {
  activeFilters: number;
  filtersOpen: boolean;
  onOpenFilters: () => void;
}) {
  const params = useSearchParams();
  const appliedQuery = params.get('q') ?? '';
  const [query, setQuery] = useState(appliedQuery);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => setQuery(appliedQuery), [appliedQuery]);
  useEffect(() => {
    if (query.trim() === appliedQuery) return;
    const timer = setTimeout(() => {
      window.history.replaceState(null, '', registrySearchHref(window.location.search, query));
    }, 300);
    return () => clearTimeout(timer);
  }, [query, appliedQuery]);

  return (
    <search className="registry-search-slot">
      <form
        className="registry-search"
        onSubmit={(event) => {
          event.preventDefault();
          window.history.replaceState(null, '', registrySearchHref(window.location.search, query));
        }}
      >
        <button className="registry-search-submit" type="submit" aria-label="Search">
          <Search size={20} aria-hidden />
        </button>
        <input
          ref={input}
          type="search"
          aria-label="Search mods"
          placeholder="Search mods, authors, and more"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        {query ? (
          <button
            className="registry-search-clear"
            type="button"
            aria-label="Clear search"
            onClick={() => {
              setQuery('');
              input.current?.focus();
            }}
          >
            <X size={16} aria-hidden />
          </button>
        ) : null}
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
      </form>
    </search>
  );
}

export function RegistrySearchFallback() {
  return (
    <div className="registry-search-slot" aria-hidden>
      <div className="registry-search" />
    </div>
  );
}
