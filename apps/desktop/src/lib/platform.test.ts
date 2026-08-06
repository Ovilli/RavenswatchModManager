import { describe, expect, it } from 'vitest';
import { joinPathEntries, shortcutLabel } from './platform';

describe('joinPathEntries', () => {
  it('uses the semicolon Windows actually parses', () => {
    // With ':' the repo root and the first inherited entry fuse into one
    // bogus path — the CLI stops resolving and so does whatever was first.
    expect(joinPathEntries(['C:\\repo', 'C:\\Windows\\system32'], 'windows')).toBe(
      'C:\\repo;C:\\Windows\\system32',
    );
  });

  it('uses a colon on linux', () => {
    expect(joinPathEntries(['/home/u/repo', '/usr/bin:/bin'], 'linux')).toBe(
      '/home/u/repo:/usr/bin:/bin',
    );
  });

  it('drops empty entries so no stray separator creates an empty PATH slot', () => {
    expect(joinPathEntries(['', '/usr/bin', ''], 'linux')).toBe('/usr/bin');
    expect(joinPathEntries([], 'windows')).toBe('');
  });
});

describe('shortcutLabel', () => {
  it('upper-cases the key', () => {
    expect(shortcutLabel('k')).toBe('Ctrl+K');
  });
});
