import { describe, expect, it } from 'vitest';
import type { Profile } from '../store';
import {
  type LibraryFilter,
  buildLibraryRows,
  conflictCountByMod,
  countLibraryFilters,
  filterLibraryRows,
  groupByCategory,
  missingDepCounts,
} from './library-filter';
import type { Mod } from './mod-types';

function mod(over: Partial<Mod> & { id: string }): Mod {
  return {
    slug: over.id,
    name: over.id,
    author: 'someone',
    version: '1.0.0',
    latestVersion: '1.0.0',
    category: 'gameplay',
    summary: '',
    description: '',
    changelog: '',
    rating: 0,
    downloads: 0,
    sizeKb: 0,
    tags: [],
    dependencies: [],
    writes: [],
    gameBuild: '',
    markdown: '',
    ...over,
  };
}

function profile(loadOrder: string[], disabled: string[] = []): Profile {
  return {
    id: 'p',
    name: 'Test',
    loadOrder,
    disabled: new Set(disabled),
    createdAt: '2026-01-01T00:00:00.000Z',
  };
}

function index(mods: Mod[]): Record<string, Mod> {
  return Object.fromEntries(mods.map((m) => [m.id, m]));
}

const ALL: LibraryFilter = { query: '', category: 'all', status: 'all', sort: 'load-order' };
const ids = (rows: { id: string }[]) => rows.map((r) => r.id);

describe('buildLibraryRows', () => {
  const mods = index([
    mod({ id: 'a', latestVersion: '2.0.0', dependencies: ['b', 'ghost'] }),
    mod({ id: 'b' }),
  ]);

  it('follows the profile load order, not the index order', () => {
    expect(ids(buildLibraryRows(profile(['b', 'a']), mods))).toEqual(['b', 'a']);
    expect(buildLibraryRows(profile(['b', 'a']), mods).map((r) => r.orderIdx)).toEqual([0, 1]);
  });

  it('drops a load-order entry whose mod is not on disk', () => {
    // A folder deleted outside the app. Rendering a placeholder row for it
    // would offer controls that act on nothing.
    expect(ids(buildLibraryRows(profile(['a', 'gone', 'b']), mods))).toEqual(['a', 'b']);
  });

  it('derives enabled, outdated and missing-dep counts', () => {
    const [a, b] = buildLibraryRows(profile(['a', 'b'], ['b']), mods);
    expect(a).toMatchObject({ enabled: true, outdated: true, missingDeps: 1 });
    expect(b).toMatchObject({ enabled: false, outdated: false, missingDeps: 0 });
  });

  it('only counts a dependency as missing when it is absent from the load order', () => {
    // "Present but disabled" is a different problem with a different fix, and
    // conflating them made the badge point at the wrong remedy.
    const rows = buildLibraryRows(profile(['a', 'b'], ['b']), mods);
    expect(rows[0]?.missingDeps).toBe(1); // only `ghost`
  });
});

