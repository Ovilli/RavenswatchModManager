'use client';

import { RegistrySearchBar } from '@rsmm/ui';
import { useSearchParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import { registrySearchHref } from '../../lib/registry-query';

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

  useEffect(() => setQuery(appliedQuery), [appliedQuery]);
  useEffect(() => {
    if (query.trim() === appliedQuery) return;
    const timer = setTimeout(() => {
      window.history.replaceState(null, '', registrySearchHref(window.location.search, query));
    }, 300);
    return () => clearTimeout(timer);
  }, [query, appliedQuery]);

  return (
    <RegistrySearchBar
      query={query}
      onSubmit={() => window.history.replaceState(null, '', registrySearchHref(window.location.search, query))}
      onQueryChange={(next) => {
        setQuery(next);
        if (!next.trim()) window.history.replaceState(null, '', registrySearchHref(window.location.search, ''));
      }}
      activeFilters={activeFilters}
      filtersOpen={filtersOpen}
      onOpenFilters={onOpenFilters}
    />
  );
}

export function RegistrySearchFallback() {
  return (
    <div className="registry-search-slot" aria-hidden>
      <div className="registry-search" />
    </div>
  );
}
