import { describe, expect, it } from 'vitest';
import {
  MACHINE_LOCAL_SETTING_KEYS,
  isSafeProfileId,
  sanitizeDirInput,
  sanitizeDirSetting,
  sanitizeSources,
} from './untrusted-state';

describe('isSafeProfileId', () => {
  it('accepts the ids the app actually mints', () => {
    for (const id of ['default', 'chaos', 'a1b2c3d4e5f6', 'my-profile_2']) {
      expect(isSafeProfileId(id)).toBe(true);
    }
  });

  it('rejects anything that could leave the profiles directory', () => {
    // Each of these, interpolated into `${modsDir}/profiles/${id}`, lands
    // outside the mods tree — where the CLI would then create, overwrite and
    // delete files.
    for (const id of [
      '..',
      '../..',
      '../../../../etc',
      'a/b',
      'a\\b',
      '/etc/passwd',
      'C:\\Windows',
      '.',
      'has space',
      'nul\u0000byte',
      '',
      'x'.repeat(65),
    ]) {
      expect(isSafeProfileId(id), `${JSON.stringify(id)} must be rejected`).toBe(false);
    }
  });

  it('rejects non-strings', () => {
    for (const v of [null, undefined, 42, {}, ['default']]) {
      expect(isSafeProfileId(v)).toBe(false);
    }
  });
});

describe('sanitizeDirSetting', () => {
  it('keeps the path shapes a user legitimately types', () => {
    for (const dir of [
      '~/.local/share/rsmm/mods',
      '%APPDATA%\\rsmm\\mods',
      'C:\\Games\\Ravenswatch',
      '/srv/games/mods',
      '\\\\nas\\share\\mods',
    ]) {
      expect(sanitizeDirSetting(dir, 'FALLBACK')).toBe(dir);
    }
  });

  it('trims surrounding whitespace', () => {
    expect(sanitizeDirSetting('  /srv/mods  ', 'FALLBACK')).toBe('/srv/mods');
  });

  it('falls back on empty, missing, or non-string values', () => {
    for (const v of ['', '   ', undefined, null, 7, {}]) {
      expect(sanitizeDirSetting(v, 'FALLBACK')).toBe('FALLBACK');
    }
  });

  it('falls back on control characters, which no real path contains', () => {
    for (const v of ['/srv/mods\u0000/etc', '/srv/\nmods', '/srv/mods\u007f']) {
      expect(sanitizeDirSetting(v, 'FALLBACK')).toBe('FALLBACK');
    }
  });
});

describe('sanitizeSources', () => {
  const fallback = ['https://rsmm.me/registry'];

  it('keeps http(s) sources and de-duplicates', () => {
    expect(
      sanitizeSources(
        ['https://a.example/r', 'http://b.example/r', 'https://a.example/r'],
        fallback,
      ),
    ).toEqual(['https://a.example/r', 'http://b.example/r']);
  });

  it('drops entries that are not http(s)', () => {
    expect(sanitizeSources(['javascript:alert(1)', 'https://ok.example/r'], fallback)).toEqual([
      'https://ok.example/r',
    ]);
    expect(sanitizeSources(['file:///etc/passwd'], fallback)).toEqual(fallback);
  });

  it('falls back when the stored value is not a list', () => {
    for (const v of [undefined, null, 'https://a.example/r', {}]) {
      expect(sanitizeSources(v, fallback)).toEqual(fallback);
    }
  });
});

describe('MACHINE_LOCAL_SETTING_KEYS', () => {
  it('covers every directory setting an import must not move', () => {
    expect([...MACHINE_LOCAL_SETTING_KEYS].sort()).toEqual(['backupDir', 'gameDir', 'modsDir']);
  });
});

describe('sanitizeDirInput', () => {
  it('keeps an empty value empty', () => {
    // The mods folder field means "use the default" when blank, so a field
    // that refills itself the moment you clear it cannot be cleared.
    expect(sanitizeDirInput('')).toBe('');
  });

  it('leaves an ordinary path alone, spaces included', () => {
    expect(sanitizeDirInput('C:\\Program Files\\Ravenswatch')).toBe(
      'C:\\Program Files\\Ravenswatch',
    );
    expect(sanitizeDirInput('~/games/rw ')).toBe('~/games/rw ');
  });

  it('removes control characters rather than rejecting the value', () => {
    // These reach `rsmmEnv` and become an env var verbatim.
    expect(sanitizeDirInput('/srv/\u0000mods\u001b[31m')).toBe('/srv/mods[31m');
    expect(sanitizeDirInput('/srv/\nmods')).toBe('/srv/mods');
  });
});
