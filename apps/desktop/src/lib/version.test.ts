import { describe, expect, it } from 'vitest';
import { compareVersions } from './version';

/** `compareVersions` returns an ordering, not a fixed number. */
const order = (a: string, b: string) => Math.sign(compareVersions(a, b));

describe('compareVersions', () => {
  it('treats omitted core segments as zero', () => {
    // The regression this file exists for: a mod versioned `1.0` against a
    // registry `1.0.0` used to read as outdated forever, so the update badge
    // never cleared and "Update all" reinstalled it on every pass.
    expect(order('1.0', '1.0.0')).toBe(0);
    expect(order('1', '1.0.0')).toBe(0);
    expect(order('2.1', '2.1.0.0')).toBe(0);
  });

  it('still orders a shorter core below a higher extension', () => {
    expect(order('1.0', '1.0.1')).toBe(-1);
    expect(order('1.0.1', '1.0')).toBe(1);
  });

  it('compares numerically, not lexically', () => {
    expect(order('1.10.0', '1.9.0')).toBe(1);
    expect(order('0.1.9', '0.1.11')).toBe(-1);
  });

  it('ranks a prerelease below the release it qualifies', () => {
    expect(order('1.0.0-rc1', '1.0.0')).toBe(-1);
    expect(order('1.0.0', '1.0.0-rc1')).toBe(1);
    expect(order('1.0-rc1', '1.0.0')).toBe(-1);
  });

  it('orders prereleases by field list, shorter first', () => {
    // Semver §11 — unlike the core, an omitted prerelease field is NOT a zero.
    expect(order('1.0.0-rc', '1.0.0-rc.1')).toBe(-1);
    expect(order('1.0.0-alpha', '1.0.0-beta')).toBe(-1);
  });

  it('ignores build metadata', () => {
    expect(order('1.0.0+build7', '1.0.0')).toBe(0);
    expect(order('1.0+deadbeef', '1.0.0+cafe')).toBe(0);
  });

  it('sorts equal versions as equal', () => {
    expect(order('0.1.12', '0.1.12')).toBe(0);
  });

  it('treats any non-alphanumeric run as a separator', () => {
    expect(order('1_2_3', '1.2.3')).toBe(0);
  });

  it('does NOT strip a leading v', () => {
    // Documenting, not endorsing: `parse` splits on non-alphanumerics, so the
    // `v` survives as an alpha segment and sorts below any numeric one.
    // Nothing compares tag-shaped strings today — registry and manifest
    // versions are both bare — so this is left alone rather than guessed at.
    expect(order('v1.2.3', '1.2.3')).toBe(-1);
  });
});
