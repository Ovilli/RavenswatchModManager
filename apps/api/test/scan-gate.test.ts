import { describe, expect, it } from 'vitest';
import { DrainLock, isServable } from '../src/scan-gate.js';

// The fail-closed download gate is security-critical: a regression that lets an
// un-scanned or flagged version through is a malware-distribution hole. These
// pin the exact allow-list so a future edit to the enum can't widen it silently.
describe('isServable (fail-closed scan gate)', () => {
  it('serves only clean and skipped', () => {
    expect(isServable('clean')).toBe(true);
    expect(isServable('skipped')).toBe(true);
  });

  it('withholds every non-serve state', () => {
    for (const s of ['queued', 'pending', 'flagged', 'error']) {
      expect(isServable(s)).toBe(false);
    }
  });

  it('withholds unknown / null / undefined (fail closed)', () => {
    expect(isServable(null)).toBe(false);
    expect(isServable(undefined)).toBe(false);
    expect(isServable('')).toBe(false);
    expect(isServable('anything-new')).toBe(false);
  });
});

describe('DrainLock (scan drain single-flight with a lease)', () => {
  it('lets one drain in at a time', () => {
    const lock = new DrainLock(120_000);
    expect(lock.tryAcquire(1_000)).toBe(true);
    expect(lock.tryAcquire(2_000)).toBe(false);
    lock.release(1_000);
    expect(lock.tryAcquire(3_000)).toBe(true);
  });

  it('expires a hold that was never released — a frozen detached drain', () => {
    const lock = new DrainLock(120_000);
    expect(lock.tryAcquire(0)).toBe(true);
    expect(lock.tryAcquire(119_999)).toBe(false);
    expect(lock.tryAcquire(120_000)).toBe(true);
  });

  it('a forced drain (the awaited cron) always runs', () => {
    const lock = new DrainLock(120_000);
    expect(lock.tryAcquire(0)).toBe(true);
    expect(lock.tryAcquire(10, true)).toBe(true);
  });

  it('a stale drain finishing late does not release the newer hold', () => {
    const lock = new DrainLock(120_000);
    lock.tryAcquire(0);
    lock.tryAcquire(200_000); // the old hold expired; a new drain took over
    lock.release(0); // the frozen one finally settles
    expect(lock.tryAcquire(200_001)).toBe(false);
  });
});
