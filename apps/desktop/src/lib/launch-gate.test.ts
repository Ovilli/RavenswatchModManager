import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// The CLI is reached through the Rust probe: the sidecar spawn is made to fail so
// `execute()` falls through to `probe_rsmm`, which these tests answer.
const calls: string[][] = [];
let applyJson: Record<string, unknown> = { ok: true, code: 0, stdout: '', stderr: '' };
let onProbe: (args: string[]) => Promise<void> = async () => {};

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(async (cmd: string, payload?: { args: string[] }) => {
    if (cmd !== 'probe_rsmm' || !payload) throw new Error(`no ${cmd}`);
    calls.push(payload.args);
    await onProbe(payload.args);
    const body = payload.args.includes('apply')
      ? applyJson
      : { ok: true, code: 0, stdout: '', stderr: '' };
    return { code: 0, stdout: JSON.stringify(body), stderr: '' };
  }),
}));
vi.mock('@tauri-apps/plugin-shell', () => ({
  Command: {
    sidecar: vi.fn(() => {
      throw new Error('no sidecar');
    }),
    create: vi.fn(() => {
      throw new Error('no sidecar');
    }),
  },
}));

import {
  getChannelPhases,
  getLaunchActive,
  getLaunchHold,
  resetChannelPhases,
  setChannelPhase,
  trackLoaderUpdate,
} from './channel-status';
import { afterLaunch, beforeLaunch, resetChannelTriggers } from './channel-triggers';
import { getNotedLoaderResult, noteLoaderResult, subscribeLoaderResult } from './loader-status';
import { runModded, runVanilla, setLaunchGate } from './rsmm';
import { resetSessionCache } from './session-cache';
import { getSkippedMods, setSkippedMods } from './skipped-mods';

const never = () => new Promise<never>(() => {});

function mkDeps(over: Record<string, unknown> = {}) {
  return {
    now: () => 1_000_000,
    loader: vi.fn(async () => ({ ok: true, status: 'up_to_date' })),
    cli: vi.fn(async () => null),
    downloading: () => false,
    timedOut: vi.fn(),
    ...over,
  } as never;
}

beforeEach(() => {
  calls.length = 0;
  applyJson = { ok: true, code: 0, stdout: '', stderr: '' };
  onProbe = async () => {};
  vi.useFakeTimers();
  resetChannelTriggers();
  resetChannelPhases();
  resetSessionCache();
  setSkippedMods([]);
  setLaunchGate({ before: (k) => beforeLaunch(k, mkDeps()), after: afterLaunch });
});
afterEach(() => {
  setLaunchGate(null);
  vi.useRealTimers();
});

describe('launch vs loader write', () => {
  it('a vanilla launch waits for an in-flight loader update, then runs', async () => {
    let finish: () => void = () => {};
    const { checkChannels } = await import('./channel-triggers');
    const d = mkDeps({
      loader: vi.fn(
        () =>
          new Promise((r) => {
            finish = () => r({ ok: true, status: 'updated' });
          }),
      ),
    });
    const check = checkChannels('start', d);
    const launch = runVanilla();
    await vi.advanceTimersByTimeAsync(5000);
    expect(calls.some((a) => a.includes('--vanilla'))).toBe(false);
    expect(getLaunchHold()).toBe('vanilla');
    finish();
    await check;
    await launch;
    expect(calls.some((a) => a.includes('--vanilla'))).toBe(true);
    expect(getLaunchHold()).toBeNull();
  });

  it('start and focus checks start nothing while a launch is in progress', async () => {
    const { checkChannels } = await import('./channel-triggers');
    let release: () => void = () => {};
    onProbe = (args) =>
      args.includes('--vanilla')
        ? new Promise((r) => {
            release = r;
          })
        : Promise.resolve();
    const d = mkDeps();
    const launch = runVanilla();
    await vi.advanceTimersByTimeAsync(10);
    await checkChannels('focus', d);
    await checkChannels('start', d);
    expect((d as { loader: ReturnType<typeof vi.fn> }).loader).not.toHaveBeenCalled();
    release();
    await launch;
    await checkChannels('focus', d);
    expect((d as { loader: ReturnType<typeof vi.fn> }).loader).toHaveBeenCalledTimes(1);
  });
});

