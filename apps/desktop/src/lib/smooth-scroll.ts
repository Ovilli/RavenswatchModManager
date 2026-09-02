/**
 * Smooth the mouse wheel in the app's main scroll area.
 *
 * WebKitGTK (Linux) and WebView2 (Windows) both deliver a mouse notch as one
 * discrete jump — the viewport teleports ~100px per click with no motion in
 * between — which is what makes the app feel snappier and harder than a
 * browser on the same page. `scroll-behavior: smooth` does not help: it only
 * applies to PROGRAMMATIC scrolls (`scrollTo`, anchor jumps), never to wheel
 * input.
 *
 * So the notch is intercepted and animated. Two rules keep that from making
 * things worse:
 *
 *  1. A trackpad is left alone. It already sends a stream of small pixel
 *     deltas with its own inertia; re-animating that fights the gesture and
 *     adds lag to the one input device that was never the problem. Only
 *     discrete events — line/page deltaMode, or a pixel delta big enough to be
 *     a notch — are taken over.
 *  2. Reduced motion opts out entirely, and so does a zoom (ctrl) or a
 *     horizontal (shift) wheel, which the browser must keep handling itself.
 *
 * The target position is re-synced from the live `scrollTop` whenever an
 * animation is not running, so a scrollbar drag, a keyboard PageDown or a
 * route change calling `scrollTo` never leaves the animator chasing a stale
 * position.
 */

/** Pixel delta at or above which a `deltaMode: 0` event is treated as a mouse
 *  notch rather than a trackpad glide. WebKitGTK reports 53-120px per notch;
 *  trackpad frames are typically single digits. */
const NOTCH_PX = 40;

/** A line delta is in text rows, a page delta in viewports. */
const LINE_PX = 40;

/** How much of the remaining distance is covered per frame. Higher is snappier;
 *  0.18 lands a notch in ~10 frames (~160ms at 60fps), which reads as motion
 *  without feeling like the page is coasting away from the wheel. */
const EASE = 0.18;

/** Below this the animation is done — a sub-pixel chase never converges. */
const EPSILON = 0.5;

/**
 * Pixels this wheel event should scroll, or null to let the browser have it.
 * `viewportPx` is the scroll container's own height, which is what a PAGE
 * delta means here — the window's height is a different number the moment the
 * container is not the whole window, and it never is in this app.
 *
 * Exported for the test: the device heuristic is the part of this file that
 * silently ruins a trackpad if it drifts.
 */
export function wheelDeltaPx(
  e: { deltaY: number; deltaMode: number; ctrlKey?: boolean; shiftKey?: boolean },
  viewportPx: number,
): number | null {
  // Ctrl-wheel is zoom, shift-wheel is horizontal. Neither is ours.
  if (e.ctrlKey || e.shiftKey) return null;
  if (!e.deltaY) return null;
  if (e.deltaMode === 1) return e.deltaY * LINE_PX; // WheelEvent.DOM_DELTA_LINE
  if (e.deltaMode === 2) return e.deltaY * viewportPx; // DOM_DELTA_PAGE
  // Pixel mode: a trackpad, unless the step is big enough to be a notch.
  return Math.abs(e.deltaY) >= NOTCH_PX ? e.deltaY : null;
}

function prefersReducedMotion(): boolean {
  if (document.documentElement.dataset.motion === 'reduced') return true;
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}

/**
 * Attach the smoothing to one scroll container. Returns the detach function,
 * so a caller can hand it straight back from a `useEffect`.
 */
export function attachSmoothWheel(el: HTMLElement): () => void {
  let target = el.scrollTop;
  let frame = 0;

  const step = () => {
    const distance = target - el.scrollTop;
    // Snap home once a frame would move less than a pixel. Not just tidiness:
    // a sub-pixel step can round away to no movement at all, which leaves
    // `distance` unchanged and the rAF loop running forever at 60fps.
    if (Math.abs(distance) < EPSILON || Math.abs(distance * EASE) < 1) {
      el.scrollTop = target;
      frame = 0;
      return;
    }
    el.scrollTop += distance * EASE;
    frame = requestAnimationFrame(step);
  };

  const onWheel = (e: WheelEvent) => {
    if (prefersReducedMotion()) return;
    const delta = wheelDeltaPx(e, el.clientHeight);
    if (delta === null) return;

    const max = el.scrollHeight - el.clientHeight;
    if (max <= 0) return;
    // At an edge, let the event through: swallowing it would kill the
    // browser's own overscroll handling and any outer scroll chaining.
    if ((delta < 0 && el.scrollTop <= 0) || (delta > 0 && el.scrollTop >= max)) return;

    e.preventDefault();
    // Not animating means nothing else has moved us since the last frame —
    // trust the DOM over a stale target.
    if (!frame) target = el.scrollTop;
    target = Math.max(0, Math.min(max, target + delta));
    if (!frame) frame = requestAnimationFrame(step);
  };

  // Something else moved the container (scrollbar drag, keyboard, route
  // change): adopt its position rather than yanking back to ours.
  const onScroll = () => {
    if (!frame) target = el.scrollTop;
  };

  el.addEventListener('wheel', onWheel, { passive: false });
  el.addEventListener('scroll', onScroll, { passive: true });
  return () => {
    el.removeEventListener('wheel', onWheel);
    el.removeEventListener('scroll', onScroll);
    if (frame) cancelAnimationFrame(frame);
  };
}
