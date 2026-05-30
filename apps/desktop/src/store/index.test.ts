import { beforeEach, describe, expect, it } from 'vitest';
import type { LocalMod } from '../lib/rsmm';
import {
  type Profile,
  detectConflicts,
  isEnabledIn,
  outdatedCount,
  outdatedMods,
  useApp,
} from './index';

function freshDefault(): Profile {
  return {
    id: 'default',
    name: 'Default',
    loadOrder: [],
    disabled: new Set<string>(),
    createdAt: new Date().toISOString(),
  };
}

/** Reset only the data slices — leave the action functions intact. */
function resetStore() {
  useApp.setState({
    profiles: [freshDefault()],
    activeProfileId: 'default',
    installed: [],
    localMods: {},
  });
}

function localMod(over: Partial<LocalMod> & { id: string }): LocalMod {
  return {
    slug: over.id,
    name: over.id,
    version: '1.0.0',
    author: null,
    summary: null,
    license: null,
    tags: [],
    enabled: true,
    path: `/mods/${over.id}`,
    dependencies: {},
    writes: [],
    ...over,
  };
}

function profileById(id: string): Profile {
  const p = useApp.getState().profiles.find((x) => x.id === id);
  if (!p) throw new Error(`no profile ${id}`);
  return p;
}

beforeEach(resetStore);

describe('share codes (export/import round-trip)', () => {
  it('round-trips a profile, preserving the disabled Set', () => {
    const s = useApp.getState();
    const srcId = s.createProfile('Loadout A');
    s.installMod('mod-a', srcId);
    s.installMod('mod-b', srcId);
    s.toggleMod('mod-b'); // disable mod-b in the active (new) profile

    const code = useApp.getState().exportProfile(srcId);
    expect(code).toBeTruthy();

    const importedId = useApp.getState().importProfile(code);
    expect(importedId).not.toBeNull();

    const imported = profileById(importedId as string);
    expect(imported.name).toBe('Loadout A (imported)');
    expect(imported.loadOrder).toEqual(['mod-a', 'mod-b']);
    expect(imported.disabled).toBeInstanceOf(Set);
    expect(imported.disabled.has('mod-b')).toBe(true);
  });

  it('rejects garbage / wrong-kind codes without throwing', () => {
    const s = useApp.getState();
    expect(s.importProfile('!!!not base64!!!')).toBeNull();
    expect(s.importProfile(btoa('{"not":"json'))).toBeNull();
    // A valid backup code is the wrong kind for importProfile.
    const backup = useApp.getState().exportBackup();
    expect(useApp.getState().importProfile(backup)).toBeNull();
  });

  it('round-trips a full backup and reports a reason on bad input', () => {
    const s = useApp.getState();
    s.createProfile('Keep me');
    const code = useApp.getState().exportBackup();

    resetStore();
    const res = useApp.getState().importBackup(code);
    expect(res.ok).toBe(true);
    expect(useApp.getState().profiles.some((p) => p.name === 'Keep me')).toBe(true);

    const bad = useApp.getState().importBackup('garbage');
    expect(bad.ok).toBe(false);
    if (!bad.ok) expect(bad.reason).toMatch(/base64|code/i);
  });
});

describe('install / uninstall / toggle / reorder', () => {
  it('routes installs targeting the default profile into a new "My Mods" profile', () => {
    const s = useApp.getState();
    s.installMod('mod-a', 'default');
    const state = useApp.getState();
    expect(state.activeProfileId).not.toBe('default');
    const active = profileById(state.activeProfileId);
    expect(active.name).toBe('My Mods');
    expect(active.loadOrder).toEqual(['mod-a']);
    // Default profile stays the vanilla load — never holds mods.
    expect(profileById('default').loadOrder).toEqual([]);
  });

  it('re-installing a disabled mod re-enables it instead of duplicating', () => {
    const s = useApp.getState();
    const pid = s.createProfile('p');
    s.installMod('mod-a', pid);
    s.toggleMod('mod-a'); // disable
    expect(profileById(pid).disabled.has('mod-a')).toBe(true);
    useApp.getState().installMod('mod-a', pid);
    const p = profileById(pid);
    expect(p.loadOrder).toEqual(['mod-a']); // not duplicated
    expect(p.disabled.has('mod-a')).toBe(false); // re-enabled
  });

  it('uninstall is per-profile and keeps the mod available in others', () => {
    const s = useApp.getState();
    const a = s.createProfile('A');
    s.installMod('mod-x', a);
    const b = useApp.getState().createProfile('B');
    useApp.getState().installMod('mod-x', b);

    // Uninstall from the active profile (B) only.
    useApp.getState().uninstallMod('mod-x');
    expect(profileById(b).loadOrder).toEqual([]);
    expect(profileById(a).loadOrder).toEqual(['mod-x']); // untouched
    expect(useApp.getState().installed).toContain('mod-x'); // stays on disk
  });

  it('reorderMod clamps the target index and moves the entry', () => {
    const s = useApp.getState();
    const pid = s.createProfile('p');
    for (const id of ['m1', 'm2', 'm3']) useApp.getState().installMod(id, pid);
    useApp.getState().reorderMod('m3', 0);
    expect(profileById(pid).loadOrder).toEqual(['m3', 'm1', 'm2']);
    useApp.getState().reorderMod('m3', 999); // clamps to end
    expect(profileById(pid).loadOrder).toEqual(['m1', 'm2', 'm3']);
  });
});

