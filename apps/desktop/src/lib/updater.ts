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

import { inTauri } from './platform';

export interface UpdateCheckError {
  error: true;
  reason: string;
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
      reason: `Update check failed: ${reason}`,
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
