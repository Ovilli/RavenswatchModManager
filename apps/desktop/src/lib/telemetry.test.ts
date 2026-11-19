import { describe, expect, it } from 'vitest';
import {
  firstInSession,
  isExpectedUserError,
  isShellOpenAclNoise,
  shouldUploadCrash,
} from './telemetry';

describe('crash upload filters', () => {
  it('uploads only from a packaged Tauri build', () => {
    expect(shouldUploadCrash(false, true)).toBe(true);
    expect(shouldUploadCrash(true, true)).toBe(false);
    expect(shouldUploadCrash(false, false)).toBe(false);
  });

  it('drops the CLI guard refusals, keeps real failures', () => {
    expect(
      isExpectedUserError(
        'rsmm apply failed (exit 1): Could not autodetect Ravenswatch install. Pass --game-dir',
      ),
    ).toBe(true);
    expect(
      isExpectedUserError('rsmm apply failed (exit 1): [FAIL] Ravenswatch is running — close it'),
    ).toBe(true);
    expect(
      isExpectedUserError('[FAIL] another rsmm process is working on this install (pid 1, apply)'),
    ).toBe(true);
    expect(isExpectedUserError('rsmm json run timed out after 60000ms')).toBe(false);
    expect(isExpectedUserError('rsmm apply failed (exit 1): Traceback …')).toBe(false);
  });

  it('drops the shell-plugin link-hook rejection', () => {
    expect(isShellOpenAclNoise('Command plugin:shell|open not allowed by ACL')).toBe(true);
    expect(isShellOpenAclNoise('Command plugin:window|destroy not allowed by ACL')).toBe(false);
  });

  it('reports a given error once per session', () => {
    expect(firstInSession('TypeError', 'boom')).toBe(true);
    expect(firstInSession('TypeError', 'boom')).toBe(false);
    expect(firstInSession('Error', 'boom')).toBe(true);
  });
});

describe('loader perf report upload (issue #175)', () => {
  const figures = (lua: number, max: number, slow: number, at = 'tick') => ({
    calls: 100,
    lua_ms: lua,
    max_ms: max,
    max_in: at,
    slow,
  });

  it('sends whole-session figures, busiest mod first, and flags a hitch', async () => {
    const { perfRunBody } = await import('./telemetry');
    const body = perfRunBody(
      {
        session_s: 3600,
        session: 'ab12',
        lua_ms: 50,
        slow_calls: 0,
        wait_max_ms: 2,
        session_wait_max_ms: 40,
        mods: {
          quiet: { ...figures(5, 1, 0), heap_kb: 900, heap_first_kb: 800 },
          'camera-control': {
            ...figures(40, 3, 0),
            heap_kb: 4096,
            heap_first_kb: 1024,
            session: figures(9000, 120, 7, 'hook 0x140397540'),
          },
        },
      },
      'linux',
    );
    expect(body.ok).toBe(false);
    expect(body.durationMs).toBe(3_600_000);
    const mods = body.payload?.mods as Array<Record<string, unknown>>;
    expect(mods[0]).toMatchObject({
      id: 'camera-control',
      luaMs: 9000,
      slow: 7,
      maxIn: 'hook 0x140397540',
      heapGrowKb: 3072,
    });
    expect(body.payload?.waitMaxMs).toBe(40);
  });

  it('a session with no slow call and no long wait is ok', async () => {
    const { perfRunBody } = await import('./telemetry');
    const body = perfRunBody(
      {
        lua_ms: 1,
        slow_calls: 0,
        wait_max_ms: 1,
        session_wait_max_ms: 3,
        mods: { m: { ...figures(1, 1, 0), heap_kb: 1, heap_first_kb: 1 } },
      },
      'windows',
    );
    expect(body.ok).toBe(true);
    expect(body.durationMs).toBeUndefined();
  });
});
