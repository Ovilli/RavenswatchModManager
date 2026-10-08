/**
 * Shared surface between the deep-link handler (main.tsx) and the sign-in
 * page for reporting OAuth relay failures. localStorage (not React state)
 * because the deep link may cold-start a fresh process before any React tree
 * exists; the event covers the warm case where the sign-in page is already
 * mounted and should update immediately.
 */
const DESKTOP_AUTH_ERROR_KEY = 'rsmm.desktopAuthError';
const DESKTOP_AUTH_ERROR_EVENT = 'rsmm:desktop-auth-error';

export function reportDesktopAuthFailure(message: string) {
  localStorage.setItem(DESKTOP_AUTH_ERROR_KEY, message);
  window.dispatchEvent(new Event(DESKTOP_AUTH_ERROR_EVENT));
}

/** Read-and-clear the pending failure message, if any. */
export function takeDesktopAuthFailure(): string | null {
  const message = localStorage.getItem(DESKTOP_AUTH_ERROR_KEY);
  if (message) localStorage.removeItem(DESKTOP_AUTH_ERROR_KEY);
  return message;
}

/** Subscribe to failure reports; returns the unsubscribe function. */
export function onDesktopAuthFailure(listener: () => void): () => void {
  window.addEventListener(DESKTOP_AUTH_ERROR_EVENT, listener);
  return () => window.removeEventListener(DESKTOP_AUTH_ERROR_EVENT, listener);
}

const HANDLED_LINKS_KEY = 'rsmm.desktopAuthHandledLinks';
const HANDLED_LINKS_KEPT = 8;

/**
 * True the first time this window sees a given sign-in deep link, false after.
 *
 * The deep-link plugin keeps the last link it received as "current" for the
 * life of the process, and `getCurrent()` hands it back on EVERY page load. A
 * successful sign-in reloads the page (`location.href = '/'`), so the same
 * link came straight back, found its single-use nonce already spent, and
 * reported "That sign-in link did not match…" — a failure that then waited in
 * storage and greeted the user on their next visit to the sign-in page. The
 * relay page can also deliver one link twice (meta refresh, then a script).
 *
 * sessionStorage, because that is exactly the scope of the problem: it
 * survives the reload and ends with the window, as `getCurrent()`'s memory does.
 */
export function firstSightOfDeepLink(
  raw: string,
  storage: Pick<Storage, 'getItem' | 'setItem'> = sessionStorage,
): boolean {
  let seen: string[] = [];
  try {
    const parsed: unknown = JSON.parse(storage.getItem(HANDLED_LINKS_KEY) ?? '[]');
    if (Array.isArray(parsed)) seen = parsed.filter((x): x is string => typeof x === 'string');
  } catch {
    // Unreadable record: treat as nothing seen rather than block a sign-in.
  }
  if (seen.includes(raw)) return false;
  try {
    storage.setItem(HANDLED_LINKS_KEY, JSON.stringify([...seen, raw].slice(-HANDLED_LINKS_KEPT)));
  } catch {
    // Storage full or unavailable: handling the link matters more.
  }
  return true;
}
