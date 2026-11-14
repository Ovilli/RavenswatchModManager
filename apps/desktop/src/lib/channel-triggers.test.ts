import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { resetChannelPhases } from './channel-status';
import {
  DEBOUNCE_MS,
  PRELAUNCH_CHECK_MS,
  type TriggerDeps,
  checkChannels,
  resetChannelTriggers,
} from './channel-triggers';
import { resetSessionCache } from './session-cache';

let clock = 0;
function deps(over: Partial<TriggerDeps> = {}): TriggerDeps & {
  loader: ReturnType<typeof vi.fn>;
  cli: ReturnType<typeof vi.fn>;
  timedOut: ReturnType<typeof vi.fn>;
} {
  return {
    now: () => clock,
    loader: vi.fn(async () => ({ ok: true, status: 'up_to_date' as const })),
    cli: vi.fn(async () => null),
    downloading: () => false,
    timedOut: vi.fn(),
    ...over,
  } as never;
}

beforeEach(() => {
  vi.useFakeTimers();
  clock = 1_000_000;
  resetChannelTriggers();
  resetChannelPhases();
  resetSessionCache();
});
afterEach(() => {
  vi.useRealTimers();
});

describe('start / focus checks', () => {
  it('runs both channels and returns the loader result', async () => {
    const d = deps();
    const r = await checkChannels('start', d);
    expect(d.loader).toHaveBeenCalledTimes(1);
    expect(d.cli).toHaveBeenCalledTimes(1);
    expect(r.loader?.status).toBe('up_to_date');
  });

  it('skips a focus check within 60 s of the last one, and runs it after', async () => {
    const d = deps();
    await checkChannels('start', d);
    clock += DEBOUNCE_MS - 1;
    await checkChannels('focus', d);
    expect(d.loader).toHaveBeenCalledTimes(1);
    clock += 2;
    await checkChannels('focus', d);
    expect(d.loader).toHaveBeenCalledTimes(2);
  });

  it('joins a check that is still running instead of starting another', async () => {
    let release: () => void = () => {};
    const d = deps({
      loader: vi.fn(
        () =>
          new Promise((resolve) => {
            release = () => resolve({ ok: true, status: 'up_to_date' });
          }),
      ) as never,
    });
    const a = checkChannels('start', d);
    const b = checkChannels('focus', d);
    release();
    await Promise.all([a, b]);
    expect(d.loader).toHaveBeenCalledTimes(1);
  });

  it('survives a failing channel', async () => {
    const d = deps({ cli: vi.fn(async () => Promise.reject(new Error('x'))) as never });
    await expect(checkChannels('start', d)).resolves.toBeDefined();
  });
});

describe('pre-launch check', () => {
  it('always runs, even right after another check', async () => {
    const d = deps();
    await checkChannels('start', d);
    await checkChannels('prelaunch', d);
    expect(d.loader).toHaveBeenCalledTimes(2);
  });

  it('gives up after the cap, reports it, and lets the launch go ahead', async () => {
    const d = deps({ loader: vi.fn(() => new Promise(() => {})) as never });
    const p = checkChannels('prelaunch', d);
    await vi.advanceTimersByTimeAsync(PRELAUNCH_CHECK_MS);
    await p;
    expect(d.timedOut).toHaveBeenCalledWith(3);
  });

  it('waits longer once a download is under way', async () => {
    let release: () => void = () => {};
    const d = deps({
      loader: vi.fn(
        () =>
          new Promise((resolve) => {
            release = () => resolve({ ok: true, status: 'updated' });
          }),
      ) as never,
      downloading: () => true,
    });
    const p = checkChannels('prelaunch', d);
    await vi.advanceTimersByTimeAsync(PRELAUNCH_CHECK_MS + 10_000);
    expect(d.timedOut).not.toHaveBeenCalled();
    release();
    const r = await p;
    expect(r.loader?.status).toBe('updated');
  });
});
