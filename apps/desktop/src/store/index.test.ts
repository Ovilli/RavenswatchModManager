import { beforeEach, describe, expect, it } from 'vitest';
import type { LocalMod } from '../lib/rsmm';
import {
  type Profile,
  detectConflicts,
  hydrateSettings,
  isEnabledIn,
  outdatedCount,
  outdatedMods,
  splitProfileMods,
  splitProfileModsAgainst,
  unadoptedMods,
  useApp,
} from './index';

function freshDefault(): Profile {
  return {
    id: 'default',
    name: 'My mods',
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

describe('starter profile and saved profiles', () => {
  it('starts with one empty My mods list and no Chaos Run', () => {
    const state = useApp.getInitialState();
    expect(state.profiles).toEqual([
      expect.objectContaining({
        id: 'default',
        name: 'My mods',
        loadOrder: [],
        disabled: new Set(),
      }),
    ]);
    expect(state.activeProfileId).toBe(state.profiles[0]?.id);
    expect(state.installed).toEqual([]);
    expect(state.localMods).toEqual({});
  });

  it('upgrades the legacy label without moving, merging or clearing saved lists', async () => {
    const profiles = [
      { ...freshDefault(), name: 'Default', loadOrder: ['starter-mod'], disabled: ['starter-mod'] },
      {
        ...freshDefault(),
        id: 'chaos',
        name: 'Chaos Run',
        loadOrder: ['hyper-aggro'],
        disabled: [],
      },
      {
        ...freshDefault(),
        id: 'personal',
        name: 'My mods',
        loadOrder: ['own-mod'],
        disabled: ['own-mod'],
      },
    ];
    localStorage.setItem(
      'rsmm-grimoire',
      JSON.stringify({
        state: { profiles, activeProfileId: 'chaos' },
        version: 0,
      }),
    );

    await useApp.persist.rehydrate();

    const state = useApp.getState();
    expect(state.profiles.map((p) => p.id)).toEqual(['default', 'chaos', 'personal']);
    expect(state.activeProfileId).toBe('chaos');
    expect(profileById('default')).toMatchObject({
      name: 'My mods',
      loadOrder: ['starter-mod'],
      disabled: new Set(['starter-mod']),
    });
    expect(profileById('chaos')).toMatchObject({ name: 'Chaos Run', loadOrder: ['hyper-aggro'] });
    expect(profileById('personal')).toMatchObject({
      name: 'My mods',
      loadOrder: ['own-mod'],
      disabled: new Set(['own-mod']),
    });

    // A save and another launch retain the same profile identities and mods.
    state.updateSettings({ browseView: 'list' });
    await useApp.persist.rehydrate();
    expect(useApp.getState().profiles).toEqual(state.profiles);
    expect(useApp.getState().activeProfileId).toBe('chaos');
  });

  it('keeps a custom starter name and selection when restoring an older backup', () => {
    const code = btoa(
      JSON.stringify({
        kind: 'rsmm-backup',
        profiles: [{ ...freshDefault(), name: 'Solo run', loadOrder: ['a'], disabled: ['a'] }],
        activeProfileId: 'default',
      }),
    );
    expect(useApp.getState().importBackup(code).ok).toBe(true);
    expect(profileById('default')).toMatchObject({
      name: 'Solo run',
      loadOrder: ['a'],
      disabled: new Set(['a']),
    });
    expect(useApp.getState().activeProfileId).toBe('default');
  });

  it('does not recreate a deleted starter profile on the next launch', async () => {
    const id = useApp.getState().createProfile('Keep this list');
    useApp.getState().installMod('kept-mod', id);
    useApp.getState().deleteProfile('default');

    await useApp.persist.rehydrate();

    expect(useApp.getState().profiles).toEqual([
      expect.objectContaining({ id, loadOrder: ['kept-mod'] }),
    ]);
    expect(useApp.getState().activeProfileId).toBe(id);
  });

  it('falls back to a saved list when a backup has no valid active selection', () => {
    const code = btoa(
      JSON.stringify({
        kind: 'rsmm-backup',
        profiles: [{ ...freshDefault(), id: 'keeper', name: 'Keep this list', disabled: [] }],
        activeProfileId: 'gone',
      }),
    );
    expect(useApp.getState().importBackup(code).ok).toBe(true);
    expect(useApp.getState().profiles.map((p) => p.id)).toEqual(['keeper']);
    expect(useApp.getState().activeProfileId).toBe('keeper');
  });

  it('keeps the last profile available', () => {
    useApp.getState().deleteProfile('default');
    expect(useApp.getState().profiles).toHaveLength(1);
    expect(useApp.getState().activeProfileId).toBe('default');
  });
});

describe('sidebar collapse setting', () => {
  it('defaults to expanded', () => {
    expect(useApp.getState().settings.sidebarCollapsed).toBe(false);
  });

  it('round-trips through updateSettings', () => {
    useApp.getState().updateSettings({ sidebarCollapsed: true });
    expect(useApp.getState().settings.sidebarCollapsed).toBe(true);
    useApp.getState().updateSettings({ sidebarCollapsed: false });
    expect(useApp.getState().settings.sidebarCollapsed).toBe(false);
  });

  it('reads a missing key from an older build as expanded', () => {
    // Only an explicit `true` collapses. A persisted payload written before
    // this setting existed has no such key, and `undefined` must not be
    // coerced into hiding every label on the first launch after an update.
    const base = useApp.getState().settings;
    expect(hydrateSettings(base, {}).sidebarCollapsed).toBe(false);
    expect(hydrateSettings(base, { sidebarCollapsed: true }).sidebarCollapsed).toBe(true);
  });
});

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

/**
 * A backup code is a base64 blob designed to be pasted between people, so it is
 * hostile input by default. Two of its fields used to reach the filesystem
 * untouched: `settings.modsDir` (which becomes RSMM_MODS_DIR for every CLI
 * call, and an argument to mkdir / open) and `profiles[].id` (a path segment
 * inside it).
 */
describe('importBackup treats the payload as untrusted', () => {
  function hostileCode(payload: Record<string, unknown>): string {
    return btoa(JSON.stringify({ kind: 'rsmm-backup', ...payload }));
  }

  it("keeps this machine's directories instead of the ones in the code", () => {
    useApp.setState({
      settings: {
        ...useApp.getState().settings,
        modsDir: '/home/me/.local/share/rsmm/mods',
        gameDir: '/home/me/games/Ravenswatch',
        backupDir: '/home/me/.local/share/rsmm/backups',
      },
    });

    const res = useApp.getState().importBackup(
      hostileCode({
        profiles: [{ id: 'default', name: 'Default', loadOrder: [], disabled: [] }],
        settings: {
          modsDir: '/tmp/attacker',
          gameDir: '/tmp/attacker-game',
          backupDir: '/tmp/attacker-backups',
        },
      }),
    );

    expect(res.ok).toBe(true);
    const s = useApp.getState().settings;
    expect(s.modsDir).toBe('/home/me/.local/share/rsmm/mods');
    expect(s.gameDir).toBe('/home/me/games/Ravenswatch');
    expect(s.backupDir).toBe('/home/me/.local/share/rsmm/backups');
  });

  it('still imports the parts of a backup that are safe to carry', () => {
    const res = useApp.getState().importBackup(
      hostileCode({
        profiles: [
          { id: 'default', name: 'Default', loadOrder: [], disabled: [] },
          { id: 'keeper', name: 'Keeper', loadOrder: ['mod-a'], disabled: ['mod-a'] },
        ],
        settings: { density: 'compact' },
      }),
    );
    expect(res.ok).toBe(true);
    const keeper = useApp.getState().profiles.find((p) => p.name === 'Keeper');
    expect(keeper?.loadOrder).toEqual(['mod-a']);
    expect(useApp.getState().settings.density).toBe('compact');
  });

  it('rewrites a traversing profile id rather than storing it', () => {
    const res = useApp.getState().importBackup(
      hostileCode({
        profiles: [
          { id: 'default', name: 'Default', loadOrder: [], disabled: [] },
          { id: '../../../../tmp/pwned', name: 'Evil', loadOrder: ['mod-a'], disabled: [] },
        ],
        activeProfileId: '../../../../tmp/pwned',
      }),
    );

    expect(res.ok).toBe(true);
    const state = useApp.getState();
    for (const p of state.profiles) {
      expect(p.id).toMatch(/^[A-Za-z0-9_-]{1,64}$/);
    }
    // The id it asked to make active no longer exists, so the store falls back
    // to the default profile rather than pointing RSMM_MODS_DIR at /tmp.
    expect(state.activeProfileId).toMatch(/^[A-Za-z0-9_-]{1,64}$/);
    expect(state.activeProfileId).not.toContain('..');
    // The profile's contents survive the id rewrite — a corrupt store should
    // not cost the user their mod list.
    expect(state.profiles.find((p) => p.name === 'Evil')?.loadOrder).toEqual(['mod-a']);
  });

  it('drops a non-http registry source from a code', () => {
    const res = useApp.getState().importBackup(
      hostileCode({
        profiles: [{ id: 'default', name: 'Default', loadOrder: [], disabled: [] }],
        settings: { sources: ['javascript:alert(1)', 'https://mirror.example/registry'] },
      }),
    );
    expect(res.ok).toBe(true);
    expect(useApp.getState().settings.sources).toEqual(['https://mirror.example/registry']);
  });
});

describe('a malformed profile in a code cannot break the app', () => {
  // Every screen walks `loadOrder`, and the bad profile is persisted, so a
  // missing or non-array value used to throw on every render of every launch.
  it('importBackup gives a profile with no usable loadOrder an empty one', () => {
    const code = btoa(
      JSON.stringify({
        kind: 'rsmm-backup',
        profiles: [
          { id: 'a', name: 'No order' },
          { id: 'b', name: 'String order', loadOrder: 'mod-a', disabled: 'mod-a' },
          { id: 'c', loadOrder: ['mod-a', 7, null, 'mod-a', 'mod-b'], disabled: [1, 'mod-b'] },
          null,
          'not a profile',
        ],
      }),
    );
    expect(useApp.getState().importBackup(code).ok).toBe(true);

    expect(profileById('a').loadOrder).toEqual([]);
    expect(profileById('b').loadOrder).toEqual([]);
    expect([...profileById('b').disabled]).toEqual([]);
    expect(profileById('c').loadOrder).toEqual(['mod-a', 'mod-b']);
    expect([...profileById('c').disabled]).toEqual(['mod-b']);
    expect(typeof profileById('c').name).toBe('string');
    for (const p of useApp.getState().profiles) {
      expect(() => splitProfileMods(p)).not.toThrow();
    }
  });

  it('importProfile does the same for a single profile code', () => {
    const code = btoa(
      JSON.stringify({ kind: 'rsmm-profile', profile: { loadOrder: { x: 1 }, disabled: 3 } }),
    );
    const id = useApp.getState().importProfile(code);
    expect(id).not.toBeNull();
    const p = profileById(id as string);
    expect(p.loadOrder).toEqual([]);
    expect([...p.disabled]).toEqual([]);
    expect(p.name).toBe('Profile (imported)');
  });
});

describe('hydrateSettings sanitizes a persisted blob', () => {
  it('falls back on a directory containing control characters', () => {
    const defaults = useApp.getState().settings;
    const out = hydrateSettings(defaults, { modsDir: '/srv/mods\u0000/etc' });
    expect(out.modsDir).toBe(defaults.modsDir);
  });

  it('keeps an ordinary persisted directory', () => {
    const defaults = useApp.getState().settings;
    expect(hydrateSettings(defaults, { modsDir: 'D:\\rsmm\\mods' }).modsDir).toBe('D:\\rsmm\\mods');
  });

  it('keeps a stored language and drops one this build does not ship', () => {
    const defaults = useApp.getState().settings;
    expect(hydrateSettings(defaults, { language: 'zh-CN' }).language).toBe('zh-CN');
    // A build that dropped a language, or a hand-edited blob: fall back to
    // English rather than looking messages up in a catalog that is not there.
    expect(hydrateSettings(defaults, { language: 'kl-GL' } as never).language).toBe('en');
    expect(hydrateSettings(defaults, {}).language).toBe(defaults.language);
  });
});

describe('install / uninstall / toggle / reorder', () => {
  it('adds the first and subsequent installs to My mods without creating a profile', () => {
    const s = useApp.getState();
    s.installMod('mod-a');
    s.installMod('mod-b');
    const state = useApp.getState();
    expect(state.activeProfileId).toBe('default');
    expect(state.profiles).toHaveLength(1);
    const active = profileById(state.activeProfileId);
    expect(active.name).toBe('My mods');
    expect(active.loadOrder).toEqual(['mod-a', 'mod-b']);
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

  it('clears a stale disabled entry when adding a mod back to the profile', () => {
    const pid = useApp.getState().createProfile('p');
    useApp.setState({
      profiles: useApp
        .getState()
        .profiles.map((p) => (p.id === pid ? { ...p, disabled: new Set(['mod-a', 'other']) } : p)),
    });

    useApp.getState().installMod('mod-a', pid);

    expect(isEnabledIn(profileById(pid), 'mod-a')).toBe(true);
    expect(profileById(pid).disabled).toEqual(new Set(['other']));
  });

  it('clears disabled slug aliases when installing an on-disk folder', () => {
    const pid = useApp.getState().createProfile('p');
    useApp.getState().syncLocalMods([localMod({ id: 'folder', slug: 'registry-slug' })]);
    useApp.setState({
      profiles: useApp
        .getState()
        .profiles.map((p) =>
          p.id === pid
            ? { ...p, loadOrder: ['folder'], disabled: new Set(['folder', 'registry-slug']) }
            : p,
        ),
    });

    useApp.getState().installMod('registry-slug', pid);
    useApp.getState().syncLocalMods([localMod({ id: 'folder', slug: 'registry-slug' })]);

    expect(profileById(pid).loadOrder).toEqual(['folder']);
    expect(isEnabledIn(profileById(pid), 'folder')).toBe(true);
    expect(profileById(pid).disabled.size).toBe(0);
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

  it('preserves My mods and its disabled state while tracking files on disk', () => {
    const s = useApp.getState();
    s.installMod('m');
    s.toggleMod('m');
    useApp.getState().syncLocalMods([localMod({ id: 'm' }), localMod({ id: 'n' })]);
    expect(profileById('default').loadOrder).toEqual(['m']);
    expect(profileById('default').disabled).toEqual(new Set(['m']));
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

  it('outdated requires the registry version to be strictly newer', () => {
    const s = useApp.getState();
    const pid = s.createProfile('p');
    s.installMod('ahead', pid);
    useApp.getState().installMod('ten', pid);
    useApp
      .getState()
      .syncLocalMods([
        localMod({ id: 'ahead', version: '2.0.0' }),
        localMod({ id: 'ten', version: '1.9.0' }),
      ]);
    useApp.getState().patchRemoteInfo({
      // Registry is BEHIND the local install (author testing an unpublished
      // build) — must not be offered as a downgrade-"update".
      ahead: { latestVersion: '1.0.0' },
      // Numeric segment ordering: 1.10.0 > 1.9.0 (string compare would say no).
      ten: { latestVersion: '1.10.0' },
    });

    const installed = useApp.getState().installed;
    expect(outdatedMods(installed).map((m) => m.id)).toEqual(['ten']);
    expect(outdatedCount(installed)).toBe(1);
  });

  it('handles prereleases in both directions', () => {
    const s = useApp.getState();
    const pid = s.createProfile('p');
    s.installMod('on-beta', pid);
    useApp.getState().installMod('on-stable', pid);
    useApp
      .getState()
      .syncLocalMods([
        localMod({ id: 'on-beta', version: '1.0.0-rc1' }),
        localMod({ id: 'on-stable', version: '1.0.0' }),
      ]);
    useApp.getState().patchRemoteInfo({
      // Stable release supersedes the beta the user is running.
      'on-beta': { latestVersion: '1.0.0' },
      // A prerelease of the SAME version is not an upgrade for someone
      // already on the release — offering it would be a downgrade.
      'on-stable': { latestVersion: '1.0.0-rc2' },
    });

    const installed = useApp.getState().installed;
    expect(outdatedMods(installed).map((m) => m.id)).toEqual(['on-beta']);
  });
});

describe('profile state vs. what is actually on disk', () => {
  function withProfile(loadOrder: string[], disabled: string[] = []) {
    useApp.setState({
      profiles: [
        freshDefault(),
        {
          id: 'p1',
          name: 'Run',
          loadOrder,
          disabled: new Set(disabled),
          createdAt: new Date().toISOString(),
        },
      ],
      activeProfileId: 'p1',
    });
  }

  it('splits profile entries into present and missing', () => {
    withProfile(['real-mod', 'ghost-uuid']);
    useApp.getState().syncLocalMods([localMod({ id: 'real-mod' })]);

    const { present, missing } = splitProfileMods(profileById('p1'));
    // A profile that lists two mods but only has one on disk must not
    // report "2 total" — that made empty profiles look full.
    expect(present).toEqual(['real-mod']);
    expect(missing).toEqual(['ghost-uuid']);
  });

  it('pruneMissingMods drops only entries with no mod on disk', () => {
    withProfile(['real-mod', 'ghost-uuid'], ['ghost-uuid']);
    useApp.getState().syncLocalMods([localMod({ id: 'real-mod' })]);

    const removed = useApp.getState().pruneMissingMods('p1');
    expect(removed).toBe(1);
    const p = profileById('p1');
    expect(p.loadOrder).toEqual(['real-mod']);
    // The stale id must leave the disabled set too, or it keeps being
    // reported as "a disabled mod" that does not exist.
    expect(p.disabled.has('ghost-uuid')).toBe(false);
  });

  it('pruneMissingMods is a no-op when everything resolves', () => {
    withProfile(['real-mod']);
    useApp.getState().syncLocalMods([localMod({ id: 'real-mod' })]);
    expect(useApp.getState().pruneMissingMods('p1')).toBe(0);
  });

  it('reports on-disk mods the active profile has not adopted', () => {
    withProfile(['adopted']);
    useApp.getState().syncLocalMods([localMod({ id: 'adopted' }), localMod({ id: 'dropped-in' })]);

    const s = useApp.getState();
    expect(unadoptedMods(profileById('p1'), s.installed)).toEqual(['dropped-in']);
  });

  it('adoptMods adds disk mods to the active profile', () => {
    withProfile([]);
    useApp.getState().syncLocalMods([localMod({ id: 'dropped-in' })]);

    useApp.getState().adoptMods(['dropped-in']);
    expect(profileById('p1').loadOrder).toEqual(['dropped-in']);
    // Idempotent: adopting twice must not duplicate the entry.
    useApp.getState().adoptMods(['dropped-in']);
    expect(profileById('p1').loadOrder).toEqual(['dropped-in']);
  });

  it('adoptMods adds disk mods to My mods', () => {
    useApp.setState({ profiles: [freshDefault()], activeProfileId: 'default' });
    useApp.getState().syncLocalMods([localMod({ id: 'dropped-in' })]);

    useApp.getState().adoptMods(['dropped-in']);
    expect(profileById('default').loadOrder).toEqual(['dropped-in']);
  });

  it('installed reflects the latest listing, not a stale snapshot', () => {
    withProfile(['mod-a']);
    useApp.getState().syncLocalMods([localMod({ id: 'mod-a' })]);
    expect(useApp.getState().installed).toEqual(['mod-a']);

    // mod-a deleted outside the app: `installed` must follow the disk, or
    // Browse keeps disabling its install button for a mod that isn't there.
    useApp.getState().syncLocalMods([]);
    expect(useApp.getState().installed).toEqual([]);
  });
});

describe('hydrateSettings (persisted store → live settings)', () => {
  const defaults = useApp.getState().settings;

  it('backfills keys a store written by an older build never had', () => {
    const { fontFamily, fontScale, density, ...withoutAppearance } = defaults;
    const merged = hydrateSettings(defaults, withoutAppearance);
    expect(merged.fontFamily).toBe('grimoire');
    expect(merged.fontScale).toBe(100);
    expect(merged.density).toBe('cozy');
  });

  it('keeps the user’s saved choices', () => {
    const merged = hydrateSettings(defaults, {
      fontFamily: 'sans',
      fontScale: 130,
      density: 'compact',
      gameDir: '/games/Ravenswatch',
    });
    expect(merged.fontFamily).toBe('sans');
    expect(merged.fontScale).toBe(130);
    expect(merged.density).toBe('compact');
    expect(merged.gameDir).toBe('/games/Ravenswatch');
  });

  it('keeps crash reporting on unless it was explicitly turned off', () => {
    const { crashReports, ...withoutFlag } = defaults;
    expect(hydrateSettings(defaults, withoutFlag).crashReports).toBe(true);
    expect(hydrateSettings(defaults, { crashReports: false }).crashReports).toBe(false);
    expect(hydrateSettings(defaults, { crashReports: true }).crashReports).toBe(true);
  });

  it('sanitizes values that would otherwise reach the stylesheet', () => {
    const merged = hydrateSettings(defaults, {
      fontFamily: 'wingdings' as never,
      fontScale: 4000,
      density: 'roomy' as never,
    });
    expect(merged.fontFamily).toBe('grimoire');
    expect(merged.fontScale).toBe(150);
    expect(merged.density).toBe('cozy');
  });

  it('survives a completely absent settings blob', () => {
    expect(hydrateSettings(defaults, undefined)).toEqual(defaults);
  });
});

describe('adopting mods from disk', () => {
  it('seeds the profile from each mod manifest, not all-enabled', () => {
    // Adopting a folder of mostly turned-off mods used to switch every one of
    // them on, because membership in `loadOrder` IS enabled.
    const s = useApp.getState();
    s.syncLocalMods([
      localMod({ id: 'on-a', enabled: true }),
      localMod({ id: 'off-b', enabled: false }),
      localMod({ id: 'off-c', enabled: false }),
    ]);
    const pid = useApp.getState().createProfile('T');
    useApp.getState().setActiveProfile(pid);
    useApp.getState().adoptMods(['on-a', 'off-b', 'off-c']);

    const p = profileById(pid);
    expect(p.loadOrder.sort()).toEqual(['off-b', 'off-c', 'on-a']);
    expect(isEnabledIn(p, 'on-a')).toBe(true);
    expect(isEnabledIn(p, 'off-b')).toBe(false);
    expect(isEnabledIn(p, 'off-c')).toBe(false);
  });

  it('does not invent conflicts between mods the user never enabled', () => {
    const s = useApp.getState();
    s.syncLocalMods([
      localMod({ id: 'off-x', enabled: false, writes: ['same/file.gen'] }),
      localMod({ id: 'off-y', enabled: false, writes: ['same/file.gen'] }),
    ]);
    const pid = useApp.getState().createProfile('T2');
    useApp.getState().setActiveProfile(pid);
    useApp.getState().adoptMods(['off-x', 'off-y']);
    const p = profileById(pid);
    expect(detectConflicts(p)).toEqual([]);
  });
});

describe('syncLocalMods across profile switches', () => {
  // Every CLI call runs against the ACTIVE profile's directory, so a list only
  // describes that one profile. Reading it as the whole truth made every other
  // profile look stripped of its mods.
  function twoProfiles() {
    const mk = (id: string, loadOrder: string[]): Profile => ({
      id,
      name: id,
      loadOrder,
      disabled: new Set<string>(),
      createdAt: new Date().toISOString(),
    });
    useApp.setState({
      profiles: [freshDefault(), mk('A', ['x', 'y']), mk('B', ['z'])],
      activeProfileId: 'A',
      installed: [],
      localMods: {},
    });
  }

  it('keeps an inactive profile’s mods after switching away and re-listing', () => {
    twoProfiles();
    useApp.getState().syncLocalMods([localMod({ id: 'x' }), localMod({ id: 'y' })]);
    useApp.getState().setActiveProfile('B');
    useApp.getState().syncLocalMods([localMod({ id: 'z' })]);
    expect(profileById('A').loadOrder).toEqual(['x', 'y']);
    expect(profileById('B').loadOrder).toEqual(['z']);
  });

  it('leaves the active profile’s registry alone when listing another profile', () => {
    // Browse installs into a profile that is not active and syncs that
    // profile's own listing. It used to replace `localMods`/`installed` with
    // it, so the active Library showed its own mods as "not on disk".
    twoProfiles();
    useApp.getState().syncLocalMods([localMod({ id: 'x' }), localMod({ id: 'y' })]);
    useApp.getState().syncLocalMods([localMod({ id: 'z' }), localMod({ id: 'w' })], 'B');
    const s = useApp.getState();
    expect(Object.keys(s.localMods).sort()).toEqual(['x', 'y']);
    expect([...s.installed].sort()).toEqual(['x', 'y']);
    expect(splitProfileMods(profileById('A')).missing).toEqual([]);
    expect(profileById('B').loadOrder).toEqual(['z']);
  });

  it('still prunes a mod confirmed gone from the profile the list describes', () => {
    twoProfiles();
    useApp.getState().syncLocalMods([localMod({ id: 'x' }), localMod({ id: 'y' })]);
    useApp.getState().syncLocalMods([localMod({ id: 'x' })]);
    expect(profileById('A').loadOrder).toEqual(['x']);
  });
});

describe('profiles that are not active', () => {
  const mk = (id: string, loadOrder: string[]): Profile => ({
    id,
    name: id,
    loadOrder,
    disabled: new Set<string>(),
    createdAt: new Date().toISOString(),
  });

  it('splitProfileModsAgainst judges a profile by its OWN directory listing', () => {
    const p = mk('B', ['a', 'b', 'gone']);
    const split = splitProfileModsAgainst(p, [
      localMod({ id: 'a' }),
      localMod({ id: 'uuid-1', slug: 'b' }), // legacy id, matched by slug
    ]);
    expect(split.present).toEqual(['a', 'b']);
    expect(split.missing).toEqual(['gone']);
  });

  it('never prunes an inactive profile against the active profile’s registry', () => {
    useApp.setState({
      profiles: [freshDefault(), mk('A', ['x']), mk('B', ['y', 'z'])],
      activeProfileId: 'A',
      localMods: {},
    });
    useApp.getState().syncLocalMods([localMod({ id: 'x' })]);
    expect(useApp.getState().pruneMissingMods('B')).toBe(0);
    expect(profileById('B').loadOrder).toEqual(['y', 'z']);
  });

  it('prunes an inactive profile against its own list when one is supplied', () => {
    useApp.setState({
      profiles: [freshDefault(), mk('A', ['x']), mk('B', ['y', 'z'])],
      activeProfileId: 'A',
      localMods: {},
    });
    expect(useApp.getState().pruneMissingMods('B', ['y'])).toBe(1);
    expect(profileById('B').loadOrder).toEqual(['y']);
  });
});
