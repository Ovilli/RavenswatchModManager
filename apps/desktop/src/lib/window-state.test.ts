import { describe, expect, it } from 'vitest';
import { type MonitorBox, type WindowRect, clampToMonitor } from './window-state';

const MONITOR: MonitorBox = { x: 0, y: 0, width: 1920, height: 1080 };
const rect = (r: Partial<WindowRect> = {}): WindowRect => ({
  x: 100,
  y: 100,
  width: 1280,
  height: 800,
  ...r,
});

describe('clampToMonitor', () => {
  it('keeps a rect that fits', () => {
    expect(clampToMonitor(rect(), MONITOR)).toEqual({
      size: { width: 1280, height: 800 },
      position: { x: 100, y: 100 },
    });
  });

  it('drops a position on a monitor that is no longer there', () => {
    // The reason this function exists: save a rect on a second display,
    // unplug it, relaunch. The window would open where nothing can reach it —
    // including its own title bar, so it cannot be dragged back.
    const offscreen = clampToMonitor(rect({ x: 2600, y: 300 }), MONITOR);
    expect(offscreen?.position).toBeNull();
    // The size is still worth restoring.
    expect(offscreen?.size).toEqual({ width: 1280, height: 800 });
  });

  it('drops a position whose title bar is above the monitor', () => {
    expect(clampToMonitor(rect({ y: -40 }), MONITOR)?.position).toBeNull();
  });

  it('drops a position hanging off the bottom', () => {
    expect(clampToMonitor(rect({ y: 1040 }), MONITOR)?.position).toBeNull();
  });

  it('keeps a position that only slightly overhangs the right edge', () => {
    // Partly off-screen is normal and the user put it there; only far enough
    // out to be ungrabbable is a problem.
    expect(clampToMonitor(rect({ x: 1500 }), MONITOR)?.position).toEqual({ x: 1500, y: 100 });
  });

  it('shrinks a window larger than the monitor', () => {
    expect(clampToMonitor(rect({ width: 3000, height: 2000 }), MONITOR)?.size).toEqual({
      width: 1920,
      height: 1080,
    });
  });

  it('never restores below the configured minimum size', () => {
    expect(clampToMonitor(rect({ width: 200, height: 150 }), MONITOR)?.size).toEqual({
      width: 960,
      height: 600,
    });
  });

  it('honours a monitor that does not start at the origin', () => {
    const right: MonitorBox = { x: 1920, y: 0, width: 1920, height: 1080 };
    expect(clampToMonitor(rect({ x: 2000, y: 50 }), right)?.position).toEqual({ x: 2000, y: 50 });
    expect(clampToMonitor(rect({ x: 100, y: 50 }), right)?.position).toBeNull();
  });

  it('restores nothing when the monitor is unknown', () => {
    // Without knowing where the displays are, any saved position is a guess.
    expect(clampToMonitor(rect(), null)).toBeNull();
  });
});
