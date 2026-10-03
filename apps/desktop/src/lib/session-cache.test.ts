import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  cachedFor,
  noteGameStateChanged,
  oncePerLaunch,
  prime,
  resetSessionCache,
} from './session-cache';

beforeEach(() => {
  resetSessionCache();
  vi.useRealTimers();
});

describe('oncePerLaunch', () => {
  it('runs once and shares the result between callers', async () => {
    const run = vi.fn(async () => 'a');
    const [x, y] = await Promise.all([oncePerLaunch('k', run), oncePerLaunch('k', run)]);
    expect([x, y]).toEqual(['a', 'a']);
    await oncePerLaunch('k', run);
    expect(run).toHaveBeenCalledTimes(1);
  });

  it('runs again when asked for a fresh one', async () => {
    const run = vi.fn(async () => 'a');
    await oncePerLaunch('k', run);
    await oncePerLaunch('k', run, true);
    expect(run).toHaveBeenCalledTimes(2);
  });

  it('does not remember a failure', async () => {
    const run = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce('ok');
    await expect(oncePerLaunch('k', run)).rejects.toThrow('offline');
    await expect(oncePerLaunch('k', run)).resolves.toBe('ok');
  });
});

describe('cachedFor', () => {
  it('reuses a result inside its lifetime and refetches after it', async () => {
    vi.useFakeTimers();
    const run = vi.fn(async () => 1);
    await cachedFor('k', 1000, run);
    await cachedFor('k', 1000, run);
    expect(run).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1001);
    await cachedFor('k', 1000, run);
    expect(run).toHaveBeenCalledTimes(2);
  });

  it('forgets everything the moment something writes to the game', async () => {
    const run = vi.fn(async () => 1);
    await cachedFor('k', 60_000, run);
    noteGameStateChanged();
    await cachedFor('k', 60_000, run);
    expect(run).toHaveBeenCalledTimes(2);
  });

  it('keys are independent, and `fresh` bypasses the cache', async () => {
    const a = vi.fn(async () => 'a');
    const b = vi.fn(async () => 'b');
    await cachedFor('a', 60_000, a);
    await cachedFor('b', 60_000, b);
    await cachedFor('a', 60_000, a, true);
    expect(a).toHaveBeenCalledTimes(2);
    expect(b).toHaveBeenCalledTimes(1);
  });

  it('does not remember a failure', async () => {
    const run = vi.fn().mockRejectedValueOnce(new Error('x')).mockResolvedValueOnce('ok');
    await expect(cachedFor('k', 60_000, run)).rejects.toThrow('x');
    await expect(cachedFor('k', 60_000, run)).resolves.toBe('ok');
  });

  it('prime() seeds a result without running anything', async () => {
    const run = vi.fn(async () => 'live');
    prime('k', 'seeded');
    await expect(cachedFor('k', 60_000, run)).resolves.toBe('seeded');
    expect(run).not.toHaveBeenCalled();
  });
});
