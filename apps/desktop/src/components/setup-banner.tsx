import { Link } from '@tanstack/react-router';
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, Wrench } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { TParts, useT } from '../lib/i18n-react';
import { inTauri } from '../lib/platform';
import {
  type DoctorCheck,
  type DoctorResult,
  type UpdateLoaderResult,
  applyMods,
  doctor,
  updateLoader,
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
  const t = useT();
  const [result, setResult] = useState<DoctorResult | null>(null);
  const [running, setRunning] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Game-update repair (re-apply) state. Session-only dismissal: a Steam
  // patch is a new event each time, so no persisted signature.
  const [repairing, setRepairing] = useState(false);
  const [repairError, setRepairError] = useState<string | null>(null);
  const [fixing, setFixing] = useState(false);
  const [fixError, setFixError] = useState<string | null>(null);
  const [updateDismissed, setUpdateDismissed] = useState(false);
  // Result of the loader/SDK channel check run on mount. Kept so the two
  // outcomes a user has to act on can be surfaced instead of swallowed.
  const [loaderUpdate, setLoaderUpdate] = useState<UpdateLoaderResult | null>(null);
  const [loaderDismissed, setLoaderDismissed] = useState(false);
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
      // Then the loader DLL + Lua SDK (rolling `loader` release). Both are
      // plain files in the game directory, so a loader or SDK fix reaches
      // users here rather than through a desktop release + reinstall. The
      // bundle is signature- and version-gated, and planting fails cleanly
      // while the game holds winhttp.dll open — so failures are non-fatal
      // and doctor still runs.
      // Keep the result: a landed update needs a game restart to take
      // effect, and a blocked one needs the game closed. Still non-fatal —
      // a transport failure must not stop doctor from running.
      setLoaderUpdate(await updateLoader().catch(() => null));
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
  // rebuilds the asset map, and re-copies every override. Deliberately NOT
  // doctor --fix — a game update need not produce a FAIL finding, and this
  // banner promises a re-apply specifically.
  const repair = useCallback(async () => {
    setRepairing(true);
    setRepairError(null);
    try {
      const r = await applyMods();
      if (r && r.ok === false) {
        throw new Error(
          r.stderr.trim() ||
            r.stdout.trim() ||
            t('apply exited with code {code}', { code: r.code }),
        );
      }
      await runChecks();
    } catch (e) {
      setRepairError(e instanceof Error ? e.message : String(e));
    } finally {
      setRepairing(false);
    }
  }, [runChecks, t]);

  // Doctor carries the repair for each finding it reports (apply,
  // install-loader, rebuild-asset-map, update-data) and re-runs every check
  // afterwards, so a repair only reads as fixed when the check goes green.
  // No --force: destructive repairs roll the install back or delete installed
  // files, and a banner button must never do that unasked.
  const fixFindings = useCallback(async () => {
    setFixing(true);
    setFixError(null);
    try {
      const r = await doctor({ fix: true });
      if (r) setResult(r);
      const failedRepairs = (r?.repairs ?? []).filter((x) => x.outcome === 'failed');
      if (failedRepairs.length > 0) {
        setFixError(failedRepairs.map((x) => `${x.fix}: ${x.detail || t('failed')}`).join('; '));
      }
    } catch (e) {
      setFixError(e instanceof Error ? e.message : String(e));
    } finally {
      setFixing(false);
    }
  }, [t]);

  const signature = useMemo(() => (result ? signatureFor(result.checks) : ''), [result]);

  if (running) return null;

  const updateBanner =
    result?.gameUpdated === true && !updateDismissed ? (
      <section
        aria-label={t('Game updated')}
        className="ember-banner flex w-full items-start gap-3 px-4 py-3"
      >
        <Wrench className="h-4 w-4 text-crimson shrink-0 mt-1" aria-hidden />
        <div className="flex-1 space-y-1">
          <p className="font-serif-italic text-base">
            {t('Ravenswatch updated — your mods were disabled by the game update.')}
          </p>
          <p className="text-sm text-ash">
            {t(
              "Repair re-applies every enabled mod against the new game files. Playing modded from the app's Play button also repairs automatically.",
            )}
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
          {repairing ? t('Repairing…') : t('Repair')}
        </Button>
        <Button type="button" size="sm" onClick={() => setUpdateDismissed(true)}>
          {t('Dismiss')}
        </Button>
      </section>
    ) : null;

  // The loader is read by the game at process start, so an update that
  // lands while Ravenswatch is open does nothing until it restarts — and a
  // silent channel meant the user could never know that. Only the two
  // actionable outcomes get a banner; up-to-date, nothing-published,
  // offline and every other status stay quiet.
  const loaderBanner = (() => {
    if (!loaderUpdate || loaderDismissed) return null;

    const updated = loaderUpdate.status === 'updated';
    const needsApp = loaderUpdate.status === 'needs_app_update';
    const blocked = loaderUpdate.ok === false && /in use/i.test(loaderUpdate.error ?? '');
    if (!updated && !blocked && !needsApp) return null;

    const message = updated
      ? t('Loader updated to v{version} — restart Ravenswatch to pick it up.', {
          version: loaderUpdate.installedVersion ?? '',
        })
      : blocked
        ? t('A loader update is waiting — close Ravenswatch, then re-check.')
        : t('A newer loader is available, but it needs a newer version of this app.');

    return (
      <section
        aria-label={t('Loader update')}
        className="ember-banner flex w-full items-start gap-3 px-4 py-3"
      >
        {updated ? (
          <CheckCircle2 className="h-4 w-4 text-gilt shrink-0 mt-1" aria-hidden />
        ) : (
          <AlertTriangle className="h-4 w-4 text-crimson shrink-0 mt-1" aria-hidden />
        )}
        <div className="flex-1 space-y-1">
          <p className="font-serif-italic text-base">{message}</p>
          {updated && loaderUpdate.notes ? (
            <p className="text-sm text-ash">{loaderUpdate.notes}</p>
          ) : null}
        </div>
        {blocked ? (
          <Button type="button" size="sm" onClick={() => void runChecks()} disabled={running}>
            {running ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
            )}
            {t('Re-check')}
          </Button>
        ) : null}
        <Button type="button" size="sm" onClick={() => setLoaderDismissed(true)}>
          {t('Dismiss')}
        </Button>
      </section>
    );
  })();

  const banners = (
    <>
      {updateBanner}
      {loaderBanner}
    </>
  );

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
            {t("Couldn't reach the rsmm CLI to verify the install.")}
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
          {t('Re-check')}
        </Button>
        <Button type="button" size="sm" onClick={dismissError}>
          {t('Dismiss')}
        </Button>
      </output>
    );
  }

  if (!result) return banners;
  // Only hard FAILs gate mods. WARNs (loader missing on Linux, exe
  // newer than pattern db) are informational — they don't block apply
  // and shouldn't dunk a banner on every launch.
  const failing: DoctorCheck[] = result.checks.filter((c) => c.status === 'FAIL');
  const fixableFailures = failing.filter((c) => c.fixable).length;
  if (sessionDismissed || failing.length === 0 || persistedSignature === signature) {
    return banners;
  }

  const dismiss = () => {
    writeDismissed(DISMISS_KEY, signature);
    setPersistedSignature(signature);
    setSessionDismissed(true);
  };

  return (
    <>
      {banners}
      <section aria-label={t('First-run setup')} className="grimoire-card flex flex-col gap-3 p-4">
        <header className="flex items-center justify-between gap-3">
          <h3 className="font-fraktur text-xl text-parchment flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-crimson" aria-hidden />
            {t('First-run setup')}
          </h3>
          <Button type="button" size="sm" onClick={dismiss}>
            {t('Dismiss')}
          </Button>
        </header>
        <p className="font-serif-italic text-ash">
          {t.n(
            failing.length,
            '{n} check needs your attention before mods will apply cleanly.',
            '{n} checks need your attention before mods will apply cleanly.',
          )}
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
                {!c.ok && c.detail ? (
                  <span className="font-serif-italic mt-0.5 block normal-case tracking-normal text-ash">
                    {c.detail}
                  </span>
                ) : null}
                {/* `c.fix.label` is the CLI's own wording — passed through
                    untranslated, like every other doctor string. */}
                {!c.ok && c.fix ? (
                  <span className="mt-0.5 block text-xs text-ash">
                    {t('fix:')} {c.fix.label}
                    {c.fix.manual ? ` ${t('(manual)')}` : ''}
                  </span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
        {fixError ? (
          <p className="font-mono text-sm text-crimson break-all" role="alert">
            {fixError}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          {fixableFailures > 0 ? (
            <Button
              type="button"
              size="sm"
              variant="primary"
              onClick={() => void fixFindings()}
              disabled={fixing || running}
            >
              {fixing ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              ) : (
                <Wrench className="h-3.5 w-3.5" aria-hidden />
              )}
              {fixing ? t('Repairing…') : t('Repair {n} automatically', { n: fixableFailures })}
            </Button>
          ) : null}
          <Link to="/settings">
            <Button type="button" size="sm" variant={fixableFailures > 0 ? 'default' : 'primary'}>
              {t('Open Settings')}
            </Button>
          </Link>
          <Button type="button" size="sm" onClick={() => void runChecks(true)} disabled={running}>
            {running ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
            )}
            {t('Re-check')}
          </Button>
        </div>
        <p className="font-serif-italic text-sm text-ash">
          <TParts
            text={t(
              'Fix paths in Settings, then re-check — or run {command} from a terminal for diagnostic detail.',
            )}
            parts={{ command: <span className="font-mono">rsmm doctor</span> }}
          />
        </p>
      </section>
    </>
  );
}
