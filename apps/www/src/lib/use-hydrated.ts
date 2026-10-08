'use client';
import { useSyncExternalStore } from 'react';

const subscribe = () => () => {};

/**
 * False while React is hydrating server HTML, true from then on (and true
 * straight away on a client-side navigation, so that path renders no extra
 * frame).
 *
 * For a client component whose server render had no data but whose client
 * render might: the mod page's `ModActions` (in `[slug]/layout.tsx`) and the
 * page itself share one react-query entry, and the page's Suspense boundary can
 * hydrate after the layout's fetch has already landed. Rendering that cached
 * data during hydration is a mismatch against the server's spinner, so these
 * components treat the cache as empty until this turns true.
 */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}
