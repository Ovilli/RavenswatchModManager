import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const destroy = vi.fn(async () => {});
const processExit = vi.fn(async (_code: number) => {});
const closeOverlay = vi.fn(async () => {});
const killLiveChildren = vi.fn(async () => {});
const order: string[] = [];

vi.mock('@tauri-apps/api/window', () => ({
  getCurrentWindow: () => ({
    destroy: async () => {
      order.push('destroy');
      return destroy();
    },
  }),
}));
vi.mock('@tauri-apps/plugin-process', () => ({
  exit: (code: number) => {
    order.push('force-exit');
    return processExit(code);
  },
}));
vi.mock('./overlay-windows', () => ({
  closeAllOverlays: () => {
    order.push('close-overlays');
    return closeOverlay();
  },
}));
vi.mock('./rsmm', () => ({
  killLiveChildren: () => {
    order.push('kill-children');
    return killLiveChildren();
  },
}));

import { quitApp } from './quit';

describe('quitApp', () => {
  beforeEach(() => {
    order.length = 0;
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('kills sidecars and closes the overlay before destroying the window', async () => {
    await quitApp();
    // Order matters: a child killed after the process is gone is an orphan,
    // and an overlay left open keeps the process alive with no visible UI.
    expect(order).toEqual(['kill-children', 'close-overlays', 'destroy']);
    expect(processExit).not.toHaveBeenCalled();
  });

  it('does not hard-exit while the graceful path is still within its budget', async () => {
    await quitApp();
    vi.advanceTimersByTime(2000);
    expect(processExit).not.toHaveBeenCalled();
  });

  it('falls back to a hard exit if the window never goes away', async () => {
    await quitApp();
    // The window did not actually die (a wedged webview): the user asked to
    // quit and must end up quit.
    vi.advanceTimersByTime(3000);
    expect(processExit).toHaveBeenCalledWith(0);
  });

  it('hard-exits immediately when destroy() throws', async () => {
    destroy.mockRejectedValueOnce(new Error('no window'));
    await quitApp();
    expect(processExit).toHaveBeenCalledWith(0);
  });

  it('still quits when a child refuses to die', async () => {
    killLiveChildren.mockRejectedValueOnce(new Error('access denied'));
    await quitApp();
    expect(order).toContain('destroy');
  });
});
