/**
 * Smooth the mouse wheel everywhere in the app.
 *
 * WebKitGTK (Linux) and WebView2 (Windows) both deliver a mouse notch as one
 * discrete jump — the content teleports ~100px per click with no motion in
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
 * ONE delegated listener rather than a ref per scroller. The app has a dozen
 * scroll containers — the main area, every dialog body, the log view, the mod
 * list, the command palette, the overlay HUD — and threading a hook through
 * each of them means the next one anybody adds silently feels different from
 * the rest. Delegation finds the nearest scrollable ancestor of whatever the
 * pointer is over, so a new scroller is covered the moment it exists.
 *
 * Per-element animation state lives in a WeakMap keyed by that element, so
 * nested scrollers animate independently and a container that unmounts takes
 * its state with it.
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

/**
 * Whether this box is one the wheel actually scrolls.
 *
 * `overflow: hidden` is deliberately NOT scrollable here even though it can be
 * scrolled programmatically: those are clipped layout boxes (the app shell is
 * full of them), and taking the wheel over one would move content the user
 * cannot scroll back by hand.
 *
 * Exported for the test — a DOM-free shape, because the desktop suite has no
 * jsdom and adding one to check three comparisons is not worth a dependency.
 */
export function isScrollable(box: {
  overflowY: string;
  scrollHeight: number;
  clientHeight: number;
}): boolean {
  return (
    (box.overflowY === 'auto' || box.overflowY === 'scroll' || box.overflowY === 'overlay') &&
    box.scrollHeight > box.clientHeight
  );
}

function prefersReducedMotion(): boolean {
  if (document.documentElement.dataset.motion === 'reduced') return true;
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}

/** The nearest ancestor (self included) the wheel would scroll. */
function scrollableFrom(node: EventTarget | null): HTMLElement | null {
  let el = node instanceof Element ? node : null;
  while (el) {
    if (el instanceof HTMLElement) {
      const style = getComputedStyle(el);
      if (
        isScrollable({
          overflowY: style.overflowY,
          scrollHeight: el.scrollHeight,
          clientHeight: el.clientHeight,
        })
      ) {
        return el;
      }
    }
    el = el.parentElement;
  }
  return null;
}

type Animation = { target: number; frame: number };

/**
 * Smooth every scroll container under `root`, present and future.
 *
 * Returns the detach function, so a caller can hand it straight back from a
 * `useEffect`.
 */
export function attachSmoothWheel(root: HTMLElement | Document): () => void {
  const animations = new WeakMap<HTMLElement, Animation>();

  const stepFor = (el: HTMLElement) => {
    const run = () => {
      const anim = animations.get(el);
      if (!anim) return;
      const distance = anim.target - el.scrollTop;
      // Snap home once a frame would move less than a pixel. Not just
      // tidiness: a sub-pixel step can round away to no movement at all, which
      // leaves `distance` unchanged and the rAF loop running forever at 60fps.
      if (Math.abs(distance) < EPSILON || Math.abs(distance * EASE) < 1) {
        el.scrollTop = anim.target;
        anim.frame = 0;
        return;
      }
      // ROUNDED, never fractional. WebKitGTK backs a scrolling box with tiles
      // and blits them by the scroll offset; at a sub-pixel offset the blit
      // and the repaint disagree about where the seam is, and the strip
      // between them keeps whatever was painted there before — which, right
      // after a route change, is a band of the previous page. The guard above
      // already refuses steps smaller than a pixel, so rounding can never
      // stall the chase.
      el.scrollTop = Math.round(el.scrollTop + distance * EASE);
      anim.frame = requestAnimationFrame(run);
    };
    return run;
  };

  const onWheel = (event: Event) => {
    const e = event as WheelEvent;
    if (prefersReducedMotion()) return;
    const el = scrollableFrom(e.target);
    if (!el) return;

    const delta = wheelDeltaPx(e, el.clientHeight);
    if (delta === null) return;

    const max = el.scrollHeight - el.clientHeight;
    if (max <= 0) return;
    // At an edge, let the event through: swallowing it would kill the
    // browser's own overscroll handling and the chaining that scrolls the page
    // behind a list which has hit its end.
    if ((delta < 0 && el.scrollTop <= 0) || (delta > 0 && el.scrollTop >= max)) return;

    e.preventDefault();
    let anim = animations.get(el);
    if (!anim) {
      anim = { target: el.scrollTop, frame: 0 };
      animations.set(el, anim);
    }
    // Not animating means nothing else has moved us since the last frame —
    // trust the DOM over a stale target.
    if (!anim.frame) anim.target = el.scrollTop;
    anim.target = Math.max(0, Math.min(max, anim.target + delta));
    if (!anim.frame) anim.frame = requestAnimationFrame(stepFor(el));
  };

  // Something else moved a container (scrollbar drag, keyboard, route change):
  // adopt its position rather than yanking back to ours. Capture, because
  // `scroll` does not bubble.
  const onScroll = (event: Event) => {
    const el = event.target;
    if (!(el instanceof HTMLElement)) return;
    const anim = animations.get(el);
    if (anim && !anim.frame) anim.target = el.scrollTop;
  };

  // Detach deliberately does not cancel in-flight frames: an animation runs
  // for ~10 frames and ends on its own, and cancelling one mid-flight would
  // strand a container between two positions.
  root.addEventListener('wheel', onWheel, { passive: false });
  root.addEventListener('scroll', onScroll, { capture: true, passive: true });
  return () => {
    root.removeEventListener('wheel', onWheel);
    root.removeEventListener('scroll', onScroll, { capture: true });
  };
}
