/**
 * Orderly shutdown.
 *
 * The close button used to call the process plugin's `exit(0)` — a hard
 * process exit. On Linux nothing notices; on Windows it tears the process down
 * while WebView2's own child processes are mid-teardown and while spawned
 * `rsmm.exe` sidecars are still running, which leaves orphaned CLI processes
 * holding the mods directory and occasionally an exit-time crash report.
 *
 * The orderly version: stop our children, close the auxiliary windows, then
 * DESTROY the main window and let Tauri exit when its last window is gone.
 *
 * `destroy()` rather than `close()` on purpose — `close()` fires
 * `CloseRequested`, which is where the "you are still running the game" prompt
 * lives, and the user has already answered that question by the time we get
 * here. Re-asking would be an infinite prompt loop.
 *
 * A hard exit remains as the LAST resort, on a timer: if the graceful path
 * wedges (a hung webview, a child that will not die), the user asked to quit
 * and must end up quit.
 */
import { getCurrentWindow } from '@tauri-apps/api/window';
import { exit as processExit } from '@tauri-apps/plugin-process';
import { closeAllOverlays } from './overlay-windows';
import { killLiveChildren } from './rsmm';

/** How long the graceful path gets before the hard exit takes over. */
const FORCE_EXIT_AFTER_MS = 2500;

export async function quitApp(): Promise<void> {
  // Armed first: every step below is best-effort, and the one outcome that is
  // not acceptable is "clicked quit, nothing happened".
  const force = setTimeout(() => {
    void processExit(0);
  }, FORCE_EXIT_AFTER_MS);

  try {
    // Sidecars first — a killed child cannot be orphaned by the exit that
    // follows, and `rsmm.exe` holding the mods folder is the failure users
    // actually notice (the next apply fails on a locked file).
    await killLiveChildren();
  } catch {
    // best effort
  }
  try {
    // Overlay windows are skipTaskbar: if one outlives the main window the
    // process stays alive with nothing visible to close.
    await closeAllOverlays();
  } catch {
    // best effort
  }
  try {
    await getCurrentWindow().destroy();
    // The timer stays armed deliberately. `destroy()` resolving means the
    // window is gone, not that the process is: anything else still holding
    // the event loop would leave the app running with no UI. If we are still
    // here when it fires, the process had its chance.
  } catch {
    clearTimeout(force);
    await processExit(0);
  }
}
