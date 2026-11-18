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
