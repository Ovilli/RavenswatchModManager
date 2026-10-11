import { beforeEach, describe, expect, it, vi } from 'vitest';

const invoke = vi.fn();
const installModFromIndex = vi.fn();
const installModVersion = vi.fn();
const listLocalModsForProfile = vi.fn();

vi.mock('@tauri-apps/api/core', () => ({ invoke: (...a: unknown[]) => invoke(...a) }));
vi.mock('./rsmm', () => ({
  installModFromIndex: (...a: unknown[]) => installModFromIndex(...a),
  installModVersion: (...a: unknown[]) => installModVersion(...a),
  listLocalModsForProfile: (...a: unknown[]) => listLocalModsForProfile(...a),
  modsRoot: () => '/srv/rsmm/mods',
}));

import { type Profile, useApp } from '../store';
import {
  duplicateProfileWithMods,
  installModIntoProfile,
  resolveInstallTarget,
} from './profile-mods';

const mk = (id: string, loadOrder: string[] = []): Profile => ({
  id,
  name: id,
  loadOrder,
  disabled: new Set<string>(),
  createdAt: new Date().toISOString(),
});

const listed = (...ids: string[]) =>
  ids.map((id) => ({
    id,
    slug: id,
    name: id,
    version: '1.0.0',
    author: null,
    summary: null,
    license: null,
    tags: [],
    enabled: true,
    path: `/mods/${id}`,
    dependencies: {},
    writes: [],
  }));

beforeEach(() => {
  invoke.mockReset();
  installModFromIndex.mockReset();
  installModVersion.mockReset();
  listLocalModsForProfile.mockReset();
  useApp.setState({
    profiles: [mk('default'), mk('A', ['shared']), mk('B')],
    activeProfileId: 'A',
    // The ACTIVE profile's folder has the mod; B's does not.
    installed: ['shared'],
    localMods: {},
  });
});

describe('installModIntoProfile', () => {
  it("downloads into the target's folder even when the active profile has the mod", async () => {
    // Judged by the store's `installed` (profile A's folder), this skipped the
    // download and left B listing a mod its folder did not hold.
    listLocalModsForProfile.mockResolvedValueOnce(listed()).mockResolvedValueOnce(listed('shared'));
    installModFromIndex.mockResolvedValue({ ok: true });

    expect(await installModIntoProfile('shared', 'B')).toBe(true);
    expect(installModFromIndex).toHaveBeenCalledWith('shared', 'B');
    expect(useApp.getState().profiles.find((p) => p.id === 'B')?.loadOrder).toEqual(['shared']);
    // installMod makes the target active, and the store now describes it.
    expect(useApp.getState().activeProfileId).toBe('B');
    expect(useApp.getState().installed).toEqual(['shared']);
  });

  it("skips the download when the target's own folder already has it", async () => {
    listLocalModsForProfile.mockResolvedValue(listed('shared'));
    expect(await installModIntoProfile('shared', 'B')).toBe(false);
    expect(installModFromIndex).not.toHaveBeenCalled();
    expect(listLocalModsForProfile).toHaveBeenCalledTimes(1);
  });

  it('installs the requested version', async () => {
    listLocalModsForProfile.mockResolvedValue(listed());
    installModVersion.mockResolvedValue({ ok: true });
    await installModIntoProfile('shared', 'B', { version: '2.0.0' });
    expect(installModVersion).toHaveBeenCalledWith('shared', '2.0.0', 'B');
  });

  it('treats an ok:false result as a failure and leaves the profile alone', async () => {
    // The bridge exits 0 with `{ ok: false }`, so an unchecked result read as
    // success and the mod was added to a profile whose folder lacked it.
    listLocalModsForProfile.mockResolvedValue(listed());
    installModVersion.mockResolvedValue({ ok: false, error: 'no such version' });
    await expect(installModIntoProfile('shared', 'B', { version: '9.9.9' })).rejects.toThrow(
      'no such version',
    );
    expect(useApp.getState().profiles.find((p) => p.id === 'B')?.loadOrder).toEqual([]);
  });

  it('uses and updates a batch listing without re-listing', async () => {
    installModFromIndex.mockResolvedValue({ ok: true });
    const onDisk = new Set<string>(['one']);
    await installModIntoProfile('one', 'B', { onDisk });
    await installModIntoProfile('two', 'B', { onDisk });
    await installModIntoProfile('two', 'B', { onDisk });
    expect(installModFromIndex).toHaveBeenCalledTimes(1);
    expect(listLocalModsForProfile).not.toHaveBeenCalled();
    expect(onDisk.has('two')).toBe(true);
  });
});

describe('resolveInstallTarget', () => {
  it('passes a real profile through', () => {
    expect(resolveInstallTarget('B')).toBe('B');
    expect(resolveInstallTarget()).toBe('A');
  });

  it('turns Default into a new profile BEFORE anything is downloaded', () => {
    useApp.setState({ activeProfileId: 'default' });
    const id = resolveInstallTarget();
    expect(id).not.toBe('default');
    expect(useApp.getState().profiles.find((p) => p.id === id)?.name).toBe('My Mods');
    expect(useApp.getState().activeProfileId).toBe(id);
  });
});

describe('duplicateProfileWithMods', () => {
  it('copies the folder under the resolved mods root', async () => {
    invoke.mockResolvedValue(undefined);
    const { id, copyError } = await duplicateProfileWithMods('A');
    expect(copyError).toBeNull();
    expect(invoke).toHaveBeenCalledWith('copy_profile_dir', {
      modsRoot: '/srv/rsmm/mods',
      fromProfileId: 'A',
      toProfileId: id,
    });
    expect(useApp.getState().profiles.find((p) => p.id === id)?.loadOrder).toEqual(['shared']);
  });

  it('reports a failed copy instead of swallowing it', async () => {
    invoke.mockRejectedValue('disk full');
    expect((await duplicateProfileWithMods('A')).copyError).toBe('disk full');
  });
});