describe('Settings loader update vs launch', () => {
  it('a launch started during a Settings update waits on it, vanilla and modded', async () => {
    let release: () => void = () => {};
    onProbe = (args) =>
      args.includes('update-loader')
        ? new Promise((r) => {
            release = r;
          })
        : Promise.resolve();
    const update = trackLoaderUpdate();
    await vi.advanceTimersByTimeAsync(10);
    const vanilla = runVanilla();
    await vi.advanceTimersByTimeAsync(10);
    expect(calls.some((a) => a.includes('--vanilla'))).toBe(false);
    release();
    await update;
    await vanilla;
    expect(calls.some((a) => a.includes('--vanilla'))).toBe(true);

    onProbe = (args) =>
      args.includes('update-loader')
        ? new Promise((r) => {
            release = r;
          })
        : Promise.resolve();
    const again = trackLoaderUpdate();
    await vi.advanceTimersByTimeAsync(10);
    const before = beforeLaunch('modded', mkDeps());
    const loaderCalls = calls.filter((a) => a.includes('update-loader')).length;
    await vi.advanceTimersByTimeAsync(100);
    // Joined the running update rather than starting a second one.
    expect(calls.filter((a) => a.includes('update-loader')).length).toBe(loaderCalls);
    release();
    await again;
    await before;
    afterLaunch();
  });

  it('reports a launch as active so the Settings button can disable itself', async () => {
    expect(getLaunchActive()).toBe(false);
    const p = beforeLaunch('vanilla', mkDeps());
    await p;
    expect(getLaunchActive()).toBe(true);
    afterLaunch();
    expect(getLaunchActive()).toBe(false);
  });
});

describe('pre-launch waits on the loader only', () => {
  it('a never-finishing CLI check does not hold a modded launch', async () => {
    const d = mkDeps({ cli: vi.fn(never) });
    const p = beforeLaunch('modded', d);
    await vi.advanceTimersByTimeAsync(10);
    await p;
    expect((d as { cli: ReturnType<typeof vi.fn> }).cli).toHaveBeenCalledTimes(1);
    afterLaunch();
  });

  it('a CLI download phase does not extend the cap', async () => {
    setChannelPhase('cli', { kind: 'downloading', received: 1, total: 2 });
    const d = mkDeps({
      loader: vi.fn(never),
      downloading: () => getChannelPhases().loader.kind === 'downloading',
    });
    const p = beforeLaunch('modded', d);
    await vi.advanceTimersByTimeAsync(3000);
    await p;
    expect((d as { timedOut: ReturnType<typeof vi.fn> }).timedOut).toHaveBeenCalledWith(3);
    afterLaunch();
  });
});

describe('footer refresh', () => {
  it('notifies subscribers when a loader result lands', () => {
    const seen: unknown[] = [];
    const off = subscribeLoaderResult(() => seen.push(getNotedLoaderResult()?.installedVersion));
    noteLoaderResult({ ok: true, status: 'updated', installedVersion: 12 } as never);
    off();
    noteLoaderResult({ ok: true, status: 'updated', installedVersion: 13 } as never);
    expect(seen).toEqual([12]);
  });
});

describe('skipped mods at launch', () => {
  const skipped = [
    {
      id: 'blood-wolf-pam',
      reason: 'needs RSMM CLI v32 or newer, this is v31 - update RSMM',
      needs: { cli: 32 },
    },
  ];

  it('surfaces the apply result and still launches', async () => {
    applyJson = { ok: true, code: 0, stdout: '', stderr: '', skipped };
    const r = await runModded();
    expect(r?.ok).toBe(true);
    expect(calls.some((a) => a.includes('run'))).toBe(true);
    expect(getSkippedMods()).toEqual(skipped);
  });

  it('clears the notice on a launch with nothing skipped, and tolerates old CLIs', async () => {
    setSkippedMods(skipped);
    await runModded();
    expect(getSkippedMods()).toEqual([]);
  });
});
