import { describe, expect, it } from 'vitest';
import { isServable } from '../src/scan-gate.js';

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
