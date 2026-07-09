import { Link } from '@tanstack/react-router';
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, Wrench } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { inTauri } from '../lib/platform';
import {
  type DoctorCheck,
  type DoctorResult,
  applyMods,
  doctor,
  updatePatternDb,
} from '../lib/rsmm';
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
  // Game-update repair (re-apply) state. Session-only dismissal: a Steam
  // patch is a new event each time, so no persisted signature.
  const [repairing, setRepairing] = useState(false);
  const [repairError, setRepairError] = useState<string | null>(null);
  const [updateDismissed, setUpdateDismissed] = useState(false);
  // Session dismissal — overrides the persisted check until next launch.
  const [sessionDismissed, setSessionDismissed] = useState(false);
  // Persisted across launches. Re-shown only when the failure set changes.
  const [persistedSignature, setPersistedSignature] = useState<string | null>(() =>
    readDismissed(DISMISS_KEY),
  );
  const [persistedError, setPersistedError] = useState<string | null>(() =>
    readDismissed(ERROR_DISMISS_KEY),
  );

  // Re-runnable so the "Re-check" button can re-verify after the user
  // fixes a path in Settings, without restarting the app. When the user
  // re-checks, clear the persisted dismissal so a now-different (or now-
  // empty) failure set surfaces honestly.
  const runChecks = useCallback(async (clearDismissal = false) => {
    if (!inTauri()) {
      setRunning(false);
      return;
    }
    setRunning(true);
    setError(null);
    if (clearDismissal) {
      setSessionDismissed(false);
      setPersistedSignature(null);
      setPersistedError(null);
    }
    try {
      // Refresh the loader's function-pattern DB first (rolling pattern-db
      // release) so doctor grades the freshly-planted copy, not a stale one.
      // Offline / fetch failures are non-fatal — doctor still runs.
      await updatePatternDb().catch(() => null);
      const r = await doctor();
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }, []);

  useEffect(() => {
    void runChecks();
  }, [runChecks]);

  // One-click recovery after a Steam patch: `apply` clears stale backups,
  // rebuilds the asset map, and re-copies every override. Users who launch
  // through the app's Play button get this implicitly (runModded applies
  // first); this banner covers everyone who launches from Steam.
  const repair = useCallback(async () => {
    setRepairing(true);
    setRepairError(null);
    try {
      const r = await applyMods();
      if (r && r.ok === false) {
        throw new Error(r.stderr.trim() || r.stdout.trim() || `apply exited with code ${r.code}`);
      }
      await runChecks();
    } catch (e) {
      setRepairError(e instanceof Error ? e.message : String(e));
    } finally {
      setRepairing(false);
    }
  }, [runChecks]);

  const signature = useMemo(() => (result ? signatureFor(result.checks) : ''), [result]);

  if (running) return null;

  const updateBanner =
    result?.gameUpdated === true && !updateDismissed ? (
      <section
        aria-label="Game updated"
        className="ember-banner flex w-full items-start gap-3 px-4 py-3"
      >
        <Wrench className="h-4 w-4 text-crimson shrink-0 mt-1" aria-hidden />
        <div className="flex-1 space-y-1">
          <p className="font-serif-italic text-base">
            Ravenswatch updated — your mods were disabled by the game update.
          </p>
          <p className="text-sm text-ash">
            Repair re-applies every enabled mod against the new game files. Playing modded from the
            app's Play button also repairs automatically.
          </p>
          {repairError ? (
            <p className="font-mono text-sm text-crimson break-all">{repairError}</p>
          ) : null}
        </div>
        <Button
          type="button"
          size="sm"
          variant="primary"
          onClick={() => void repair()}
          disabled={repairing}
        >
          {repairing ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <Wrench className="h-3.5 w-3.5" aria-hidden />
          )}
          {repairing ? 'Repairing…' : 'Repair'}
        </Button>
        <Button type="button" size="sm" onClick={() => setUpdateDismissed(true)}>
          Dismiss
        </Button>
      </section>
    ) : null;

  if (error) {
    if (persistedError === error) return null;
    const dismissError = () => {
      writeDismissed(ERROR_DISMISS_KEY, error);
      setPersistedError(error);
      setSessionDismissed(true);
    };
    return (
      <output className="ember-banner flex w-full items-start gap-3 px-4 py-3">
        <AlertTriangle className="h-4 w-4 text-crimson shrink-0 mt-1" aria-hidden />
        <div className="flex-1 space-y-1">
          <p className="font-serif-italic text-base">
            Couldn't reach the rsmm CLI to verify the install.
          </p>
          <p className="font-mono text-sm text-ash break-all">{error}</p>
        </div>
        <CopyButton value={error} />
        <Button type="button" size="sm" onClick={() => void runChecks(true)} disabled={running}>
          {running ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />
          )}
          Re-check
        </Button>
        <Button type="button" size="sm" onClick={dismissError}>
          Dismiss
        </Button>
      </output>
    );
  }

  if (!result) return null;
  // Only hard FAILs gate mods. WARNs (loader missing on Linux, exe
  // newer than pattern db) are informational — they don't block apply
  // and shouldn't dunk a banner on every launch.
  const failing: DoctorCheck[] = result.checks.filter((c) => c.status === 'FAIL');
  if (sessionDismissed || failing.length === 0 || persistedSignature === signature) {
    return updateBanner;
  }

  const dismiss = () => {
    writeDismissed(DISMISS_KEY, signature);
    setPersistedSignature(signature);
    setSessionDismissed(true);
  };

  return (
    <>
      {updateBanner}
      <section aria-label="First-run setup" className="grimoire-card flex flex-col gap-3 p-4">
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
        <div className="flex flex-wrap items-center gap-2">
          <Link to="/settings">
            <Button type="button" size="sm" variant="primary">
              Open Settings
            </Button>
          </Link>
          <Button type="button" size="sm" onClick={() => void runChecks(true)} disabled={running}>
            {running ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
            )}
            Re-check
          </Button>
        </div>
        <p className="font-serif-italic text-sm text-ash">
          Fix paths in Settings, then re-check — or run{' '}
          <span className="font-mono">rsmm doctor</span> from a terminal for diagnostic detail.
        </p>
      </section>
    </>
  );
}
