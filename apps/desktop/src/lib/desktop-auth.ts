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
