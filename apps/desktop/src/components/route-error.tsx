import { type ErrorComponentProps, useRouter } from '@tanstack/react-router';
import { useEffect } from 'react';

/**
 * Router-level error fallback. Wired as `defaultErrorComponent` so a crash
 * inside any single route renders here *inside the route outlet* — the
 * sidebar, header, and the rest of the shell keep working, instead of the
 * whole window white-screening through the root error boundary in main.tsx.
 *
 * `reset` re-renders the failed route; `router.invalidate()` re-runs its
 * loaders so a transient failure (e.g. the rsmm CLI not ready yet) can
 * recover without a full app reload.
 */
export function RouteErrorComponent({ error, reset }: ErrorComponentProps) {
  const router = useRouter();

  useEffect(() => {
    console.error('Route error:', error);
  }, [error]);

  const message = error instanceof Error ? error.message : String(error);

  return (
    <div className="flex min-h-[60vh] items-center justify-center p-8">
      <div className="max-w-md space-y-4 text-center">
        <h1 className="font-fraktur text-2xl text-crimson">This page hit a snag</h1>
        <pre className="whitespace-pre-wrap break-all font-mono text-sm text-ash">{message}</pre>
        <button
          type="button"
          onClick={() => {
            // Re-run loaders, then clear the error boundary state. `void`:
            // invalidate() is fire-and-forget here; a rejected refetch
            // re-enters this boundary rather than needing a caught promise.
            void router.invalidate();
            reset();
          }}
          className="border border-crimson px-4 py-2 text-parchment hover:bg-crimson/20"
        >
          Try again
        </button>
      </div>
    </div>
  );
}
