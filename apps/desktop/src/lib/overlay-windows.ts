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
import { getAllWebviewWindows, WebviewWindow } from '@tauri-apps/api/webviewWindow';

/** Window label for a mod's overlay. Must match the `overlay-*` capability. */
export function overlayLabel(modId: string): string {
  // Tauri labels allow a restricted character set; mod ids are slugs, but a
  // stray character would fail window creation with a cryptic error.
  return `overlay-${modId.replace(/[^a-zA-Z0-9\-_]/g, '_')}`;
}

function overlayUrl(modId: string): string {
  return `index.html?window=overlay&mod=${encodeURIComponent(modId)}`;
}

/** Remembered per mod, so each overlay reopens where it was left. */
function positionKey(modId: string): string {
  return `rsmm.overlay.position.${modId}`;
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
      typeof parsed.height !== 'number'
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
    width: pos?.width ?? 420,
    height: pos?.height ?? 196,
    x: pos?.x,
    y: pos?.y,
    resizable: true,
    decorations: false,
    transparent: true,
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
