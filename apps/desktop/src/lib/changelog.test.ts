import { describe, expect, it } from 'vitest';
import {
  BUNDLED_CHANGELOG,
  type ChangelogEntry,
  entriesSince,
  latestVersion,
  mergeEntries,
  pendingEntries,
} from './changelog';

/** Small fixed set, so these tests don't move every time a release ships. */
const ENTRIES: ChangelogEntry[] = [
  { version: '5.0.2', date: '2026-08-20', highlights: ['c'] },
  { version: '5.0.1', date: '2026-08-16', highlights: ['b'] },
  { version: '5.0.0', date: '2026-08-14', highlights: ['a'] },
];

describe('bundled changelog data', () => {
  it('is ordered newest-first', () => {
    // By DATE across the whole feed, because a loader-channel note has no app
    // version to sort by — it belongs to no release. The app entries among
    // them must still descend by version.
    const dates = BUNDLED_CHANGELOG.map((e) => e.date);
    expect(dates).toEqual([...dates].sort((a, b) => (a > b ? -1 : 1)));

    const versions = BUNDLED_CHANGELOG.filter((e) => e.version).map((e) => e.version);
    expect(versions).toEqual([...versions].sort((a, b) => (a > b ? -1 : 1)));
  });

  it('identifies every entry as either a release or a loader note', () => {
    for (const entry of BUNDLED_CHANGELOG) {
      expect(Boolean(entry.version) || typeof entry.loader_version === 'number').toBe(true);
    }
  });

  it('has a non-empty highlight list and an ISO date per entry', () => {
    for (const entry of BUNDLED_CHANGELOG) {
      expect(entry.highlights.length).toBeGreaterThan(0);
      expect(entry.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    }
  });

  it('reports the newest version', () => {
    expect(latestVersion(ENTRIES)).toBe('5.0.2');
  });
});

describe('mergeEntries', () => {
  it('lets a published note override the version shipped in this build', () => {
    const remote: ChangelogEntry[] = [
      { version: '5.0.2', date: '2026-08-21', highlights: ['corrected'] },
    ];
    const merged = mergeEntries(remote, ENTRIES);
    expect(merged.find((e) => e.version === '5.0.2')?.highlights).toEqual(['corrected']);
    expect(merged).toHaveLength(3);
  });

  it('keeps a published note for a release this build predates', () => {
    const remote: ChangelogEntry[] = [
      { version: '5.1.0', date: '2026-08-25', highlights: ['loader-only fix'] },
    ];
    expect(mergeEntries(remote, ENTRIES).map((e) => e.version)).toEqual([
      '5.1.0',
      '5.0.2',
      '5.0.1',
      '5.0.0',
    ]);
  });

  it('keeps bundled entries the feed has dropped', () => {
    const remote: ChangelogEntry[] = [{ version: '5.0.2', date: '2026-08-20', highlights: ['c'] }];
    expect(mergeEntries(remote, ENTRIES)).toHaveLength(3);
  });

  it('sorts newest-first even when neither input is ordered', () => {
    const jumbled = [...ENTRIES].reverse();
    expect(mergeEntries([], jumbled).map((e) => e.version)).toEqual(['5.0.2', '5.0.1', '5.0.0']);
  });
});

describe('entriesSince', () => {
  it('returns only releases newer than the mark', () => {
    expect(entriesSince(ENTRIES, '5.0.0', '5.0.2').map((e) => e.version)).toEqual([
      '5.0.2',
      '5.0.1',
    ]);
  });

  it('returns nothing when the mark is current', () => {
    expect(entriesSince(ENTRIES, '5.0.2', '5.0.2')).toEqual([]);
  });

  it('returns nothing on a downgrade rather than replaying old notes', () => {
    expect(entriesSince(ENTRIES, '5.0.2', '5.0.0')).toEqual([]);
  });

  it('hides a published note for a release newer than the running build', () => {
    const withFuture = mergeEntries(
      [{ version: '5.1.0', date: '2026-08-25', highlights: ['not shipped to you yet'] }],
      ENTRIES,
    );
    expect(entriesSince(withFuture, '5.0.1', '5.0.2').map((e) => e.version)).toEqual(['5.0.2']);
  });

  it('caps the list so a long gap stays readable', () => {
    expect(entriesSince(ENTRIES, '0.0.1', '5.0.2', 2)).toHaveLength(2);
  });
});

describe('pendingEntries', () => {
  it('shows nothing on a first-ever launch', () => {
    expect(
      pendingEntries({ entries: ENTRIES, seen: null, current: '5.0.2', hasRunBefore: false }),
    ).toEqual([]);
  });

  it('shows the current release to a returning user with no mark yet', () => {
    const got = pendingEntries({
      entries: ENTRIES,
      seen: null,
      current: '5.0.1',
      hasRunBefore: true,
    });
    expect(got.map((e) => e.version)).toEqual(['5.0.1']);
  });

  it('shows everything since the mark for a returning user', () => {
    const got = pendingEntries({
      entries: ENTRIES,
      seen: '5.0.0',
      current: '5.0.2',
      hasRunBefore: true,
    });
    expect(got.map((e) => e.version)).toEqual(['5.0.2', '5.0.1']);
  });
});

describe('loader-channel notes', () => {
  // The loader DLL and Lua SDK update out of band, so a fix reaches users with
  // no app release to announce it in. Those entries carry `loader_version` and
  // no app `version`, and clamp against the loader the user has PLANTED —
  // otherwise a note would describe a payload they have not received.
  const loaderNote = (v: number, date: string): ChangelogEntry => ({
    version: '',
    loader_version: v,
    date,
    highlights: [`loader v${v} landed`],
  });

  it('shows a loader note only up to the planted loader build', () => {
    const entries = [loaderNote(9, '2026-08-25'), loaderNote(8, '2026-08-24')];
    const shown = entriesSince(entries, '5.1.0', '5.1.0', 3, { current: 8, seen: 7 });
    expect(shown.map((e) => e.loader_version)).toEqual([8]);
  });

  it('does not repeat a loader note the user has already seen', () => {
    const entries = [loaderNote(8, '2026-08-24')];
    expect(entriesSince(entries, '5.1.0', '5.1.0', 3, { current: 8, seen: 8 })).toEqual([]);
  });

  it('hides loader notes from a caller that knows nothing about the loader', () => {
    // An older caller passing no loader context must not have notes announced
    // early; silence is the safe direction.
    const entries = [loaderNote(8, '2026-08-24')];
    expect(entriesSince(entries, '5.1.0', '5.1.0')).toEqual([]);
  });

  it('still shows app releases alongside', () => {
    const entries: ChangelogEntry[] = [
      loaderNote(8, '2026-08-24'),
      { version: '5.1.1', date: '2026-08-24', highlights: ['app'] },
    ];
    const shown = entriesSince(entries, '5.1.0', '5.1.1', 5, { current: 8, seen: 7 });
    expect(shown.map((e) => e.version || `loader${e.loader_version}`)).toEqual([
      'loader8',
      '5.1.1',
    ]);
  });

  it('merges loader notes without collapsing them onto each other', () => {
    // They all share the empty version string, so keying the union on
    // `version` alone kept exactly one of them.
    const merged = mergeEntries([loaderNote(9, '2026-08-25')], [loaderNote(8, '2026-08-24')]);
    expect(merged.map((e) => e.loader_version)).toEqual([9, 8]);
  });

  it('latestVersion ignores loader notes', () => {
    const entries: ChangelogEntry[] = [
      loaderNote(8, '2026-08-24'),
      { version: '5.1.0', date: '2026-08-22', highlights: ['app'] },
    ];
    expect(latestVersion(entries)).toBe('5.1.0');
  });

  it('does not open a first-run dialog with a loader note', () => {
    const entries: ChangelogEntry[] = [
      loaderNote(8, '2026-08-24'),
      { version: '5.1.0', date: '2026-08-22', highlights: ['app'] },
    ];
    const shown = pendingEntries({
      entries,
      seen: null,
      current: '5.1.0',
      hasRunBefore: true,
      loader: { current: 8, seen: 0 },
    });
    expect(shown.map((e) => e.version)).toEqual(['5.1.0']);
  });
});
