import { AlertTriangle, CheckCircle2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { inTauri } from '../lib/platform';
import { type DoctorCheck, type DoctorResult, doctor } from '../lib/rsmm';
import { Button, CopyButton } from './chrome';

const DISMISS_KEY = 'rsmm:setup-banner-dismissed';
const ERROR_DISMISS_KEY = 'rsmm:setup-banner-error-dismissed';

function signatureFor(checks: DoctorCheck[]): string {
  return checks
    .filter((c) => c.status === 'FAIL')
    .map((c) => `${c.status}:${c.label}`)
    .sort()
    .join('|');
}

function readDismissed(key: string): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeDismissed(key: string, value: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable — banner returns next launch, acceptable */
  }
}

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
  // Session dismissal — overrides the persisted check until next launch.
  const [sessionDismissed, setSessionDismissed] = useState(false);
  // Persisted across launches. Re-shown only when the failure set changes.
  const [persistedSignature, setPersistedSignature] = useState<string | null>(() =>
    readDismissed(DISMISS_KEY),
  );
  const [persistedError, setPersistedError] = useState<string | null>(() =>
    readDismissed(ERROR_DISMISS_KEY),
  );

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

  const signature = useMemo(
    () => (result ? signatureFor(result.checks) : ''),
    [result],
  );

  if (sessionDismissed) return null;
  if (running) return null;

  if (error) {
    if (persistedError === error) return null;
    const dismissError = () => {
      writeDismissed(ERROR_DISMISS_KEY, error);
      setPersistedError(error);
      setSessionDismissed(true);
    };
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
        <Button type="button" size="sm" onClick={dismissError}>
          Dismiss
        </Button>
      </div>
    );
  }

  if (!result) return null;
  // Only hard FAILs gate mods. WARNs (loader missing on Linux, exe
  // newer than pattern db) are informational — they don't block apply
  // and shouldn't dunk a banner on every launch.
  const failing: DoctorCheck[] = result.checks.filter((c) => c.status === 'FAIL');
  if (failing.length === 0) return null;
  if (persistedSignature === signature) return null;

  const dismiss = () => {
    writeDismissed(DISMISS_KEY, signature);
    setPersistedSignature(signature);
    setSessionDismissed(true);
  };

  return (
    <div className="grimoire-card flex flex-col gap-3 p-4" role="status">
      <header className="flex items-center justify-between gap-3">
        <h3 className="font-fraktur text-xl text-parchment flex items-center gap-2">
          <AlertTriangle className="h-5 w-5 text-crimson" aria-hidden />
          First-run setup
        </h3>
        <Button type="button" size="sm" onClick={dismiss}>
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
