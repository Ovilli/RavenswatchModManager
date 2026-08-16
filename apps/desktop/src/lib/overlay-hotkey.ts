/**
 * The un-pin hotkey.
 *
 * A click-through overlay ignores the mouse completely — including the click
 * that would turn click-through back off. Settings has a button for it, but
 * alt-tabbing out of a fight to reach it is not an answer, so the toggle is
 * also bound to a global shortcut that works while the game has focus.
 *
 * Registered by the MAIN window (overlays come and go); it broadcasts the same
 * event the Settings button emits, so there is one code path to undo the pin.
 */
import { isRegistered, register, unregister } from '@tauri-apps/plugin-global-shortcut';
import { emit } from '@tauri-apps/api/event';
import { OVERLAY_INTERACTIVE_EVENT } from '../components/overlay-hud';

export const UNPIN_SHORTCUT = 'CommandOrControl+Alt+O';

/**
 * Bind the shortcut. Best effort: another application may already own the
 * combination, and failing to bind must not take the app down — the Settings
 * button still works.
 *
 * Returns true when the binding is live.
 */
export async function registerUnpinShortcut(): Promise<boolean> {
  try {
    if (await isRegistered(UNPIN_SHORTCUT)) return true;
    await register(UNPIN_SHORTCUT, (event) => {
      // Fire on the key press, not its release, or the toggle runs twice.
      if (event.state !== 'Pressed') return;
      void emit(OVERLAY_INTERACTIVE_EVENT);
    });
    return true;
  } catch (e) {
    console.warn('overlay un-pin shortcut unavailable', e);
    return false;
  }
}

export async function unregisterUnpinShortcut(): Promise<void> {
  try {
    await unregister(UNPIN_SHORTCUT);
  } catch {
    // Nothing to release.
  }
}
