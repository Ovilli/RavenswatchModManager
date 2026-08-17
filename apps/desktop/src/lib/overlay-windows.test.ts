import { beforeEach, describe, expect, it, vi } from 'vitest';

// The module reaches for Tauri's webview API at import time; the helpers under
// test do not, so a stub keeps this a pure unit test.
vi.mock('@tauri-apps/api/webviewWindow', () => ({
  WebviewWindow: class {},
  getAllWebviewWindows: async () => [],
}));

import { overlayFor, overlayLabel, resetPosition, savePosition } from './overlay-windows';

describe('overlayFor', () => {
  const records = [{ modId: 'damage-meter' }, { modId: 'run-timer' }];

  it('finds the declaration a mod ships', () => {
    expect(overlayFor(records, 'run-timer')).toEqual({ modId: 'run-timer' });
  });

  it('returns null for a mod with no overlay, so no button is offered', () => {
    expect(overlayFor(records, 'no-hud')).toBeNull();
  });

  it('tolerates a list that has not loaded (or failed to load)', () => {
    // Outside Tauri the CLI call throws and the query data is undefined; the
    // control must simply not render rather than crash the library page.
    expect(overlayFor(undefined, 'damage-meter')).toBeNull();
    expect(overlayFor(null, 'damage-meter')).toBeNull();
  });
});

describe('overlay window labels', () => {
  it('namespaces by mod id so several overlays can be open at once', () => {
    expect(overlayLabel('damage-meter')).toBe('overlay-damage-meter');
    expect(overlayLabel('run_timer')).toBe('overlay-run_timer');
  });

  it('sanitises a mod id that would be an invalid window label', () => {
    // Window creation fails with a cryptic error on an unexpected character;
    // mod ids are slugs, but the client must not rely on that.
    expect(overlayLabel('weird/id.v2')).toBe('overlay-weird_id_v2');
  });
});

describe('overlay position memory', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('is stored per mod, so one overlay cannot move another', () => {
    savePosition('damage-meter', { x: 10, y: 20, width: 300, height: 200 });
    savePosition('run-timer', { x: 900, y: 40, width: 240, height: 120 });
    expect(JSON.parse(localStorage.getItem('rsmm.overlay.position.damage-meter') ?? '{}')).toEqual({
      x: 10,
      y: 20,
      width: 300,
      height: 200,
    });
    expect(JSON.parse(localStorage.getItem('rsmm.overlay.position.run-timer') ?? '{}').x).toBe(900);
  });

  it('reset clears only that mod — the fix for an off-screen window', () => {
    savePosition('a', { x: 1, y: 2, width: 3, height: 4 });
    savePosition('b', { x: 5, y: 6, width: 7, height: 8 });
    resetPosition('a');
    expect(localStorage.getItem('rsmm.overlay.position.a')).toBeNull();
    expect(localStorage.getItem('rsmm.overlay.position.b')).not.toBeNull();
  });

  it('survives a storage failure instead of breaking the drag', () => {
    const original = localStorage.setItem;
    localStorage.setItem = () => {
      throw new Error('quota exceeded');
    };
    expect(() => savePosition('a', { x: 1, y: 2, width: 3, height: 4 })).not.toThrow();
    localStorage.setItem = original;
  });
});
