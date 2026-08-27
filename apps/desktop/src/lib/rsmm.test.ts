import { beforeEach, describe, expect, it, vi } from 'vitest';

// rsmm.ts pulls in the Tauri bridges at module load. Nothing under test here
// spawns a process — these stubs exist so the import resolves outside a webview.
vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(async () => ({ code: 0, stdout: '', stderr: '' })),
}));
vi.mock('@tauri-apps/plugin-shell', () => ({
  Command: { sidecar: vi.fn(), create: vi.fn() },
}));

import { useApp } from '../store';
import { formatBytes, parseProgressLine, rsmmEnv } from './rsmm';

/**
 * `RSMM_MODS_DIR` is the directory the CLI creates, overwrites and DELETES in.
 * The profile id is interpolated into it, so an id that is not a plain path
 * segment walks the whole apply/restore pipeline out of the mods tree. The
 * store sanitizes ids at the boundary; this asserts the sink refuses one
 * anyway, because a future caller could pass an id that never went through the
 * store at all.
 */
describe('rsmmEnv', () => {
  beforeEach(() => {
    useApp.setState({
      settings: { ...useApp.getState().settings, modsDir: '/srv/rsmm/mods' },
      activeProfileId: 'default',
    });
  });

  it('builds the profile path from the active profile', () => {
    useApp.setState({ activeProfileId: 'keeper' });
    expect(rsmmEnv().RSMM_MODS_DIR).toBe('/srv/rsmm/mods/profiles/keeper');
  });

  it('honours an explicit profile id', () => {
    expect(rsmmEnv('other').RSMM_MODS_DIR).toBe('/srv/rsmm/mods/profiles/other');
  });

  it('falls back to the default profile for a traversing id', () => {
    for (const bad of ['../../../../tmp/pwned', 'a/b', 'a\\b', '..', '', 'has space']) {
      expect(rsmmEnv(bad).RSMM_MODS_DIR).toBe('/srv/rsmm/mods/profiles/default');
    }
  });

  it('falls back when the ACTIVE profile id is unsafe', () => {
    useApp.setState({ activeProfileId: '../../etc' });
    expect(rsmmEnv().RSMM_MODS_DIR).toBe('/srv/rsmm/mods/profiles/default');
  });

  it('uses the platform default when no mods dir is configured', () => {
    useApp.setState({ settings: { ...useApp.getState().settings, modsDir: '   ' } });
    expect(rsmmEnv('p1').RSMM_MODS_DIR).toMatch(/\/profiles\/p1$/);
    expect(rsmmEnv('p1').RSMM_MODS_DIR).not.toMatch(/^\s*\/profiles/);
  });
});

describe('parseProgressLine', () => {
  it('reads a well-formed progress line', () => {
    expect(
      parseProgressLine('  {"progress":{"phase":"download","received":10,"total":100}}  '),
    ).toEqual({ phase: 'download', received: 10, total: 100 });
  });

  it('tolerates a missing phase', () => {
    expect(parseProgressLine('{"progress":{"received":1,"total":2}}')).toEqual({
      phase: '',
      received: 1,
      total: 2,
    });
  });

  it('returns null for ordinary log output, not just malformed JSON', () => {
    for (const line of [
      '',
      'planting winhttp.dll',
      '{"not-progress":1}',
      '{"progress":{"received":"10","total":100}}',
      '{"progress":{"received":10}}',
      '{"progress": truncated…',
    ]) {
      expect(parseProgressLine(line), line).toBeNull();
    }
  });
});

describe('formatBytes', () => {
  it('scales through the units at 1024', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(1024)).toBe('1.0 KB');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(5.4 * 1024 * 1024)).toBe('5.4 MB');
    expect(formatBytes(3 * 1024 ** 3)).toBe('3.0 GB');
  });

  it('stops at GB rather than running off the unit list', () => {
    expect(formatBytes(4096 * 1024 ** 3)).toMatch(/ GB$/);
  });

  it('reads a missing or nonsensical size as zero', () => {
    for (const n of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(formatBytes(n)).toBe('0 B');
    }
  });
});
