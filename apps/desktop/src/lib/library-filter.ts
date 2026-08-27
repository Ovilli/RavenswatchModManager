import { type activeProfile, isEnabledIn } from '../store';
import { getMissingDependencyCount } from './library-deps';
import type { Mod, ModCategory } from './mod-types';
import { compareVersions } from './version';

/**
 * The library screen's row building, filtering, sorting and grouping.
 *
 * Lifted out of `routes/index.tsx` for the same reason as `browse-filter`: it
 * is the part of the screen with rules to get wrong — which fields the search
 * box actually searches, what "outdated" means, whether a filtered-out mod can
 * still be counted — and it was unreachable from a test inside the component.
 */

type Profile = ReturnType<typeof activeProfile>;

export type LibraryStatusFilter = 'all' | 'enabled' | 'disabled' | 'outdated' | 'missingDeps';
export type LibrarySort = 'load-order' | 'name' | 'author' | 'version';

export interface LibraryRow {
  id: string;
  /** Position in the profile's load order — the default sort, and the drag key. */
  orderIdx: number;
  mod: Mod;
  enabled: boolean;
  outdated: boolean;
  missingDeps: number;
}

export interface LibraryFilter {
  query: string;
  category: ModCategory | 'all';
  status: LibraryStatusFilter;
  sort: LibrarySort;
}

/**
 * Build one row per entry in the profile's load order.
 *
 * The library is *profile-scoped*: a mod is in it iff this profile opted into
 * it. An id with no matching local mod is dropped rather than rendered as a
 * placeholder — that is a load-order entry whose folder is gone, and
 * `unadoptedMods` is what surfaces the opposite case.
 */
export function buildLibraryRows(profile: Profile, localMods: Record<string, Mod>): LibraryRow[] {
  const rows: LibraryRow[] = [];
  profile.loadOrder.forEach((id, orderIdx) => {
    const mod = localMods[id];
    if (!mod) return;
    rows.push({
      id,
      orderIdx,
      mod,
      enabled: isEnabledIn(profile, id),
      outdated: mod.version !== mod.latestVersion,
      missingDeps: getMissingDependencyCount(mod, profile),
    });
  });
  return rows;
}

function matchesQuery(row: LibraryRow, needle: string): boolean {
  const m = row.mod;
  return (
    m.name.toLowerCase().includes(needle) ||
    m.author.toLowerCase().includes(needle) ||
    m.summary.toLowerCase().includes(needle) ||
    m.slug.toLowerCase().includes(needle) ||
    m.version.toLowerCase().includes(needle) ||
    m.category.toLowerCase().includes(needle) ||
    m.tags.some((tag) => tag.toLowerCase().includes(needle))
  );
}

/** Apply the search box, the category chip and the status chip, then sort. Never mutates `rows`. */
export function filterLibraryRows(rows: LibraryRow[], f: LibraryFilter): LibraryRow[] {
  const needle = f.query.trim().toLowerCase();
  return rows
    .filter((row) => {
      if (f.category !== 'all' && row.mod.category !== f.category) return false;
      if (f.status === 'enabled' && !row.enabled) return false;
      if (f.status === 'disabled' && row.enabled) return false;
      if (f.status === 'outdated' && !row.outdated) return false;
      if (f.status === 'missingDeps' && row.missingDeps === 0) return false;
      return needle ? matchesQuery(row, needle) : true;
    })
    .sort((a, b) => {
      if (f.sort === 'name') return a.mod.name.localeCompare(b.mod.name);
      if (f.sort === 'author') return a.mod.author.localeCompare(b.mod.author);
      // Newest first, so an outdated mod is not buried under everything else.
      if (f.sort === 'version') return compareVersions(b.mod.version, a.mod.version);
      return a.orderIdx - b.orderIdx;
    });
}

/**
 * Group the visible rows by category for the grouped list view, keeping each
 * group in load order.
 */
export function groupByCategory(
  rows: LibraryRow[],
): [ModCategory, { id: string; orderIdx: number }[]][] {
  const groups = new Map<ModCategory, { id: string; orderIdx: number }[]>();
  for (const { id, orderIdx, mod } of rows) {
    const list = groups.get(mod.category) ?? [];
    list.push({ id, orderIdx });
    groups.set(mod.category, list);
  }
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
}

/** Rows with at least one unmet dependency, as `id → count`, for the row badges. */
export function missingDepCounts(rows: LibraryRow[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const row of rows) {
    if (row.missingDeps > 0) counts.set(row.id, row.missingDeps);
  }
  return counts;
}

/** How many mods each conflict implicates, as `id → count`, for the row badges. */
export function conflictCountByMod(conflicts: { modIds: string[] }[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const conflict of conflicts) {
    for (const modId of conflict.modIds) {
      counts.set(modId, (counts.get(modId) ?? 0) + 1);
    }
  }
  return counts;
}

/** Count of filters the "clear" affordance would reset. A sort is not a filter. */
export function countLibraryFilters(f: Omit<LibraryFilter, 'sort'>): number {
  return [f.category !== 'all', f.status !== 'all', f.query.trim().length > 0].filter(Boolean)
    .length;
}
