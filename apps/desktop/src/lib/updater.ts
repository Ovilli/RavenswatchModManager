/**
 * Wraps the Tauri updater plugin so the React side can:
 *  - check for updates,
 *  - track download progress,
 *  - apply + relaunch.
 *
 * All entry points fail closed when running outside a Tauri shell (web preview,
 * unit tests), so callers can render the UI defensively.
 */

export interface AvailableUpdate {
  version: string;
  currentVersion: string;
  date?: string;
  body?: string;
  apply: (onProgress?: (downloaded: number, total: number | null) => void) => Promise<void>;
}

import { t } from './i18n';
import { inTauri } from './platform';

export interface UpdateCheckError {
  error: true;
  reason: string;
}

/** Where users get a build when the in-app updater can't write over this install. */
export const RELEASES_URL = 'https://github.com/Ovilli/RavenswatchModManager/releases/latest';

export interface InstallTarget {
  /** 'appimage' | 'system-package' | 'portable' | 'unsupported-check' */
  kind: string;
  path: string | null;
  /** False when an in-place update would fail with EACCES. */
  writable: boolean;
  reason: string;
  /** True when `migrateToAppImage()` can rescue this install (Linux only). */
  canMigrate?: boolean;
}

/** What `migrateToAppImage()` planted, and what it left behind. */
export interface MigrationResult {
  /** Where the self-updating AppImage now lives. */
  path: string;
  /** The desktop entry that was rewritten to point at it, if any. */
  desktopEntry: string | null;
  version: string;
  /** How to remove the system package this copy supersedes, when there is one. */
  leftover: string | null;
}

/** Progress event emitted by the Rust side while the AppImage downloads. */
export const MIGRATE_PROGRESS_EVENT = 'updater://migrate-progress';

/**
 * Ask the Rust side whether the updater can actually replace this install.
 *
 * The Tauri updater rewrites the running binary (on Linux: the `$APPIMAGE`
 * file, and it needs the containing directory too, because it renames the old
 * file into a scratch dir alongside it). When that isn't permitted the plugin
 * only reports `Permission denied (os error 13)` after a full download, so we
 * check first and offer `migrateToAppImage()` (or, failing that, a manual
 * download) instead.
 *
 * Returns `null` when the check can't run (web preview, older shell) — callers
 * should treat that as "go ahead and try".
 */
export async function getInstallTarget(): Promise<InstallTarget | null> {
  if (!inTauri()) return null;
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    return await invoke<InstallTarget>('update_install_target');
  } catch (err) {
    console.warn('[Updater] install-target probe unavailable:', err);
    return null;
  }
}

/** True when a failure string is the updater's write-permission error. */
export function isPermissionError(detail: string): boolean {
  return /os error 13|Permission denied|EACCES|Access is denied|os error 5/i.test(detail);
}

export async function openReleasesPage(): Promise<void> {
  if (!inTauri()) {
    window.open(RELEASES_URL, '_blank', 'noopener');
    return;
  }
  const { openUrl } = await import('@tauri-apps/plugin-opener');
  await openUrl(RELEASES_URL);
}

/**
 * Escape a Linux install the updater can never write to.
 *
 * A `.deb` lives in `/usr/bin` and an AppImage can sit in a root-owned store;
 * either way Tauri's in-place updater dead-ends and the user has been
 * reinstalling by hand on every release. This downloads the pending update
 * (signature-verified by the updater plugin, same pubkey as a normal update),
 * installs it as an AppImage under `~/Applications`, and repoints the desktop
 * entry. `$APPIMAGE` is set from the next launch onward, so the ordinary
 * updater takes over and this never runs again.
 *
 * Call `relaunchMigrated()` and then quit — the new process starts once this
 * one is gone (single-instance would otherwise bounce it).
 */
export async function migrateToAppImage(
  onProgress?: (downloaded: number, total: number | null) => void,
): Promise<MigrationResult> {
  if (!inTauri()) throw new Error(t('Not running in the desktop app.'));
  const { invoke } = await import('@tauri-apps/api/core');
  const { listen } = await import('@tauri-apps/api/event');

  const stop = onProgress
    ? await listen<{ downloaded: number; total: number | null }>(MIGRATE_PROGRESS_EVENT, (e) => {
        onProgress(e.payload.downloaded, e.payload.total ?? null);
      })
    : null;
  try {
    return await invoke<MigrationResult>('migrate_to_appimage');
  } finally {
    stop?.();
  }
}

/** Queue the migrated AppImage to start once this process exits. */
export async function relaunchMigrated(): Promise<void> {
  if (!inTauri()) return;
  const { invoke } = await import('@tauri-apps/api/core');
  await invoke('relaunch_migrated_appimage');
}

export async function checkForUpdate(): Promise<AvailableUpdate | UpdateCheckError | null> {
  if (!inTauri()) return null;
  const { check } = await import('@tauri-apps/plugin-updater');
  let update: Awaited<ReturnType<typeof check>> | null = null;
  try {
    update = await check();
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    console.error('[Updater] Check failed:', reason);
    // Return error to let UI display it instead of silently failing
    return {
      error: true,
      reason: t('Update check failed: {error}', { error: reason }),
    };
  }
  if (!update) return null;

  return {
    version: update.version,
    currentVersion: update.currentVersion,
    date: update.date,
    body: update.body,
    apply: async (onProgress) => {
      let downloaded = 0;
      let total: number | null = null;
      await update.downloadAndInstall((event) => {
        if (event.event === 'Started') {
          total = event.data.contentLength ?? null;
          onProgress?.(0, total);
        } else if (event.event === 'Progress') {
          downloaded += event.data.chunkLength;
          onProgress?.(downloaded, total);
        } else if (event.event === 'Finished') {
          onProgress?.(total ?? downloaded, total);
        }
      });
    },
  };
}

export async function relaunchApp(): Promise<void> {
  if (!inTauri()) return;
  const { relaunch } = await import('@tauri-apps/plugin-process');
  await relaunch();
}

/**
 * The version of the launcher that is actually running.
 *
 * Tauri's `getVersion()` reads the version baked into the bundle at build
 * time (`tauri.conf.json`), which is the number the updater compares
 * against — so it is the honest answer for "what am I running?". Outside a
 * Tauri shell (web preview, unit tests) there is no bundle to ask, and the
 * caller falls back to the compiled-in `package.json` version.
 */
export async function getAppVersion(): Promise<string | null> {
  if (!inTauri()) return null;
  try {
    const { getVersion } = await import('@tauri-apps/api/app');
    return await getVersion();
  } catch (err) {
    console.warn('[Updater] getVersion unavailable:', err);
    return null;
  }
}
