import { invoke } from '@tauri-apps/api/core';
import { useApp } from '../store';
import { t } from './i18n';
import {
  type InstallResult,
  type LocalMod,
  installModFromIndex,
  installModVersion,
  listLocalModsForProfile,
  modsRoot,
} from './rsmm';

/**
 * Profile operations that have to move files as well as store rows.
 *
 * Every profile owns a folder, `<modsRoot>/profiles/<id>`, and every CLI call
 * runs with `RSMM_MODS_DIR` pointed at one of them. A store row that names a
 * mod its folder does not hold is a mod that profile does not have: the
 * Library shows it as "not on disk" and `apply` installs nothing for it. The
 * helpers here are the places where the row and the folder are kept in step,
 * so each screen does not have to remember to.
 */

/**
 * Duplicate a profile: the store row AND the mods in its folder.
 *
 * The copy also becomes the active profile, so a copy with no folder showed an
 * empty Library for both it and (until re-activated) the original.
 * `copyError` is set when the row was copied but the files were not.
 */
export async function duplicateProfileWithMods(
  sourceId: string,
): Promise<{ id: string; copyError: string | null }> {
  const id = useApp.getState().duplicateProfile(sourceId);
  // The store hands back the source id when there was nothing to duplicate.
  if (id === sourceId) return { id, copyError: null };
  try {
    await invoke('copy_profile_dir', {
      modsRoot: modsRoot(),
      fromProfileId: sourceId,
      toProfileId: id,
    });
    return { id, copyError: null };
  } catch (err) {
    return { id, copyError: err instanceof Error ? err.message : String(err) };
  }
}

/**
 * Capture the target before downloading so its folder and profile entry agree,
 * even if the user changes the active profile while the download is running.
 */
export function resolveInstallTarget(requested?: string): string {
  return requested ?? useApp.getState().activeProfileId;
}

/** Resolve both folder ids and registry slugs against one profile's listing. */
export function modIdsOf(
  mods: ReadonlyArray<{ id: string; slug: string }> | null,
): Map<string, string> {
  const ids = new Map<string, string>();
  for (const m of mods ?? []) {
    ids.set(m.id, m.id);
    ids.set(m.slug, m.id);
  }
  return ids;
}

/** Reconcile completed batch installs once their final folder ids are known. */
export function syncInstalledMods(mods: LocalMod[], profileId: string, slugs: string[]): void {
  const ids = modIdsOf(mods);
  for (const slug of slugs) {
    const id = ids.get(slug);
    if (id !== undefined) useApp.getState().installMod(slug, profileId, id);
  }
  useApp.getState().syncLocalMods(mods, profileId);
}

/**
 * Put a mod from the index into a profile: download it into THAT profile's
 * folder unless it is already there, then add it to the profile.
 *
 * Whether it is "already there" is asked of the target's own folder. The store's
 * `installed` list describes the ACTIVE profile, and judging another profile by
 * it skipped the download whenever the active one happened to have the mod —
 * including right after creating a new profile to install into, when the list
 * still described the profile just switched away from.
 *
 * `installMod` makes the target the active profile, so its listing is synced
 * into the store afterwards. A batch passes `onDisk` (the target folder's ids,
 * listed once and updated here as mods land) and calls `syncInstalledMods`
 * with its completed slugs at the end, when newly downloaded folder ids are known.
 * `version` installs that exact version instead of the latest. Returns whether
 * anything was downloaded.
 */
export async function installModIntoProfile(
  slug: string,
  profileId: string,
  opts: { version?: string; onDisk?: Map<string, string> } = {},
): Promise<boolean> {
  const listed = opts.onDisk ? null : await listLocalModsForProfile(profileId);
  const onDisk = opts.onDisk ?? modIdsOf(listed);
  let downloaded = false;
  if (!onDisk.has(slug)) {
    const result: InstallResult | null = opts.version
      ? await installModVersion(slug, opts.version, profileId)
      : await installModFromIndex(slug, profileId);
    // The bridge reports a failed install as `ok: false` with exit 0, so a
    // result that is not checked is a failure that reads as success.
    if (!result || !result.ok) {
      throw new Error(result?.error ?? t('failed to install {slug}', { slug }));
    }
    onDisk.set(slug, slug);
    downloaded = true;
  }
  if (opts.onDisk) {
    useApp.getState().installMod(slug, profileId, onDisk.get(slug));
    return downloaded;
  }
  const fresh = downloaded ? await listLocalModsForProfile(profileId) : listed;
  const id = modIdsOf(fresh).get(slug) ?? onDisk.get(slug) ?? slug;
  useApp.getState().installMod(slug, profileId, id);
  if (fresh) useApp.getState().syncLocalMods(fresh, profileId);
  return downloaded;
}
