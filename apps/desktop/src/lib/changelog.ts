import feed from '../../../../data/changelog.json';
import { fetchChangelog } from './rsmm';
import { compareVersions } from './version';

/**
 * Release notes for the "What's new" dialog.
 *
 * The entries themselves are NOT compiled in as a literal. They come from
 * `data/changelog.json` at the repo root, which is the single source shared by
 * three consumers: this bundle (the offline fallback), the PyInstaller sidecar
 * (`rsmm changelog` when the network is down), and
 * `scripts/publish_changelog.sh`, which uploads that exact file to the rolling
 * `changelog` GitHub release.
 *
 * That last one is the point. Notes compiled into the app can only reach a user
 * by shipping a whole new build — which is backwards, because the loader DLL and
 * Lua SDK already update out of band and so have no release to announce
 * themselves in. `fetchRemoteEntries()` reads the published feed, so a note can
 * go out on its own.
 */
export interface ChangelogEntry {
  /**
   * Release version, matching the tag without the leading `v`.
   *
   * Empty on a LOADER-CHANNEL note, which belongs to no app release: the
   * loader DLL and Lua SDK update out of band, so a fix can reach every user
   * with no build to announce it in. Those entries carry `loader_version`
   * instead and are shown against the loader the user has planted.
   */
  version: string;
  /**
   * Loader-channel build this entry describes, when it describes one.
   *
   * snake_case because that is the wire shape — the bundled feed is imported
   * straight from data/changelog.json and the CLI emits the same keys, so a
   * camelCase field here would simply read undefined at runtime with nothing
   * to catch it.
   */
  loader_version?: number;
  /** ISO date (YYYY-MM-DD) of the release. */
  date: string;
  /** Optional one-line framing for the release as a whole. */
  summary?: string;
  highlights: string[];
}

/** The copy shipped inside this build. Used when the channel is unreachable. */
export const BUNDLED_CHANGELOG: ChangelogEntry[] = feed.entries;

/** Newest APP release described by a set of entries (loader notes are skipped:
 *  they belong to no release and would otherwise report an empty version). */
export function latestVersion(entries: ChangelogEntry[] = BUNDLED_CHANGELOG): string {
  return entries.find((e) => e.version)?.version ?? '0.0.0';
}

/** Is this a loader-channel note rather than an app release? */
export function isLoaderEntry(e: ChangelogEntry): boolean {
  return !e.version && typeof e.loader_version === 'number';
}

/**
 * Fold the published feed over the copy shipped in this build.
 *
 * Neither list alone is right. The feed can be ahead (a note published after
 * this build shipped) and it can also be *behind* (a user updates the app
 * before anyone re-publishes the feed), so taking either one wholesale loses
 * entries. Union by version, with the remote winning any version both describe
 * — the remote copy is the one that can be corrected after the fact.
 *
 * Sorted newest-first on the way out, because neither input is trusted to be.
 */
export function mergeEntries(
  remote: ChangelogEntry[],
  bundled: ChangelogEntry[] = BUNDLED_CHANGELOG,
): ChangelogEntry[] {
  // Key on what IDENTIFIES the entry. Keying on `version` alone collapsed every
  // loader note onto one another, because they all share the empty string.
  const key = (e: ChangelogEntry) => (e.version ? `app:${e.version}` : `loader:${e.loader_version}`);
  const byKey = new Map<string, ChangelogEntry>();
  for (const entry of bundled) byKey.set(key(entry), entry);
  for (const entry of remote) byKey.set(key(entry), entry);
  return [...byKey.values()].sort(compareEntries);
}

/** Newest-first: by version between releases, by date when either side is a
 *  loader note (which has no version to compare). */
function compareEntries(a: ChangelogEntry, b: ChangelogEntry): number {
  if (a.version && b.version) return compareVersions(b.version, a.version);
  return (b.date ?? '').localeCompare(a.date ?? '');
}

/**
 * Entries strictly newer than `seen` and no newer than `current`, capped at
 * `limit` so a user who skipped eight releases gets a readable dialog rather
 * than a wall.
 *
 * Versions compare through the project's own `compareVersions` (semver-aware,
 * prerelease-correct) rather than by string equality, so a downgrade — a user
 * rolling back a bad build — shows nothing instead of replaying old notes.
 *
 * The `current` ceiling is what keeps the remote feed honest: the channel is
 * updated independently of releases, so it routinely describes a version newer
 * than the binary the user is running. Announcing "what's new in 5.2.0" to
 * someone still on 5.1.0 would be a lie about their own install.
 */
export function entriesSince(
  entries: ChangelogEntry[],
  seen: string,
  current: string,
  limit = 3,
  loader?: { current: number; seen: number },
): ChangelogEntry[] {
  return entries
    .filter((e) => {
      if (isLoaderEntry(e)) {
        // A loader note has no app version to clamp against; the equivalent
        // ceiling is the loader the user actually has planted, so a note never
        // describes a payload they have not received. Without loader context
        // (an older caller) they stay hidden rather than being announced early.
        if (!loader) return false;
        const v = e.loader_version as number;
        return v > loader.seen && v <= loader.current;
      }
      return compareVersions(e.version, seen) > 0 && compareVersions(e.version, current) <= 0;
    })
    .slice(0, limit);
}

/**
 * What the "What's new" dialog should show on this launch, given what the user
 * has already been shown and whether this machine has run RSMM before.
 *
 * Three cases, and the middle one is the reason this is a function rather than
 * a comparison inlined into the component:
 *
 * - A returning user with a recorded mark gets everything since that mark.
 * - A returning user with *no* mark is someone upgrading into the first build
 *   that ships a changelog. They get the current release's notes only — going
 *   further back would dump the entire file on them.
 * - A first-ever launch gets nothing. There is no "new" for someone who has
 *   never seen the old.
 */
export function pendingEntries(args: {
  entries: ChangelogEntry[];
  seen: string | null;
  current: string;
  hasRunBefore: boolean;
  limit?: number;
  /** Planted loader build, and the newest loader note already shown. */
  loader?: { current: number; seen: number };
}): ChangelogEntry[] {
  const { entries, seen, current, hasRunBefore, limit = 3, loader } = args;
  if (seen !== null) return entriesSince(entries, seen, current, limit, loader);
  if (!hasRunBefore) return [];
  // First run with a mark of any kind: show the current release only. A loader
  // note is not "the current release", so it is not the thing to open with.
  const newest = entries.find((e) => e.version && compareVersions(e.version, current) <= 0);
  return newest ? [newest] : [];
}

/**
 * Everything this client knows about, freshest first: the published feed folded
 * over the bundled copy.
 *
 * Never rejects. The CLI already degrades from live fetch to cache to bundled
 * copy, and a "what changed" dialog that throws because the network is down is
 * worse than one showing slightly old notes.
 */
export async function loadChangelog(opts: { refresh?: boolean } = {}): Promise<ChangelogEntry[]> {
  try {
    const result = await fetchChangelog(opts);
    if (result?.entries?.length) return mergeEntries(result.entries);
  } catch {
    /* channel unreachable, or not running under Tauri — bundled copy stands */
  }
  // Loader notes sort by date among the releases: they have no version to
  // compare, and `compareVersions('', x)` would bury them all at the bottom.
  return [...BUNDLED_CHANGELOG].sort(compareEntries);
}
