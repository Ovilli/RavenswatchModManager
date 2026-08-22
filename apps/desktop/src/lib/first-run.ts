/**
 * Persistence for the two dialogs that gate the first render: the one-time
 * AI-assistance disclosure and the post-update changelog.
 *
 * Both live in `localStorage` rather than the zustand store because the store
 * is the *user's* state — profiles, load order, settings — and is exported,
 * imported and reset by features that have no business carrying "has this
 * person read the disclosure" along with them.
 *
 * Every accessor is failure-tolerant: a disabled or full localStorage (private
 * mode, a locked-down WebView profile) must never keep the app from starting.
 * The cost of a failed read is that a dialog shows once more than it should.
 */

const DISCLOSURE_KEY = 'rsmm:ai-disclosure-ack';
const CHANGELOG_SEEN_KEY = 'rsmm:changelog-seen';
/** The zustand persist key. Its presence means this profile has run before. */
const STORE_KEY = 'rsmm-grimoire';

// Reached through `globalThis`, not `window`: the same guard has to hold in the
// non-DOM test environment, where a minimal Storage shim is installed globally
// and `window` does not exist at all.
function read(key: string): string | null {
  try {
    return globalThis.localStorage?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    globalThis.localStorage?.setItem(key, value);
  } catch {
    /* storage unavailable — the dialog returns next launch, which is fine */
  }
}

/** Version of the disclosure text the user has acknowledged, or null. */
export function disclosureAck(): string | null {
  return read(DISCLOSURE_KEY);
}

/**
 * Record acknowledgement of a specific revision of the disclosure text.
 *
 * Stamping the revision rather than a bare `true` means a materially changed
 * disclosure can be re-shown by bumping `DISCLOSURE_REVISION` — without that,
 * the only way to re-inform existing users would be to clear the key and
 * re-prompt everyone on every release.
 */
export function ackDisclosure(revision: string): void {
  write(DISCLOSURE_KEY, revision);
}

/** Newest release whose notes the user has already been shown, or null. */
export function changelogSeen(): string | null {
  return read(CHANGELOG_SEEN_KEY);
}

export function markChangelogSeen(version: string): void {
  write(CHANGELOG_SEEN_KEY, version);
}

/**
 * True when this machine has run RSMM before.
 *
 * A fresh install has nothing to be "new" about, so the changelog seeds itself
 * silently instead of greeting a first-time user with notes on a release they
 * never ran. The signal is the persisted store, not the changelog key itself —
 * an existing user upgrading into the first build that *has* a changelog has no
 * changelog key either, and would otherwise be misread as brand new and told
 * nothing on the one upgrade where the notes actually matter.
 */
export function hasRunBefore(): boolean {
  return read(STORE_KEY) !== null;
}
