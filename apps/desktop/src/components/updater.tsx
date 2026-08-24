import { ProgressBar } from '@rsmm/ui';
import { AlertTriangle, Download, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import pkg from '../../package.json';
import { appendLauncherLog } from '../lib/launcher-log';
import {
  formatBytes,
  gameStatus,
  type LoaderDownloadProgress,
  restartGame,
  type UpdateLoaderResult,
  updateLoader,
} from '../lib/rsmm';
import {
  type AvailableUpdate,
  type UpdateCheckError,
  checkForUpdate,
  getAppVersion,
  getInstallTarget,
  isPermissionError,
  openReleasesPage,
  relaunchApp,
} from '../lib/updater';
import { Button } from './chrome';
import { useToast } from './toast';

interface UpdateStatus {
  state:
    | 'idle'
    | 'checking'
    | 'available'
    | 'downloading'
    | 'ready'
    | 'error'
    | 'check-error'
    // In-place install is impossible on this machine (read-only AppImage
    // location, or a system-wide .deb install). The user has to download.
    | 'manual'
    | 'dismissed';
  update?: AvailableUpdate;
  error?: string;
  checkError?: UpdateCheckError;
  progress?: { downloaded: number; total: number | null };
}

/** Shared store so the Settings panel and the layout banner stay in sync. */
let sharedStatus: UpdateStatus = { state: 'idle' };
const listeners = new Set<(s: UpdateStatus) => void>();

function setStatus(next: UpdateStatus) {
  sharedStatus = next;
  for (const l of listeners) l(sharedStatus);
}

function useUpdateStatus(): [UpdateStatus, (s: UpdateStatus) => void] {
  const [s, set] = useState(sharedStatus);
  useEffect(() => {
    const fn = (next: UpdateStatus) => set(next);
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  }, []);
  return [s, setStatus];
}

let autoCheckScheduled = false;

async function runCheck(): Promise<void> {
  if (sharedStatus.state === 'checking' || sharedStatus.state === 'downloading') return;
  setStatus({ state: 'checking' });

  try {
    const result = await checkForUpdate();

    // Log result to launcher log so it's visible in-app without devtools
    void appendLauncherLog('info', '[Updater] check() result', {
      result: result === null ? 'null (no update / not in Tauri)' : JSON.stringify(result),
      inTauri:
        typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window),
    });

    // Check returned an error object
    if (result && 'error' in result && result.error) {
      const checkError = result as UpdateCheckError;
      setStatus({ state: 'check-error', checkError });
      void appendLauncherLog('error', '[Updater] Update check failed', {
        reason: checkError.reason,
      });
      return;
    }

    if (!result) {
      setStatus({ state: 'idle' });
      return;
    }

    // result is now guaranteed to be AvailableUpdate
    const update = result as AvailableUpdate;

    void appendLauncherLog('info', '[Updater] Update found, starting download', {
      from: update.currentVersion,
      to: update.version,
    });

    // Auto-download immediately — no manual step needed.
    setStatus({ state: 'available', update });
    await applyUpdate();
  } catch (e) {
    const detail = e instanceof Error ? e.message : String(e);
    const message = `Could not check for updates right now: ${detail}`;
    setStatus({ state: 'error', error: message });
    void appendLauncherLog('error', '[Updater] Update check threw exception', { error: detail });
  }
}

async function applyUpdate(): Promise<void> {
  const update = sharedStatus.update;
  if (!update) return;

  // Pre-flight: the updater overwrites the running binary in place. If this
  // install lives somewhere we can't write (root-owned AppImage directory, or
  // a system-wide .deb), downloading 100 MB only to hit
  // "Permission denied (os error 13)" helps nobody — tell the user now and
  // point at the downloads page.
  const target = await getInstallTarget();
  if (target && !target.writable) {
    setStatus({ state: 'manual', update, error: target.reason });
    void appendLauncherLog('warn', '[Updater] In-place update not possible', {
      kind: target.kind,
      path: target.path,
      reason: target.reason,
    });
    return;
  }

  setStatus({ state: 'downloading', update, progress: { downloaded: 0, total: null } });
  try {
    await update.apply((downloaded, total) => {
      setStatus({
        state: 'downloading',
        update,
        progress: { downloaded, total },
      });
    });
    setStatus({ state: 'ready', update });
    void appendLauncherLog('info', '[Updater] Download complete, ready to relaunch', {
      version: update.version,
    });
  } catch (e) {
    const detail = e instanceof Error ? e.message : String(e);
    void appendLauncherLog('error', '[Updater] Download/install failed', { error: detail });
    // The pre-flight can be fooled (path became read-only mid-download, an
    // AppImage manager holding the file, SELinux). Same remedy either way.
    if (isPermissionError(detail)) {
      setStatus({
        state: 'manual',
        update,
        error: `The updater couldn't replace the installed app (${detail}). Download v${update.version} manually and replace this copy.`,
      });
      return;
    }
    setStatus({ state: 'error', error: `Update download/install failed: ${detail}`, update });
  }
}

