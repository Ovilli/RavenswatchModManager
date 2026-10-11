/**
 * Overlay windows — one per mod that declares one.
 *
 * An overlay is a MOD capability, not a client feature: a mod describes the
 * HUD in its manifest `[overlay]` block and publishes rows at runtime, and the
 * client draws whatever it is handed. So nothing here knows about any
 * particular mod; windows are keyed by mod id.
 *
 * Each window is a frameless, always-on-top webview loading this same bundle
 * with `?window=overlay&mod=<id>` — a query parameter rather than a route
 * because the packaged app serves static files and a deep path like /overlay
 * has no SPA fallback to land on.
 */
import { WebviewWindow, getAllWebviewWindows } from '@tauri-apps/api/webviewWindow';
import { LogicalSize, PhysicalPosition, type Window, currentMonitor } from '@tauri-apps/api/window';
import { getPlatform } from './platform';

/** Window label for a mod's overlay. Must match the `overlay-*` capability. */
export function overlayLabel(modId: string): string {
  // Tauri labels allow a restricted character set; mod ids are slugs, but a
  // stray character would fail window creation with a cryptic error.
  return `overlay-${modId.replace(/[^a-zA-Z0-9\-_]/g, '_')}`;
}

/** Whether overlay windows are see-through on this platform (see openOverlay). */
export function overlayTransparent(): boolean {
  return getPlatform() !== 'linux';
}

function overlayUrl(modId: string): string {
  return `index.html?window=overlay&mod=${encodeURIComponent(modId)}`;
}

/** Remembered per mod, so each overlay reopens where it was left. */
function positionKey(modId: string): string {
  return `rsmm.overlay.position.${modId}`;
}

/** The size a fresh overlay opens at. */
export const DEFAULT_OVERLAY_SIZE = { width: 420, height: 196 } as const;

/**
 * Largest saved size we will restore. A HUD bigger than this is not a HUD —
 * it is a window that got maximized (a double-click on the title bar did it)
 * and then saved at screen size, which reopened full-screen forever with no
 * way back. Such a record is ignored, so the next open heals by itself.
 */
export const MAX_RESTORED_SIZE = { width: 900, height: 700 } as const;

/** Whether a saved size is one a HUD could plausibly have. Pure, for tests. */
export function plausibleOverlaySize(width: number, height: number): boolean {
  return (
    width >= 120 &&
    height >= 40 &&
    width <= MAX_RESTORED_SIZE.width &&
    height <= MAX_RESTORED_SIZE.height
  );
}

interface StoredPosition {
  x: number;
  y: number;
  width: number;
  height: number;
}

