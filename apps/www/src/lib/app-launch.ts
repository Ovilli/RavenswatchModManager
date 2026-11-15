/**
 * Watch a user-initiated protocol link for a likely handoff. Browsers cannot
 * report whether RSMM is installed: hiding the page is only a best-effort signal.
 * A browser confirmation prompt can blur the window without opening the app,
 * so pause on blur and allow another grace period when focus returns.
 */
export function watchAppLaunch(onFallback: () => void, onSettled?: () => void): () => void {
  let timer: number | undefined;
  let active = true;

  function clearTimer() {
    window.clearTimeout(timer);
  }

  function stop() {
    active = false;
    clearTimer();
    window.removeEventListener('blur', clearTimer);
    window.removeEventListener('focus', scheduleFallback);
    window.removeEventListener('pagehide', finish);
    document.removeEventListener('visibilitychange', onVisibilityChange);
  }

  function finish() {
    if (!active) return;
    stop();
    onSettled?.();
  }

  function scheduleFallback() {
    clearTimer();
    timer = window.setTimeout(() => {
      if (document.visibilityState === 'hidden') {
        finish();
        return;
      }
      // Don't place a modal behind a pending browser/OS confirmation prompt.
      if (!document.hasFocus()) return;
      finish();
      onFallback();
    }, 2000);
  }

  function onVisibilityChange() {
    if (document.visibilityState === 'hidden') finish();
  }

  window.addEventListener('blur', clearTimer);
  window.addEventListener('focus', scheduleFallback);
  window.addEventListener('pagehide', finish);
  document.addEventListener('visibilitychange', onVisibilityChange);
  scheduleFallback();
  return stop;
}