export function UpdaterBanner() {
  const [status, set] = useUpdateStatus();
  const startedRef = useRef(false);

  useEffect(() => {
    if (autoCheckScheduled || startedRef.current) return;
    autoCheckScheduled = true;
    startedRef.current = true;
    const handle = window.setTimeout(() => {
      runCheck().catch(() => {
        /* silent — errors already logged via appendLauncherLog */
      });
    }, 1500);
    return () => window.clearTimeout(handle);
  }, []);

  // Downloading: compact bar with progress.
  if (status.state === 'downloading') {
    const p = status.progress;
    return (
      <output className="flex w-full items-center gap-3 border-b border-oxblood/60 bg-oxblood/20 px-4 py-2">
        <RefreshCw className="h-4 w-4 text-gilt shrink-0 animate-spin" />
        <span className="font-serif-italic text-parchment shrink-0">
          Downloading v{status.update?.version}…
        </span>
        <div className="flex-1 max-w-80">
          <ProgressBar value={p?.downloaded ?? 0} max={p?.total ?? 0} indeterminate={!p?.total} />
        </div>
      </output>
    );
  }

  // Ready: BIG prominent "update your launcher" prompt.
  if (status.state === 'ready' && status.update) {
    const v = status.update;
    return (
      <div
        role="alert"
        className="fixed inset-0 z-[80] flex items-center justify-center bg-pitch/90"
      >
        <div className="mx-4 w-full max-w-lg rounded-lg border-2 border-crimson bg-pitch p-8 shadow-2xl">
          <div className="text-center">
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-crimson/20">
              <Download className="h-8 w-8 text-crimson" />
            </div>
            <h2 className="font-fraktur text-3xl text-crimson">
              Action Needed: Update Your Launcher!
            </h2>
            <p className="mt-2 font-serif-italic text-parchment">
              Version {v.version} is ready to install
              <span className="font-mono block mt-1 text-sm text-ash">
                (currently running v{v.currentVersion})
              </span>
            </p>
          </div>

          {v.body ? (
            <div className="mt-4 max-h-32 overflow-y-auto rounded border border-oxblood/30 bg-pitch/60 p-3">
              <pre className="font-mono whitespace-pre-wrap text-xs text-ash leading-relaxed">
                {v.body}
              </pre>
            </div>
          ) : null}

          <div className="mt-6 flex flex-col items-center gap-3">
            <Button
              type="button"
              variant="primary"
              onClick={() => {
                relaunchApp().catch((e) => {
                  const detail = e instanceof Error ? e.message : String(e);
                  // The new version is already installed on disk by this point;
                  // a failed relaunch just means the running process didn't swap.
                  // Surface it so the user restarts manually instead of assuming
                  // the click did nothing.
                  setStatus({
                    state: 'error',
                    update: v,
                    error: `Couldn't restart automatically. Close and reopen the app to finish updating to v${v.version}. (${detail})`,
                  });
                  void appendLauncherLog('error', '[Updater] relaunch failed', { error: detail });
                });
              }}
            >
              <Download className="h-4 w-4" /> Restart &amp; update
            </Button>
            <button
              type="button"
              onClick={() => set({ state: 'dismissed', update: v })}
              className="font-mono text-xs text-ash underline-offset-2 hover:text-parchment hover:underline"
            >
              Remind me later
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Manual: in-place install is impossible here — offer the download page.
  if (status.state === 'manual') {
    return (
      <div className="flex items-start gap-3 border-b border-gilt/50 bg-gilt/10 px-4 py-3">
        <AlertTriangle className="h-4 w-4 text-gilt shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <p className="font-serif-italic text-sm text-parchment mb-1">
            Update v{status.update?.version} must be installed manually
          </p>
          <p className="font-mono text-xs text-ash break-words">{status.error}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button
            type="button"
            size="sm"
            variant="primary"
            onClick={() => {
              openReleasesPage().catch(() => {});
            }}
          >
            <Download className="h-3.5 w-3.5" /> Downloads
          </Button>
          <button
            type="button"
            onClick={() => set({ state: 'dismissed', update: status.update })}
            className="font-mono text-xs text-ash hover:text-parchment"
          >
            Dismiss
          </button>
        </div>
      </div>
    );
  }

  // Error: compact notice.
  if (status.state === 'error') {
    return (
      <div className="flex items-center gap-3 border-b border-crimson/40 bg-crimson/10 px-4 py-2">
        <span className="font-serif-italic text-sm text-crimson flex-1">
          {status.error ?? 'Update check failed.'}
        </span>
        <button
          type="button"
          onClick={() => {
            runCheck().catch(() => {});
          }}
          className="font-mono text-xs text-ash hover:text-parchment"
        >
          Retry
        </button>
      </div>
    );
  }

  // Check error: shows diagnostic info about why the check failed.
  if (status.state === 'check-error' && status.checkError) {
    return (
      <div className="flex items-start gap-3 border-b border-crimson/60 bg-crimson/15 px-4 py-3">
        <AlertTriangle className="h-4 w-4 text-crimson shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <p className="font-serif-italic text-sm text-crimson mb-1">Update check failed</p>
          <p className="font-mono text-xs text-ash break-words">{status.checkError.reason}</p>
        </div>
        <button
          type="button"
          onClick={() => {
            runCheck().catch(() => {});
          }}
          className="font-mono text-xs text-ash hover:text-parchment shrink-0 ml-2"
        >
          Retry
        </button>
      </div>
    );
  }

  // 'available' should not normally be visible since we auto-download,
  // but keep it as a fallback in case the download step somehow didn't start.
  if (status.state === 'available' && status.update) {
    const v = status.update;
    return (
      <div className="ember-banner flex items-center justify-between gap-3 border-b border-border px-4 py-2">
        <span className="font-serif-italic text-parchment">Update available — v{v.version}</span>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant="primary"
            onClick={() => {
              applyUpdate().catch(() => {});
            }}
          >
            <Download className="h-3.5 w-3.5" /> Install
          </Button>
        </div>
      </div>
    );
  }

  return null;
}

/**
 * The two versions that matter, parked in the bottom-right corner.
 *
 * They are two SEPARATE channels and a bug report is nearly useless without
 * both: the launcher ships through the Tauri updater, while the game loader and
 * Lua SDK update out of band (see rsmm.engine.loader_update), so the pair can
 * legitimately disagree. Settings shows the same numbers with the update
 * controls; this is the at-a-glance copy.
 *
 * `checkOnly` — a read of what is planted in the game directory. Nothing is
 * written, and a failure leaves the loader half absent rather than showing an
 * error in the corner of every screen.
 */
export function VersionFooter() {
  const [appVersion, setAppVersion] = useState<string>(pkg.version ?? '0.0.0');
  const [loaderVersion, setLoaderVersion] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    void getAppVersion().then((v) => {
      if (alive && v) setAppVersion(v);
    });
    void updateLoader({ checkOnly: true })
      .then((r) => {
        if (alive && r?.installedVersion != null) setLoaderVersion(r.installedVersion);
      })
      .catch(() => {
        /* offline, or no game directory — the loader half just stays quiet */
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    // `pointer-events-none`: this is a caption, not a control, and it sits over
    // the scrolling content — it must never eat a click meant for what is
    // underneath it.
    <div className="font-mono pointer-events-none fixed bottom-1.5 right-3 z-10 select-none text-[10px] leading-tight text-ash/60">
      <span>launcher v{appVersion}</span>
      {loaderVersion != null ? <span> · loader v{loaderVersion}</span> : null}
    </div>
  );
}

/** One "Name — vX" row in the versions block. */
function VersionRow({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="font-serif-italic text-parchment shrink-0">{label}</span>
      <span className="flex-1 border-b border-dotted border-oxblood/40" aria-hidden />
      <span className="font-mono text-sm text-gilt shrink-0">{value}</span>
      {hint ? <span className="font-mono text-xs text-ash shrink-0">{hint}</span> : null}
    </div>
  );
}

/** Human-readable one-liner for a loader-channel result. */
function loaderSummary(r: UpdateLoaderResult | null): string | null {
  if (!r) return null;
  switch (r.status) {
    case 'updated':
      return `Updated to v${r.installedVersion} — restart Ravenswatch to pick it up.`;
    case 'up_to_date':
      return 'Up to date with the loader channel.';
    case 'update_available':
      return `v${r.remoteVersion} is available on the loader channel.`;
    case 'ahead':
      return `This build ships v${r.installedVersion}, newer than the channel's v${r.remoteVersion}.`;
    case 'not_published':
      return 'Nothing published on the loader channel yet.';
    case 'needs_app_update':
      return r.error ?? 'The loader channel needs a newer launcher — update the launcher first.';
    default:
      return r.error ?? null;
  }
}

export function UpdaterSettings() {
  const [status] = useUpdateStatus();
  const toast = useToast();
  // package.json is the compiled-in fallback; getAppVersion() replaces it with
  // the version baked into the running bundle, which is what the updater
  // actually compares against.
  const [appVersion, setAppVersion] = useState<string>(pkg.version ?? '0.0.0');
  const [loader, setLoader] = useState<UpdateLoaderResult | null>(null);
  const [loaderBusy, setLoaderBusy] = useState(false);
  const [loaderError, setLoaderError] = useState<string | null>(null);
  // Download progress for the loader bundle, mirroring what the launcher's own
  // updater shows. A few MB over an unknown link is long enough that a bare
  // spinner reads as "stuck".
  const [loaderProgress, setLoaderProgress] = useState<LoaderDownloadProgress | null>(null);
  // Set once a bundle has been planted: the running game still has the OLD
  // loader mapped, because the DLL is loaded at process start. Offering the
  // restart here is the difference between "updated" and "in effect".
  const [needsGameRestart, setNeedsGameRestart] = useState(false);
  const [restarting, setRestarting] = useState(false);

  useEffect(() => {
    let alive = true;
    void getAppVersion().then((v) => {
      if (alive && v) setAppVersion(v);
    });
    // Read-only probe: reports the planted loader version without writing
    // anything into the game directory. Offline just leaves it unknown —
    // the button below still works once there is a connection.
    void updateLoader({ checkOnly: true })
      .then((r) => {
        if (alive) setLoader(r);
      })
      .catch(() => {
        /* channel unreachable — version stays "unknown", not an error */
      });
    return () => {
      alive = false;
    };
  }, []);

  /** Pull the signed loader DLL + Lua SDK bundle, if the channel is ahead. */
  const runLoaderUpdate = useCallback(async (): Promise<void> => {
    setLoaderBusy(true);
    setLoaderError(null);
    setLoaderProgress(null);
    try {
      const r = await updateLoader({ onProgress: setLoaderProgress });
      setLoader(r);
      void appendLauncherLog('info', '[Updater] loader channel check', {
        status: r?.status ?? 'null',
        installed: r?.installedVersion ?? null,
        remote: r?.remoteVersion ?? null,
      });
      if (r?.status === 'updated') {
        setNeedsGameRestart(true);
        toast.push(
          `Game loader updated to v${r.installedVersion} — restart Ravenswatch to pick it up.`,
          'success',
        );
      } else if (r && r.ok === false) {
        // needs_app_update lands here too: a real answer, phrased as an
        // instruction rather than a transport failure.
        setLoaderError(loaderSummary(r) ?? r.error ?? 'Loader update failed.');
      }
    } catch (e) {
      const detail = e instanceof Error ? e.message : String(e);
      setLoaderError(`Loader update failed: ${detail}`);
      void appendLauncherLog('error', '[Updater] loader update failed', { error: detail });
    } finally {
      setLoaderBusy(false);
      setLoaderProgress(null);
    }
  }, [toast]);

  /** Close the game (if it is up) and launch it again, so a freshly planted
   *  loader is actually the one in the process. */
  const onRestartGame = useCallback(async (): Promise<void> => {
    setRestarting(true);
    try {
      const st = await gameStatus();
      if (st?.running) {
        // A run in progress dies with the process. Never do that silently.
        const ok = window.confirm(
          'Close Ravenswatch and start it again?\n\n' +
            'Any run in progress will be lost — the new loader only takes effect ' +
            'in a fresh session.',
        );
        if (!ok) return;
      }
      const r = await restartGame();
      if (r?.ok) {
        setNeedsGameRestart(false);
        toast.push(r.wasRunning ? 'Ravenswatch restarted.' : 'Ravenswatch launched.', 'success');
      } else {
        toast.push(r?.error ?? 'Could not restart Ravenswatch.', 'error');
      }
    } catch (e) {
      toast.push(`Restart failed: ${e instanceof Error ? e.message : String(e)}`, 'error');
    } finally {
      setRestarting(false);
    }
  }, [toast]);

  // One button, both channels: the launcher itself ships through the Tauri
  // updater, the loader DLL + Lua SDK through the rolling `loader` release.
  // A user who clicks "check for updates" means both.
  const onCheck = () => {
    const app = runCheck().then(() => {
      if (sharedStatus.state === 'idle') {
        toast.push('Launcher is on the latest version.', 'success');
      }
    });
    void Promise.allSettled([app, runLoaderUpdate()]);
  };

  const onApply = () => {
    applyUpdate().catch((e) => toast.push(`Update failed: ${e}`, 'error'));
  };

  const onRestart = () => {
    relaunchApp().catch((e) => toast.push(`Restart failed: ${e}`, 'error'));
  };

  const busy = status.state === 'checking' || status.state === 'downloading' || loaderBusy;
  const loaderVersion =
    loader?.installedVersion == null ? 'unknown' : `v${loader.installedVersion}`;
  const loaderPending =
    loader?.status === 'update_available' && loader.remoteVersion != null
      ? `→ v${loader.remoteVersion}`
      : undefined;

  return (
    <div className="space-y-3">
      <div className="border border-border bg-pitch/40 px-3 py-2">
        <VersionRow
          label="Launcher"
          value={`v${appVersion}`}
          hint={
            status.state === 'ready' || status.state === 'available'
              ? `→ v${status.update?.version}`
              : undefined
          }
        />
        <VersionRow label="Game loader & Lua SDK" value={loaderVersion} hint={loaderPending} />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" size="sm" variant="primary" onClick={onCheck} disabled={busy}>
          <RefreshCw className={`h-3.5 w-3.5 ${busy ? 'animate-spin' : ''}`} />
          {busy ? 'Checking…' : 'Check for updates'}
        </Button>
        {status.state === 'ready' && status.update ? (
          <Button type="button" size="sm" variant="primary" onClick={onRestart}>
            <Download className="h-3.5 w-3.5" /> Restart v{status.update.version}
          </Button>
        ) : null}
        {status.state === 'available' && status.update ? (
          <Button type="button" size="sm" variant="primary" onClick={onApply}>
            <Download className="h-3.5 w-3.5" /> Install v{status.update.version}
          </Button>
        ) : null}
        {status.state === 'manual' ? (
          <Button
            type="button"
            size="sm"
            variant="primary"
            onClick={() => {
              openReleasesPage().catch((e) => toast.push(`Couldn't open downloads: ${e}`, 'error'));
            }}
          >
            <Download className="h-3.5 w-3.5" /> Open downloads page
          </Button>
        ) : null}
      </div>

      {loaderBusy && loaderProgress ? (
        <output className="flex items-center gap-3">
          <span className="shrink-0 font-serif-italic text-parchment text-sm">
            Downloading game loader…
          </span>
          <div className="max-w-80 flex-1">
            <ProgressBar
              value={loaderProgress.received}
              max={loaderProgress.total}
              indeterminate={!loaderProgress.total}
            />
          </div>
          <span className="shrink-0 font-mono text-ash text-xs">
            {formatBytes(loaderProgress.received)}
            {loaderProgress.total ? ` / ${formatBytes(loaderProgress.total)}` : ''}
          </span>
        </output>
      ) : null}

      {needsGameRestart ? (
        <div className="flex flex-wrap items-center gap-3 border border-gilt/40 bg-pitch/40 px-3 py-2">
          <p className="flex-1 text-parchment text-sm">
            The new loader takes effect in a fresh session — a running game keeps the one it
            started with.
          </p>
          <Button
            type="button"
            size="sm"
            variant="primary"
            onClick={() => void onRestartGame()}
            disabled={restarting}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${restarting ? 'animate-spin' : ''}`} />
            {restarting ? 'Restarting…' : 'Restart Ravenswatch'}
          </Button>
        </div>
      ) : null}

      {loaderError ? (
        <p className="text-sm text-crimson" role="alert">
          {loaderError}
        </p>
      ) : loader ? (
        <p className="font-mono text-xs text-ash">{loaderSummary(loader)}</p>
      ) : null}

      {status.state === 'ready' && status.update?.body ? (
        <pre className="font-mono whitespace-pre-wrap text-ash text-sm border border-border bg-pitch/40 p-3 max-h-48 overflow-y-auto">
          {status.update.body}
        </pre>
      ) : null}
      {status.state === 'error' ? (
        <p className="text-sm text-crimson" role="alert">
          {status.error}
        </p>
      ) : null}
      {status.state === 'manual' ? (
        <p className="text-sm text-gilt" role="alert">
          {status.error}
        </p>
      ) : null}
      {status.state === 'check-error' && status.checkError ? (
        <p className="text-sm text-crimson" role="alert">
          {status.checkError.reason}
        </p>
      ) : null}
    </div>
  );
}
