import { describe, expect, it } from 'vitest';
import {
  DrainLock,
  RESET_SCAN_FIELDS,
  SERVABLE_STATUSES,
  canReplaceVersionBytes,
  isServable,
  storedBytesMatchDeclared,
} from '../src/scan-gate.js';

// Re-presigning a version points it at new bytes. A servable version must be
// immutable, and any replaceable one must lose its old verdict — otherwise new,
// never-scanned bytes are served under the previous 'clean'.
describe('version byte replacement', () => {
  it('refuses to replace a servable version', () => {
    for (const s of SERVABLE_STATUSES) expect(canReplaceVersionBytes(s)).toBe(false);
  });

  it('lets an unscanned, flagged or errored version be re-uploaded', () => {
    for (const s of ['queued', 'pending', 'flagged', 'error']) {
      expect(canReplaceVersionBytes(s)).toBe(true);
    }
  });

  it('resets the verdict to a non-servable state', () => {
    expect(isServable(RESET_SCAN_FIELDS.scanStatus)).toBe(false);
    expect(RESET_SCAN_FIELDS.scannedAt).toBeNull();
    expect(RESET_SCAN_FIELDS.scanStats).toBeNull();
  });
});

// A verdict must cover the bytes clients will accept. Clients install only what
// hashes to the declared sha256, so a scan of anything else — a same-length
// decoy PUT before the real payload — must never produce 'clean'.
describe('storedBytesMatchDeclared', () => {
  const a = 'a'.repeat(64);
  const b = 'b'.repeat(64);

  it('accepts the declared bytes', () => {
    expect(storedBytesMatchDeclared(a, a)).toBe(true);
    expect(storedBytesMatchDeclared(a.toUpperCase(), a)).toBe(true);
  });

  it('rejects a decoy whose hash is not the declared one', () => {
    expect(storedBytesMatchDeclared(b, a)).toBe(false);
  });
});

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
