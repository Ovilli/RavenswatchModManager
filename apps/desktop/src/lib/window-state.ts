/**
 * Remember the main window's size and position across launches.
 *
 * `tauri.conf.json` hardcodes 1280x800 centred, so every launch threw away
 * whatever the user had arranged. The official `tauri-plugin-window-state`
 * would cover this, but its allow/deny lists take exact window labels and the
 * overlay windows are `overlay-<modId>` — created at runtime, one per mod, and
 * already persisting their own geometry in `lib/overlay-windows.ts`. Rather
 * than add a plugin that would need excluding from most of the windows it can
 * see, this reuses that same proven pattern for one more key.
 *
 * The pure part (`clampToMonitor`) is separated from the Tauri calls so the
 * off-screen logic — the one thing here that can strand a user with an
 * unreachable window — is testable in a suite with no webview and no jsdom.
 */
import {
  LogicalPosition,
  LogicalSize,
  currentMonitor,
  getCurrentWindow,
} from '@tauri-apps/api/window';

const KEY = 'rsmm.window.main';

/** Matches `minWidth`/`minHeight` in tauri.conf.json. */
const MIN_WIDTH = 960;
const MIN_HEIGHT = 600;

/** How much of the window must be on a monitor for the rect to be usable. */
const VISIBLE_MARGIN = 80;

export interface WindowRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface MonitorBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

function isRect(v: unknown): v is WindowRect {
  if (typeof v !== 'object' || v === null) return false;
  const r = v as Partial<WindowRect>;
  return (
    Number.isFinite(r.x) &&
    Number.isFinite(r.y) &&
    Number.isFinite(r.width) &&
    Number.isFinite(r.height)
  );
}

export function readRect(): WindowRect | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isRect(parsed) ? parsed : null;
  } catch {
    // A full, disabled or corrupted localStorage is not a reason to fail a
    // launch — the window just opens where the config says.
    return null;
  }
}

export function saveRect(rect: WindowRect): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(rect));
  } catch {
    // ignore
  }
}

/**
 * A rect that is actually reachable on `monitor`, or size-only when the saved
 * position is not.
 *
 * The failure this exists for: save a rect on a second monitor, unplug it,
 * relaunch — the window opens at coordinates no display covers and cannot be
 * dragged back, because the title bar is off-screen too. Restoring the size
 * and letting the config centre it is strictly better than an invisible
 * window. Size is clamped rather than dropped: a window larger than the
 * monitor is awkward, one whose controls are past the edge is unusable.
 *
 * `null` monitor (headless, or the query failed) means restore nothing —
 * without knowing where the displays are, any saved position is a guess.
 */
export function clampToMonitor(
  rect: WindowRect,
  monitor: MonitorBox | null,
): { size: { width: number; height: number }; position: { x: number; y: number } | null } | null {
  if (!monitor) return null;
  const width = Math.max(MIN_WIDTH, Math.min(rect.width, monitor.width));
  const height = Math.max(MIN_HEIGHT, Math.min(rect.height, monitor.height));

  // Enough of the window has to overlap the monitor to grab it by hand.
  const onScreen =
    rect.x + rect.width > monitor.x + VISIBLE_MARGIN &&
    rect.x < monitor.x + monitor.width - VISIBLE_MARGIN &&
    // The top edge specifically: that is where the drag region is, and a
    // window whose title bar is above the monitor cannot be moved back.
    rect.y >= monitor.y &&
    rect.y < monitor.y + monitor.height - VISIBLE_MARGIN;

  return { size: { width, height }, position: onScreen ? { x: rect.x, y: rect.y } : null };
}

/** Save at most this often while a drag or resize is in flight. */
const SAVE_DEBOUNCE_MS = 400;

/**
 * Restore the saved rect, then keep it up to date.
 *
 * Returns the detach function so a caller can hand it back from a `useEffect`.
 * Every step is best-effort: a window that will not report its geometry is a
 * window that opens at the default, not a launch failure.
 */
export function trackMainWindow(): () => void {
  let stopped = false;
  const unlisteners: (() => void)[] = [];
  let timer: ReturnType<typeof setTimeout> | null = null;

  void (async () => {
    const win = getCurrentWindow();

    try {
      const saved = readRect();
      if (saved) {
        const monitor = await currentMonitor();
        // `currentMonitor` reports PHYSICAL pixels; the rect is stored in
        // logical ones, so the box has to be divided by the scale factor or a
        // HiDPI display reads as twice its real size and nothing ever clamps.
        const scale = monitor?.scaleFactor ?? 1;
        const box: MonitorBox | null = monitor
          ? {
              x: monitor.position.x / scale,
              y: monitor.position.y / scale,
              width: monitor.size.width / scale,
              height: monitor.size.height / scale,
            }
          : null;
        const target = clampToMonitor(saved, box);
        if (target && !stopped) {
          await win.setSize(new LogicalSize(target.size.width, target.size.height));
          if (target.position) {
            await win.setPosition(new LogicalPosition(target.position.x, target.position.y));
          }
        }
      }
    } catch {
      // Leave the window where the config put it.
    }

    const persist = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        void (async () => {
          try {
            // A maximized or minimized window's geometry is the state it is
            // IN, not the one to come back to — saving it means restoring a
            // full-screen-sized window that is not actually maximized.
            if (await win.isMaximized()) return;
            if (await win.isMinimized()) return;
            const scale = await win.scaleFactor();
            const size = (await win.innerSize()).toLogical(scale);
            const position = (await win.outerPosition()).toLogical(scale);
            saveRect({
              x: Math.round(position.x),
              y: Math.round(position.y),
              width: Math.round(size.width),
              height: Math.round(size.height),
            });
          } catch {
            // ignore
          }
        })();
      }, SAVE_DEBOUNCE_MS);
    };

    try {
      unlisteners.push(await win.onMoved(persist));
      unlisteners.push(await win.onResized(persist));
    } catch {
      // Without the events the window simply stops being remembered.
    }
    if (stopped) for (const off of unlisteners) off();
  })();

  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
    for (const off of unlisteners) off();
  };
}
