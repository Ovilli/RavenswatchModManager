'use client';
import { useEffect } from 'react';

/**
 * Marks the document while an owner has an inline editor open.
 *
 * The saved title/body of a guide or collection is server-rendered one level up
 * in `[slug]/layout.tsx` (see `ServerProse`), which a client page cannot
 * unmount — a layout renders above `children`. Without this flag an owner who
 * clicked Edit would see the saved copy stranded above their own draft.
 *
 * `globals.css` hides `[data-server-prose]` under `[data-editing='true']`.
 * This is UI state for a signed-in owner, not a crawler concern: the block is
 * present and visible in the served HTML, and only this component's effect —
 * which never runs for a crawler that does not execute JS — can hide it.
 */
export function useEditingFlag(editing: boolean): void {
  useEffect(() => {
    const el = document.documentElement;
    if (!editing) {
      delete el.dataset.editing;
      return;
    }
    el.dataset.editing = 'true';
    return () => {
      delete el.dataset.editing;
    };
  }, [editing]);
}
