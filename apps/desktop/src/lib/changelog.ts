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
  /** Release version, matching the tag without the leading `v`. */
  version: string;
  /** ISO date (YYYY-MM-DD) of the release. */
  date: string;
  /** Optional one-line framing for the release as a whole. */
  summary?: string;
  highlights: string[];
}

/** The copy shipped inside this build. Used when the channel is unreachable. */
export const BUNDLED_CHANGELOG: ChangelogEntry[] = feed.entries;

/** Newest release described by a set of entries. */
export function latestVersion(entries: ChangelogEntry[] = BUNDLED_CHANGELOG): string {
  return entries[0]?.version ?? '0.0.0';
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
  const byVersion = new Map<string, ChangelogEntry>();
  for (const entry of bundled) byVersion.set(entry.version, entry);
  for (const entry of remote) byVersion.set(entry.version, entry);
  return [...byVersion.values()].sort((a, b) => compareVersions(b.version, a.version));
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
): ChangelogEntry[] {
  return entries
    .filter((e) => compareVersions(e.version, seen) > 0 && compareVersions(e.version, current) <= 0)
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
}): ChangelogEntry[] {
  const { entries, seen, current, hasRunBefore, limit = 3 } = args;
  if (seen !== null) return entriesSince(entries, seen, current, limit);
  if (!hasRunBefore) return [];
  const newest = entries.find((e) => compareVersions(e.version, current) <= 0);
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
  return [...BUNDLED_CHANGELOG].sort((a, b) => compareVersions(b.version, a.version));
}