describe('filterLibraryRows', () => {
  const mods = index([
    mod({
      id: 'a',
      name: 'Damage Meter',
      author: 'Ovilli',
      category: 'utility',
      tags: ['hud'],
      latestVersion: '2.0.0',
      version: '1.0.0',
    }),
    mod({
      id: 'b',
      name: 'Quiet HUD',
      category: 'qol',
      summary: 'less noise',
      version: '3.1.0',
      latestVersion: '3.1.0',
    }),
    mod({
      id: 'c',
      name: 'Skins',
      category: 'cosmetic',
      dependencies: ['ghost'],
      version: '2.0.0',
      latestVersion: '2.0.0',
    }),
  ]);
  const rows = buildLibraryRows(profile(['a', 'b', 'c'], ['b']), mods);

  it('searches name, author, summary, slug, version, category and tags', () => {
    expect(ids(filterLibraryRows(rows, { ...ALL, query: 'ovilli' }))).toEqual(['a']);
    expect(ids(filterLibraryRows(rows, { ...ALL, query: 'less noise' }))).toEqual(['b']);
    expect(ids(filterLibraryRows(rows, { ...ALL, query: 'hud' }))).toEqual(['a', 'b']);
    expect(ids(filterLibraryRows(rows, { ...ALL, query: 'cosmetic' }))).toEqual(['c']);
    expect(ids(filterLibraryRows(rows, { ...ALL, query: '3.1' }))).toEqual(['b']);
    expect(ids(filterLibraryRows(rows, { ...ALL, query: '  ' }))).toEqual(['a', 'b', 'c']);
  });

  it('filters by category', () => {
    expect(ids(filterLibraryRows(rows, { ...ALL, category: 'qol' }))).toEqual(['b']);
  });

  it('filters by each status', () => {
    expect(ids(filterLibraryRows(rows, { ...ALL, status: 'enabled' }))).toEqual(['a', 'c']);
    expect(ids(filterLibraryRows(rows, { ...ALL, status: 'disabled' }))).toEqual(['b']);
    expect(ids(filterLibraryRows(rows, { ...ALL, status: 'outdated' }))).toEqual(['a']);
    expect(ids(filterLibraryRows(rows, { ...ALL, status: 'missingDeps' }))).toEqual(['c']);
  });

  it('reads any version mismatch as outdated, in either direction', () => {
    // `outdated` is `version !== latestVersion`, so a local build AHEAD of the
    // index is flagged too. That is the shipped behaviour; pinned here so a
    // change to it is a deliberate one rather than a silent regression.
    const ahead = index([mod({ id: 'x', version: '9.0.0', latestVersion: '1.0.0' })]);
    expect(buildLibraryRows(profile(['x']), ahead)[0]?.outdated).toBe(true);
  });

  it('ANDs the search with the chips', () => {
    expect(ids(filterLibraryRows(rows, { ...ALL, status: 'enabled', query: 'skins' }))).toEqual([
      'c',
    ]);
    expect(filterLibraryRows(rows, { ...ALL, status: 'disabled', query: 'skins' })).toEqual([]);
  });

  it('sorts by load order, name, author or version', () => {
    expect(ids(filterLibraryRows(rows, { ...ALL, sort: 'load-order' }))).toEqual(['a', 'b', 'c']);
    expect(ids(filterLibraryRows(rows, { ...ALL, sort: 'name' }))).toEqual(['a', 'b', 'c']);
    // Newest version first.
    expect(ids(filterLibraryRows(rows, { ...ALL, sort: 'version' }))).toEqual(['b', 'c', 'a']);
  });

  it('never mutates the rows it was handed', () => {
    const input = [...rows];
    filterLibraryRows(input, { ...ALL, sort: 'version' });
    expect(ids(input)).toEqual(['a', 'b', 'c']);
  });
});

describe('groupByCategory', () => {
  it('groups visible rows alphabetically by category, keeping load order inside', () => {
    const mods = index([
      mod({ id: 'a', category: 'utility' }),
      mod({ id: 'b', category: 'audio' }),
      mod({ id: 'c', category: 'utility' }),
    ]);
    const rows = buildLibraryRows(profile(['a', 'b', 'c']), mods);
    expect(groupByCategory(rows)).toEqual([
      ['audio', [{ id: 'b', orderIdx: 1 }]],
      [
        'utility',
        [
          { id: 'a', orderIdx: 0 },
          { id: 'c', orderIdx: 2 },
        ],
      ],
    ]);
  });

  it('produces no groups for an empty library', () => {
    expect(groupByCategory([])).toEqual([]);
  });
});

describe('badge counters', () => {
  it('maps only the rows with unmet dependencies', () => {
    const mods = index([mod({ id: 'a', dependencies: ['x', 'y'] }), mod({ id: 'b' })]);
    const rows = buildLibraryRows(profile(['a', 'b']), mods);
    expect([...missingDepCounts(rows)]).toEqual([['a', 2]]);
  });

  it('counts how many conflicts each mod takes part in', () => {
    const counts = conflictCountByMod([{ modIds: ['a', 'b'] }, { modIds: ['a', 'c'] }]);
    expect([...counts].sort()).toEqual([
      ['a', 2],
      ['b', 1],
      ['c', 1],
    ]);
  });

  it('returns an empty map rather than undefined for no conflicts', () => {
    expect(conflictCountByMod([]).size).toBe(0);
  });
});

describe('countLibraryFilters', () => {
  it('counts the chips and the search box, and treats whitespace as empty', () => {
    expect(countLibraryFilters({ query: '', category: 'all', status: 'all' })).toBe(0);
    expect(countLibraryFilters({ query: '   ', category: 'all', status: 'all' })).toBe(0);
    expect(countLibraryFilters({ query: 'hud', category: 'qol', status: 'enabled' })).toBe(3);
  });
});
