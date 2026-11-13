/**
 * Mods the last modded launch left out because their manifest `[requires]` is
 * newer than this CLI or loader. `apply` reports them in its JSON (`skipped`)
 * and used to say so only on stderr, so the game started and the mod was just
 * missing. The launch still goes ahead; the banner shows this until dismissed.
 */
export interface SkippedMod {
  id: string;
  /** The CLI's own sentence (English; CLI output is not translated). */
  reason: string;
  needs?: { cli?: number; loader?: number };
}

let current: SkippedMod[] = [];
const listeners = new Set<() => void>();

export function getSkippedMods(): SkippedMod[] {
  return current;
}

export function subscribeSkippedMods(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/** Replace the notice with this launch's skipped mods; an empty list clears it. */
export function setSkippedMods(skipped: SkippedMod[] | undefined): void {
  const next = Array.isArray(skipped) ? skipped.filter((m) => m && typeof m.id === 'string') : [];
  if (next.length === 0 && current.length === 0) return;
  current = next;
  for (const fn of listeners) fn();
}
