import { AlertTriangle, CheckCircle2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { inTauri } from '../lib/platform';
import { type DoctorCheck, type DoctorResult, doctor } from '../lib/rsmm';
import { Button, CopyButton } from './chrome';

/**
 * Surfaces a banner on the Library page summarizing first-run health
 * checks. Hidden when every check passes, or when the user dismisses it.
 *
 * Replaces the implicit "guess from the failing button" UX with one
 * spot a new install can look at to see *exactly* what's not yet wired
 * (rsmm CLI missing, game dir not detected, etc.).
 */
export function SetupBanner() {
  const [result, setResult] = useState<DoctorResult | null>(null);
  const [running, setRunning] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (!inTauri()) {
      setRunning(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const r = await doctor();
        if (cancelled) return;
        setResult(r);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setRunning(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (dismissed) return null;
  if (running) return null;

  if (error) {
    return (
      <div className="ember-banner flex items-start gap-3 px-4 py-3" role="status">
        <AlertTriangle className="h-4 w-4 text-crimson shrink-0 mt-1" aria-hidden />
        <div className="flex-1 space-y-1">
          <p className="font-serif-italic text-base">
            Couldn't reach the rsmm CLI to verify the install.
          </p>
          <p className="font-mono text-sm text-ash break-all">{error}</p>
        </div>
        <CopyButton value={error} />
        <Button type="button" size="sm" onClick={() => setDismissed(true)}>
          Dismiss
        </Button>
      </div>
    );
  }

  if (!result) return null;
  const failing: DoctorCheck[] = result.checks.filter((c) => !c.ok);
  if (failing.length === 0) return null;

  return (
    <div className="grimoire-card flex flex-col gap-3 p-4" role="status">
      <header className="flex items-center justify-between gap-3">
        <h3 className="font-fraktur text-xl text-parchment flex items-center gap-2">
          <AlertTriangle className="h-5 w-5 text-crimson" aria-hidden />
          First-run setup
        </h3>
        <Button type="button" size="sm" onClick={() => setDismissed(true)}>
          Dismiss
        </Button>
      </header>
      <p className="font-serif-italic text-ash">
        {failing.length === 1
          ? '1 check needs your attention before mods will apply cleanly.'
          : `${failing.length} checks need your attention before mods will apply cleanly.`}
      </p>
      <ul className="space-y-2">
        {result.checks.map((c, i) => (
          <li
            // biome-ignore lint/suspicious/noArrayIndexKey: doctor returns a stable, identity-free list
            key={i}
            className="flex items-start gap-2 font-mono text-sm"
          >
            {c.ok ? (
              <CheckCircle2 className="h-4 w-4 text-gilt shrink-0 mt-0.5" aria-hidden />
            ) : (
              <AlertTriangle className="h-4 w-4 text-crimson shrink-0 mt-0.5" aria-hidden />
            )}
            <span className={c.ok ? 'text-ash' : 'text-parchment'}>
              <span className="uppercase tracking-wider text-xs mr-2">{c.status}</span>
              {c.label}
            </span>
          </li>
        ))}
      </ul>
      <p className="font-serif-italic text-sm text-ash">
        Open <span className="font-mono">Settings</span> to fix paths, or rerun{' '}
        <span className="font-mono">rsmm doctor</span> from a terminal for diagnostic detail.
      </p>
    </div>
  );
}
