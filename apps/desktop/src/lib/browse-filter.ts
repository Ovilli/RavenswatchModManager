import type { Collection, ModListItem } from '@rsmm/schemas';

/**
 * The browse page's search, facet and sort rules.
 *
 * Lifted out of `routes/browse.tsx` because this is the part of that screen
 * with real behaviour to get wrong — AND-vs-OR tag semantics, whether facets
 * are counted before or after filtering, whether an unrated mod passes a
 * minimum rating — and none of it was reachable from a test while it lived
 * inside the component closure.
 */

export type BrowseSort = 'recent' | 'popular' | 'rating';

/** Tag chips offered as filters. More than this and the bar outgrows the page. */
export const TAG_FACET_LIMIT = 12;

export interface BrowseFacets {
  /** `[name, count]`, most-used first, then alphabetical. */
  categories: [string, number][];
  tags: [string, number][];
}

export interface ModFilter {
  q: string;
  sort: BrowseSort;
  showNsfw: boolean;
  category: string | null;
  tags: string[];
  minRating: number;
  hideInstalled: boolean;
  /** Slugs present on disk, used only by `hideInstalled`. */
  installed: string[];
}

function matches(needle: string, ...fields: (string | null | undefined)[]): boolean {
  return fields.some((f) => (f ?? '').toLowerCase().includes(needle));
}

/**
 * Category and tag counts for the filter bar.
 *
 * Derived from the fetched items rather than from the schema's category enum:
 * offering "speedrun" when no speedrun mod is published is a filter that can
 * only ever return nothing. Tags are ranked by how many mods carry them and
 * capped, because the tag vocabulary is free-form and unbounded.
 *
 * Counted BEFORE the category/tag filters are applied — otherwise picking one
 * facet would delete the others from the bar, and there would be no way back
 * without a reload. The NSFW gate is the one exception: a hidden mod must not
 * contribute a count either, or the bar advertises results the list cannot show.
 */
export function computeFacets(items: ModListItem[], showNsfw: boolean): BrowseFacets {
  const categories = new Map<string, number>();
  const tagCounts = new Map<string, number>();
  for (const m of items) {
    if (!showNsfw && m.nsfw) continue;
    if (m.category) categories.set(m.category, (categories.get(m.category) ?? 0) + 1);
    for (const t of m.tags) tagCounts.set(t, (tagCounts.get(t) ?? 0) + 1);
  }
  const rank = (a: [string, number], b: [string, number]) =>
    b[1] - a[1] || a[0].localeCompare(b[0]);
  return {
    categories: [...categories.entries()].sort(rank),
    tags: [...tagCounts.entries()].sort(rank).slice(0, TAG_FACET_LIMIT),
  };
}

/** Search, filter and sort the mod list. Never mutates `items`. */
export function filterMods(items: ModListItem[], f: ModFilter): ModListItem[] {
  const needle = f.q.trim().toLowerCase();
  const installed = new Set(f.installed);
  return (
    items
      .filter((m) => (needle ? matches(needle, m.name, m.summary, m.author) : true))
      .filter((m) => f.showNsfw || !m.nsfw)
      .filter((m) => (f.category ? m.category === f.category : true))
      // EVERY selected tag must be present, not any of them. Picking two tags to
      // widen a search is not what anyone means by it.
      .filter((m) => f.tags.every((t) => m.tags.includes(t)))
      // An unrated mod has no rating to compare, so it drops out as soon as a
      // minimum is set rather than counting as zero-and-therefore-bad.
      .filter((m) => (f.minRating > 0 ? (m.rating ?? 0) >= f.minRating : true))
      .filter((m) => (f.hideInstalled ? !installed.has(m.slug) : true))
      .sort((a, b) => {
        if (f.sort === 'popular') return (b.downloads ?? 0) - (a.downloads ?? 0);
        if (f.sort === 'rating') return (b.rating ?? 0) - (a.rating ?? 0);
        return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime();
      })
  );
}

/** Collections carry no facets — only the free-text search applies. */
export function filterCollections(items: Collection[], q: string): Collection[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return items;
  return items.filter((c) => matches(needle, c.name, c.summary));
}

/** Count of filters the "clear" affordance would reset. */
export function countActiveFilters(
  f: Pick<ModFilter, 'category' | 'tags' | 'minRating' | 'hideInstalled'>,
): number {
  return (
    (f.category ? 1 : 0) + f.tags.length + (f.minRating > 0 ? 1 : 0) + (f.hideInstalled ? 1 : 0)
  );
}
