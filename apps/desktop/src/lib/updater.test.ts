import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const invoke = vi.fn();
const listen = vi.fn();

vi.mock('@tauri-apps/api/core', () => ({ invoke: (...a: unknown[]) => invoke(...a) }));
vi.mock('@tauri-apps/api/event', () => ({ listen: (...a: unknown[]) => listen(...a) }));

import { migrateToAppImage, relaunchMigrated } from './updater';

/** `inTauri()` is a window-global probe; the node test env has no window. */
function pretendTauri(on: boolean) {
  if (on) {
    (globalThis as { window?: unknown }).window = { __TAURI_INTERNALS__: {} };
  } else {
    (globalThis as { window?: unknown }).window = undefined;
  }
}

describe('migrateToAppImage', () => {
  beforeEach(() => {
    invoke.mockReset();
    listen.mockReset();
    pretendTauri(true);
  });
  afterEach(() => pretendTauri(false));

  it('reports download progress and stops listening when it finishes', async () => {
    const unlisten = vi.fn();
    let emit: ((e: { payload: { downloaded: number; total: number | null } }) => void) | undefined;
    listen.mockImplementation((_name, cb) => {
      emit = cb;
      return Promise.resolve(unlisten);
    });
    invoke.mockImplementation(async () => {
      emit?.({ payload: { downloaded: 512, total: 1024 } });
      return {
        path: '/home/u/Applications/x.AppImage',
        desktopEntry: null,
        version: '9.9.9',
        leftover: null,
      };
    });

    const seen: Array<[number, number | null]> = [];
    const result = await migrateToAppImage((d, t) => seen.push([d, t]));

    expect(invoke).toHaveBeenCalledWith('migrate_to_appimage');
    expect(seen).toEqual([[512, 1024]]);
    expect(result.version).toBe('9.9.9');
    expect(unlisten).toHaveBeenCalled();
  });

  it('stops listening when the migration fails', async () => {
    // A leaked listener would keep firing progress into a dead UI state after
    // the user has been sent back to the manual-download path.
    const unlisten = vi.fn();
    listen.mockResolvedValue(unlisten);
    invoke.mockRejectedValue(new Error('no write access'));

    await expect(migrateToAppImage(() => {})).rejects.toThrow('no write access');
    expect(unlisten).toHaveBeenCalled();
  });

  it('does not subscribe at all when no progress callback is given', async () => {
    invoke.mockResolvedValue({ path: '/x', desktopEntry: null, version: '1', leftover: null });
    await migrateToAppImage();
    expect(listen).not.toHaveBeenCalled();
  });

  it('refuses outside the desktop shell instead of invoking nothing', async () => {
    pretendTauri(false);
    await expect(migrateToAppImage()).rejects.toThrow(/desktop app/);
    expect(invoke).not.toHaveBeenCalled();
  });
});

describe('relaunchMigrated', () => {
  beforeEach(() => {
    invoke.mockReset();
  });
  afterEach(() => pretendTauri(false));

  it('asks Rust to queue the new copy', async () => {
    pretendTauri(true);
    invoke.mockResolvedValue(null);
    await relaunchMigrated();
    expect(invoke).toHaveBeenCalledWith('relaunch_migrated_appimage');
  });

  it('is a no-op in the web preview', async () => {
    pretendTauri(false);
    await relaunchMigrated();
    expect(invoke).not.toHaveBeenCalled();
  });
});
