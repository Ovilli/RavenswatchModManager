import { invoke } from '@tauri-apps/api/core';
import { useApp } from '../store';
import { t } from './i18n';
import {
  type InstallResult,
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

/** Name of the profile an install aimed at Default lands in (matches the store's `installMod`). */
const INSTALL_PROFILE_NAME = 'My Mods';

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
 * The profile an install should land in.
 *
 * Default is the vanilla load and never carries mods, so `installMod` reroutes
 * an install aimed at it into a fresh "My Mods" profile. That has to be decided
 * BEFORE the download: the CLI writes into the folder of the profile it is
 * given, and a mod downloaded into Default's folder and then listed under a new
 * profile is a mod the new profile does not have.
 */
export function resolveInstallTarget(requested?: string): string {
  const s = useApp.getState();
  const target = requested ?? s.activeProfileId;
  if (target !== 'default') return target;
  return s.createProfile(INSTALL_PROFILE_NAME);
}

/** Ids (and slugs) of the mods in a folder listing. */
export function modIdsOf(mods: ReadonlyArray<{ id: string; slug: string }> | null): Set<string> {
  const ids = new Set<string>();
  for (const m of mods ?? []) {
    ids.add(m.id);
    ids.add(m.slug);
  }
  return ids;
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
 * listed once and updated here as mods land) and syncs once at the end itself.
 * `version` installs that exact version instead of the latest. Returns whether
 * anything was downloaded.
 */
export async function installModIntoProfile(
  slug: string,
  profileId: string,
  opts: { version?: string; onDisk?: Set<string> } = {},
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
    onDisk.add(slug);
    downloaded = true;
  }
  useApp.getState().installMod(slug, profileId);
  if (opts.onDisk) return downloaded;
  const fresh = downloaded ? await listLocalModsForProfile(profileId) : listed;
  if (fresh) useApp.getState().syncLocalMods(fresh, profileId);
  return downloaded;
}
