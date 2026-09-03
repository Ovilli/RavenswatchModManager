import { safeHttpUrl } from '@rsmm/schemas';

/**
 * Guards for store values that did not come from this app's own UI.
 *
 * Two sources feed the store without a user typing into a field:
 *
 *  - `importBackup()` / `importProfile()`, which decode a base64 "code" that is
 *    designed to be pasted between people (Discord, a forum post, a wiki), and
 *  - zustand's `persist` rehydrate, reading a localStorage blob that a crash,
 *    a partial write, or a hand-edit can leave malformed.
 *
 * Neither is trusted input, and both land on values that become filesystem
 * paths: a profile id is interpolated into `RSMM_MODS_DIR` for every CLI call
 * (`lib/rsmm.ts::rsmmEnv`) and into `mkdir -p` / `open('file://…')`
 * (`routes/profiles.tsx::onOpenFolder`). `hydrateSettings` already sanitized
 * the appearance keys for exactly this reason — "read straight into CSS" — but
 * the filesystem half was passing through untouched.
 */

/**
 * A profile id is used as a single path segment. Anything outside this shape —
 * `..`, a slash, a backslash, a NUL, a drive letter — would let a pasted backup
 * code walk `RSMM_MODS_DIR` out of the mods tree and point apply/restore at an
 * arbitrary directory.
 *
 * Matches the check `onOpenFolder` already performs at its call site; the point
 * of putting it here is that the *boundary* enforces it, so a sink added later
 * cannot forget to.
 */
export const PROFILE_ID_RE = /^[A-Za-z0-9_-]{1,64}$/;

export function isSafeProfileId(id: unknown): id is string {
  return typeof id === 'string' && PROFILE_ID_RE.test(id);
}

/**
 * Machine-local settings, which an import must never carry.
 *
 * These are absolute paths on one particular computer. A backup made on
 * someone else's machine names directories that do not exist here, so honouring
 * them is wrong even when the code is entirely well-meant — and when it is not,
 * it silently repoints every subsequent `rsmm apply` / `restore` at a directory
 * the person importing never chose. Keeping the local values is both the safe
 * answer and the correct one.
 */
export const MACHINE_LOCAL_SETTING_KEYS = ['gameDir', 'modsDir', 'backupDir'] as const;

export type MachineLocalSettingKey = (typeof MACHINE_LOCAL_SETTING_KEYS)[number];

/**
 * Sanitize a directory setting read back from localStorage.
 *
 * This is the rehydrate path, not the import path: the value was typed by this
 * user on this machine, so the shape is theirs to choose (`~/…`, `%APPDATA%\…`,
 * a UNC path). Only genuinely malformed values are rejected — control
 * characters, which no path contains and which would be passed to a process
 * argument or an env var verbatim.
 */
export function sanitizeDirSetting(value: unknown, fallback: string): string {
  if (typeof value !== 'string') return fallback;
  const trimmed = value.trim();
  if (!trimmed) return fallback;
  // biome-ignore lint/suspicious/noControlCharactersInRegex: rejecting control characters is the point.
  if (/[\u0000-\u001f\u007f]/.test(trimmed)) return fallback;
  return trimmed;
}

/**
 * Strip control characters from a directory the user is typing right now.
 *
 * `sanitizeDirSetting` is the REHYDRATE path and substitutes a fallback for an
 * empty value, which is wrong mid-edit: the mods folder field is documented as
 * "leave empty to use the default", and a field that refills itself the moment
 * you clear it cannot be cleared. So this keeps empty as empty and only
 * removes what must never reach a process argument.
 *
 * Needed because sanitisation ran only on rehydrate and on import — a pasted
 * control character stayed live in `RSMM_MODS_DIR` until the next restart.
 */
export function sanitizeDirInput(value: string): string {
  // biome-ignore lint/suspicious/noControlCharactersInRegex: removing control characters is the point.
  return value.replace(/[\u0000-\u001f\u007f]/g, '');
}

/**
 * Registry sources are fetched over the network, so a stored value that is not
 * an http(s) URL is dropped rather than carried. `safeHttpUrl` is the same
 * allowlist the API and website use.
 */
export function sanitizeSources(value: unknown, fallback: string[]): string[] {
  if (!Array.isArray(value)) return fallback;
  const cleaned = value
    .map((entry) => safeHttpUrl(typeof entry === 'string' ? entry : null))
    .filter((entry): entry is string => entry !== null);
  return cleaned.length ? [...new Set(cleaned)] : fallback;
}
