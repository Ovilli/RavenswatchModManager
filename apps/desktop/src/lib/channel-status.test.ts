import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  INSTALLED_VISIBLE_MS,
  cliPendingVersion,
  describeCliSource,
  describeLoaderInstall,
  describePhase,
  failureReason,
  getChannelPhases,
  getPendingCliUpdate,
  resetChannelPhases,
  setChannelPhase,
  subscribeChannelPhases,
} from './channel-status';

beforeEach(() => {
  vi.useFakeTimers();
  resetChannelPhases();
});
afterEach(() => {
  vi.useRealTimers();
});

describe('describePhase', () => {
  it('says nothing when idle', () => {
    expect(describePhase('cli', { kind: 'idle' })).toBeNull();
  });

  it('names the channel while checking', () => {
    expect(describePhase('loader', { kind: 'checking' })).toBe('Checking for a new Game loader…');
    expect(describePhase('cli', { kind: 'checking' })).toBe('Checking for a new CLI…');
  });

  it('shows bytes and percent when the total is known', () => {
    expect(
      describePhase('loader', { kind: 'downloading', received: 1048576, total: 4194304 }),
    ).toBe('Downloading Game loader - 1.0 MB / 4.0 MB (25%)');
  });

  it('shows bytes only when the total is unknown, never 0%', () => {
    expect(describePhase('cli', { kind: 'downloading', received: 2048, total: 0 })).toBe(
      'Downloading CLI - 2.0 KB',
    );
  });

  it('confirms an install with the version and what to do next', () => {
    expect(describePhase('loader', { kind: 'installed', version: 12 })).toBe(
      'Game loader v12 installed - restart Ravenswatch to pick it up.',
    );
    expect(describePhase('cli', { kind: 'installed', version: 7 })).toBe(
      'CLI v7 downloaded - restart the app to use it.',
    );
    expect(describePhase('cli', { kind: 'installed', version: null })).toBe(
      'CLI downloaded - restart the app to use it.',
    );
  });

  it('carries the failure reason', () => {
    expect(describePhase('loader', { kind: 'failed', reason: 'timed out' })).toBe(
      'Game loader update failed: timed out',
    );
  });
});

describe('failureReason', () => {
  it('is null for a good answer', () => {
    expect(failureReason({ ok: true, status: 'up_to_date' })).toBeNull();
    expect(failureReason({ ok: true, status: 'updated' })).toBeNull();
  });
  it('reports an error status and a missing answer', () => {
    expect(failureReason({ ok: false, status: 'error', error: 'boom' })).toBe('boom');
    expect(failureReason({ ok: false, status: 'error' })).toBe('unknown error');
    expect(failureReason(null)).toBe('no answer from the CLI');
  });
  it('treats needs_app_update as a failure with its own message', () => {
    expect(failureReason({ ok: false, status: 'needs_app_update', error: 'update the app' })).toBe(
      'update the app',
    );
  });
});

describe('describeLoaderInstall / describeCliSource', () => {
  it('distinguishes release, dev and none', () => {
    expect(describeLoaderInstall('release', 9)).toBe('v9');
    expect(describeLoaderInstall('dev', 9)).toBe('dev');
    expect(describeLoaderInstall('none', null)).toBe('none');
    expect(describeLoaderInstall(undefined, null)).toBeNull();
    expect(describeLoaderInstall(undefined, 4)).toBe('v4');
  });
  it('says whether the CLI is embedded or from the channel', () => {
    expect(describeCliSource({ active: true, version: 12 })).toBe('v12 - update channel');
    expect(describeCliSource({ active: false, version: 11 })).toBe('v11 - embedded');
  });
});

describe('phase store', () => {
  it('notifies subscribers and clears a loader install confirmation', () => {
    const seen: string[] = [];
    const off = subscribeChannelPhases(() => seen.push(getChannelPhases().loader.kind));
    setChannelPhase('loader', { kind: 'installed', version: 3 });
    expect(getChannelPhases().loader.kind).toBe('installed');
    vi.advanceTimersByTime(INSTALLED_VISIBLE_MS);
    expect(getChannelPhases().loader.kind).toBe('idle');
    expect(seen).toEqual(['installed', 'idle']);
    off();
  });

  it('keeps a staged CLI ready for an app restart', () => {
    setChannelPhase('cli', { kind: 'installed', version: 8 });
    vi.advanceTimersByTime(INSTALLED_VISIBLE_MS * 10);
    expect(getChannelPhases().cli).toEqual({ kind: 'installed', version: 8 });
    expect(getPendingCliUpdate()).toEqual({ kind: 'installed', version: 8 });
  });

  it('preserves the restart offer while a later background check runs or fails', () => {
    setChannelPhase('cli', { kind: 'installed', version: 8 });
    setChannelPhase('cli', { kind: 'checking' });
    setChannelPhase('cli', { kind: 'failed', reason: 'offline' });
    setChannelPhase('cli', { kind: 'idle' });
    expect(getPendingCliUpdate()).toEqual({ kind: 'installed', version: 8 });
  });

  it('only offers a CLI update after one is staged and resets on a new session', () => {
    setChannelPhase('loader', { kind: 'installed', version: 61 });
    setChannelPhase('cli', { kind: 'failed', reason: 'offline' });
    expect(getPendingCliUpdate()).toBeNull();
    setChannelPhase('cli', { kind: 'installed', version: 8 });
    resetChannelPhases();
    expect(getPendingCliUpdate()).toBeNull();
  });

  it('keeps a failure until dismissed and tracks channels independently', () => {
    setChannelPhase('loader', { kind: 'failed', reason: 'x' });
    setChannelPhase('cli', { kind: 'checking' });
    vi.advanceTimersByTime(INSTALLED_VISIBLE_MS * 2);
    expect(getChannelPhases().loader.kind).toBe('failed');
    expect(getChannelPhases().cli.kind).toBe('checking');
  });
});

describe('cliPendingVersion', () => {
  it('reports a staged build, whether new or from an earlier check', () => {
    expect(cliPendingVersion({ status: 'staged', installedVersion: 9 }, 8)).toBe(9);
    expect(cliPendingVersion({ status: 'up_to_date', installedVersion: 9 }, 8)).toBe(9);
  });
  it('is null when nothing is waiting or the check failed', () => {
    expect(cliPendingVersion({ status: 'up_to_date', installedVersion: 8 }, 8)).toBeNull();
    expect(cliPendingVersion({ status: 'error', installedVersion: 9 }, 8)).toBeNull();
    expect(cliPendingVersion({ status: 'not_published' }, 8)).toBeNull();
  });
});