function readPosition(modId: string): StoredPosition | null {
  try {
    const raw = localStorage.getItem(positionKey(modId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredPosition>;
    if (
      typeof parsed.x !== 'number' ||
      typeof parsed.y !== 'number' ||
      typeof parsed.width !== 'number' ||
      typeof parsed.height !== 'number' ||
      !plausibleOverlaySize(parsed.width, parsed.height)
    ) {
      return null;
    }
    return parsed as StoredPosition;
  } catch {
    return null;
  }
}

export function savePosition(modId: string, pos: StoredPosition): void {
  try {
    localStorage.setItem(positionKey(modId), JSON.stringify(pos));
  } catch {
    // A full or disabled localStorage is not a reason to fail a drag.
  }
}

/** Forget a saved position — the fix when a window opens off-screen. */
export function resetPosition(modId: string): void {
  try {
    localStorage.removeItem(positionKey(modId));
  } catch {
    // ignore
  }
}

/**
 * Put an overlay window back to a fresh state: not maximized, default size,
 * centred on its current monitor, saved position forgotten. Called from the
 * overlay's own reset button, so it works even when the window is huge.
 */
export async function resetOverlayWindow(modId: string, win: Window): Promise<void> {
  resetPosition(modId);
  try {
    if (await win.isMaximized()) await win.unmaximize();
  } catch {
    // keep going: the size and position below are the part that matters
  }
  await win.setSize(new LogicalSize(DEFAULT_OVERLAY_SIZE.width, DEFAULT_OVERLAY_SIZE.height));
  try {
    // The monitor of the window CALLING this — the overlay resets itself.
    const monitor = await currentMonitor();
    if (monitor) {
      const scale = monitor.scaleFactor;
      const w = DEFAULT_OVERLAY_SIZE.width * scale;
      const h = DEFAULT_OVERLAY_SIZE.height * scale;
      await win.setPosition(
        new PhysicalPosition(
          Math.round(monitor.position.x + (monitor.size.width - w) / 2),
          Math.round(monitor.position.y + (monitor.size.height - h) / 2),
        ),
      );
    }
  } catch {
    // An unknown monitor leaves it where it is, which is still reachable.
  }
}

export async function findOverlay(modId: string): Promise<WebviewWindow | null> {
  try {
    const label = overlayLabel(modId);
    const windows = await getAllWebviewWindows();
    return windows.find((w) => w.label === label) ?? null;
  } catch {
    return null;
  }
}

export async function isOverlayOpen(modId: string): Promise<boolean> {
  return (await findOverlay(modId)) !== null;
}

/** Mod ids whose overlay window is currently open. */
export async function openOverlayMods(): Promise<string[]> {
  try {
    const windows = await getAllWebviewWindows();
    return windows
      .map((w) => w.label)
      .filter((l) => l.startsWith('overlay-'))
      .map((l) => l.slice('overlay-'.length));
  } catch {
    return [];
  }
}

/**
 * The declaration for one mod, or null when that mod ships no overlay.
 *
 * Pure on purpose: every place that offers an "open the overlay" control has to
 * decide whether the control exists at all, and that decision must be identical
 * everywhere (a button in the library that a mod cannot honour is worse than no
 * button).
 */
export function overlayFor<T extends { modId: string }>(
  records: readonly T[] | null | undefined,
  modId: string,
): T | null {
  return records?.find((r) => r.modId === modId) ?? null;
}

export async function openOverlay(modId: string): Promise<void> {
  const existing = await findOverlay(modId);
  if (existing) {
    await existing.setFocus();
    return;
  }
  const pos = readPosition(modId);
  const overlay = new WebviewWindow(overlayLabel(modId), {
    url: overlayUrl(modId),
    title: `RSMM — ${modId}`,
    width: pos?.width ?? DEFAULT_OVERLAY_SIZE.width,
    height: pos?.height ?? DEFAULT_OVERLAY_SIZE.height,
    x: pos?.x,
    y: pos?.y,
    resizable: true,
    // A HUD is never meant to fill the screen. Maximizing is how one got
    // stuck full-screen (see MAX_RESTORED_SIZE).
    maximizable: false,
    decorations: false,
    // Not on Linux: a transparent WebKitGTK window on X11 is not redrawn after
    // a content update until input forces it, so the HUD went invisible and
    // came back on a click (2026-10-02). Opaque there; the card paints the
    // same, only its corners lose the see-through.
    transparent: overlayTransparent(),
    alwaysOnTop: true,
    // Keep it out of the taskbar/alt-tab list: it is a HUD, and having it
    // steal a tab stop while you are playing is worse than useless.
    skipTaskbar: true,
    shadow: false,
    focus: false,
  });
  await new Promise<void>((resolve, reject) => {
    overlay.once('tauri://created', () => resolve());
    overlay.once('tauri://error', (e) => reject(new Error(String(e.payload))));
  });
}

export async function closeOverlay(modId: string): Promise<void> {
  const existing = await findOverlay(modId);
  if (existing) await existing.close();
}

/** Close every overlay window — used on the app's quit path. */
export async function closeAllOverlays(): Promise<void> {
  try {
    const windows = await getAllWebviewWindows();
    await Promise.allSettled(
      windows.filter((w) => w.label.startsWith('overlay-')).map((w) => w.close()),
    );
  } catch {
    // best effort; quitting must not depend on it
  }
}

export async function toggleOverlay(modId: string): Promise<boolean> {
  if (await isOverlayOpen(modId)) {
    await closeOverlay(modId);
    return false;
  }
  await openOverlay(modId);
  return true;
}
