import { describe, expect, it } from 'vitest';
import { isScrollable, wheelDeltaPx } from './smooth-scroll';

/** Height of the scroll container the deltas are measured against. */
const VIEWPORT = 720;

/**
 * The device heuristic is the whole safety case: take over a mouse notch,
 * never touch a trackpad. If this drifts, the one input device that already
 * felt right starts fighting an animation it does not need.
 */
describe('wheelDeltaPx', () => {
  it('takes over a mouse notch in pixel mode', () => {
    // WebKitGTK reports ~53-120px per click.
    expect(wheelDeltaPx({ deltaY: 53, deltaMode: 0 }, VIEWPORT)).toBe(53);
    expect(wheelDeltaPx({ deltaY: -120, deltaMode: 0 }, VIEWPORT)).toBe(-120);
  });

  it('leaves a trackpad glide to the browser', () => {
    for (const deltaY of [1, -3, 8, 39.5]) {
      expect(wheelDeltaPx({ deltaY, deltaMode: 0 }, VIEWPORT)).toBeNull();
    }
  });

  it('converts line and page deltas', () => {
    expect(wheelDeltaPx({ deltaY: 3, deltaMode: 1 }, VIEWPORT)).toBe(120);
    // Page mode is one CONTAINER viewport per step, not one window.
    expect(wheelDeltaPx({ deltaY: 1, deltaMode: 2 }, VIEWPORT)).toBe(VIEWPORT);
  });

  it('declines zoom and horizontal wheels', () => {
    expect(wheelDeltaPx({ deltaY: 100, deltaMode: 0, ctrlKey: true }, VIEWPORT)).toBeNull();
    expect(wheelDeltaPx({ deltaY: 100, deltaMode: 0, shiftKey: true }, VIEWPORT)).toBeNull();
  });

  it('declines a wheel that scrolls nothing', () => {
    expect(wheelDeltaPx({ deltaY: 0, deltaMode: 0 }, VIEWPORT)).toBeNull();
  });
});

/**
 * Delegation picks the container by computed overflow, so this is what decides
 * whether a wheel is taken over at all.
 */
describe('isScrollable', () => {
  it('accepts an overflowing auto/scroll box', () => {
    expect(isScrollable({ overflowY: 'auto', scrollHeight: 900, clientHeight: 400 })).toBe(true);
    expect(isScrollable({ overflowY: 'scroll', scrollHeight: 900, clientHeight: 400 })).toBe(true);
  });

  it('rejects a clipped box, which the user cannot scroll back by hand', () => {
    expect(isScrollable({ overflowY: 'hidden', scrollHeight: 900, clientHeight: 400 })).toBe(false);
    // The app shell is full of these: overflow-hidden flex boxes whose content
    // is taller than the box.
    expect(isScrollable({ overflowY: 'visible', scrollHeight: 900, clientHeight: 400 })).toBe(
      false,
    );
  });

  it('rejects a box with nothing to scroll', () => {
    expect(isScrollable({ overflowY: 'auto', scrollHeight: 400, clientHeight: 400 })).toBe(false);
  });
});