describe('syncLocalMods reconcile (the documented data-loss guard)', () => {
  it('drops a profile mod confirmed gone when the CLI returns a non-empty list', () => {
    const s = useApp.getState();
    const pid = s.createProfile('p');
    s.installMod('keep', pid);
    s.installMod('gone', pid);
    // Both were on disk previously.
    useApp.getState().syncLocalMods([localMod({ id: 'keep' }), localMod({ id: 'gone' })]);
    // Now CLI reports only `keep` — `gone` was really removed.
    useApp.getState().syncLocalMods([localMod({ id: 'keep' })]);
    expect(profileById(pid).loadOrder).toEqual(['keep']);
  });

  it('keeps profile mods when the CLI returns an EMPTY list (transient error)', () => {
    const s = useApp.getState();
    const pid = s.createProfile('p');
    s.installMod('keep', pid);
    useApp.getState().syncLocalMods([localMod({ id: 'keep' })]);
    // Empty list = likely a transient CLI failure, not a real wipe.
    useApp.getState().syncLocalMods([]);
    expect(profileById(pid).loadOrder).toEqual(['keep']);
  });

  it('always clears the default profile and tracks installed from disk', () => {
    const s = useApp.getState();
    s.installMod('m', 'default'); // creates My Mods, m on disk
    useApp.getState().syncLocalMods([localMod({ id: 'm' }), localMod({ id: 'n' })]);
    expect(profileById('default').loadOrder).toEqual([]);
    expect(useApp.getState().installed.sort()).toEqual(['m', 'n']);
  });
});

describe('selectors', () => {
  it('isEnabledIn requires loadOrder membership and absence from disabled', () => {
    const p: Profile = {
      ...freshDefault(),
      id: 'p',
      loadOrder: ['a', 'b'],
      disabled: new Set(['b']),
    };
    expect(isEnabledIn(p, 'a')).toBe(true);
    expect(isEnabledIn(p, 'b')).toBe(false); // disabled
    expect(isEnabledIn(p, 'c')).toBe(false); // not in profile
  });

  it('detectConflicts flags shared write paths among enabled mods only', () => {
    const s = useApp.getState();
    const pid = s.createProfile('p');
    s.installMod('a', pid);
    useApp.getState().installMod('b', pid);
    useApp.getState().installMod('c', pid);
    useApp
      .getState()
      .syncLocalMods([
        localMod({ id: 'a', writes: ['shared.cfg', 'a.cfg'] }),
        localMod({ id: 'b', writes: ['shared.cfg'] }),
        localMod({ id: 'c', writes: ['shared.cfg'] }),
      ]);
    // Disable c — it must not count toward the conflict.
    useApp.getState().toggleMod('c');

    const conflicts = detectConflicts(profileById(pid));
    expect(conflicts).toHaveLength(1);
    const [conflict] = conflicts;
    expect(conflict).toBeDefined();
    expect(conflict?.path).toBe('shared.cfg');
    expect(conflict?.modIds.sort()).toEqual(['a', 'b']);
  });

  it('outdatedCount / outdatedMods compare version against latestVersion', () => {
    const s = useApp.getState();
    const pid = s.createProfile('p');
    s.installMod('old', pid);
    useApp.getState().installMod('current', pid);
    useApp
      .getState()
      .syncLocalMods([
        localMod({ id: 'old', version: '1.0.0' }),
        localMod({ id: 'current', version: '2.0.0' }),
      ]);
    // Bump the remote "latest" for `old` so it reads as outdated.
    useApp.getState().patchRemoteInfo({ old: { latestVersion: '1.1.0' } });

    const installed = useApp.getState().installed;
    expect(outdatedCount(installed)).toBe(1);
    expect(outdatedMods(installed).map((m) => m.id)).toEqual(['old']);
  });
});
