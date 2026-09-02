import { type ErrorComponentProps, useRouter } from '@tanstack/react-router';
import { useEffect } from 'react';
import { explainError } from '../lib/errors';
import { useT } from '../lib/i18n-react';
import { CopyButton } from './chrome';

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
  const t = useT();
  const router = useRouter();

  useEffect(() => {
    console.error('Route error:', error);
  }, [error]);

  const message = error instanceof Error ? error.message : String(error);
  // Most route crashes are a failed rsmm call, so give the same actionable
  // headline the Commands page does and keep the raw text one click away.
  const { title, hint } = explainError(message);

  return (
    <div className="flex min-h-[60vh] items-center justify-center p-8">
      <div className="max-w-md space-y-4 text-center">
        <h1 className="font-fraktur text-2xl text-crimson">{t('This page hit a snag')}</h1>
        {/* `explainError` returns English sources; translate them here so the
            mapping table stays free of React and of the active locale. */}
        <p className="font-serif-italic text-parchment">{t(title)}</p>
        {hint ? <p className="font-serif-italic text-sm text-ash">{t(hint)}</p> : null}
        <details className="border border-border/70 text-left">
          <summary className="font-mono cursor-pointer px-3 py-2 text-xs text-ash hover:text-parchment">
            {t('Error detail')}
          </summary>
          <div className="flex items-start gap-2 border-t border-border/70 p-3">
            <pre className="max-h-48 flex-1 overflow-auto whitespace-pre-wrap break-all font-data text-xs text-ash">
              {message}
            </pre>
            <CopyButton value={message} />
          </div>
        </details>
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
          {t('Try again')}
        </button>
      </div>
    </div>
  );
}
