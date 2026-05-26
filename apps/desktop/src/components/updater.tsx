import { AlertTriangle, Download, RefreshCw } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { ProgressBar } from '@rsmm/ui';
import { appendLauncherLog } from '../lib/launcher-log';
import { type AvailableUpdate, type UpdateCheckError, checkForUpdate, relaunchApp } from '../lib/updater';
import { Button } from './chrome';
import { useToast } from './toast';

interface UpdateStatus {
  state: 'idle' | 'checking' | 'available' | 'downloading' | 'ready' | 'error' | 'check-error' | 'dismissed';
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
        typeof window !== 'undefined' &&
        ('__TAURI_INTERNALS__' in window || '__TAURI__' in window),
    });

    // Check returned an error object
    if (result && 'error' in result && result.error) {
      const checkError = result as UpdateCheckError;
      setStatus({ state: 'check-error', checkError });
      void appendLauncherLog('error', '[Updater] Update check failed', { reason: checkError.reason });
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
    setStatus({ state: 'error', error: String(e), update });
    void appendLauncherLog('error', '[Updater] Download/install failed', { error: detail });
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
      runCheck().catch(() => { /* silent — errors already logged via appendLauncherLog */ });
    }, 1500);
    return () => window.clearTimeout(handle);
  }, []);

  // Downloading: compact bar with progress.
  if (status.state === 'downloading') {
    const p = status.progress;
    return (
      <div
        role="status"
        className="flex items-center gap-3 border-b border-oxblood/60 bg-oxblood/20 px-4 py-2"
      >
        <RefreshCw className="h-4 w-4 text-gilt shrink-0 animate-spin" />
        <span className="font-serif-italic text-parchment shrink-0">
          Downloading v{status.update?.version}…
        </span>
        <div className="flex-1 max-w-80">
          <ProgressBar
            value={p?.downloaded ?? 0}
            max={p?.total ?? 0}
            indeterminate={!p?.total}
          />
        </div>
      </div>
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
                relaunchApp().catch(() => {});
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

  // Error: compact notice.
  if (status.state === 'error') {
    return (
      <div className="flex items-center gap-3 border-b border-crimson/40 bg-crimson/10 px-4 py-2">
        <span className="font-serif-italic text-sm text-crimson flex-1">
          Update check failed.
        </span>
        <button
          type="button"
          onClick={() => { runCheck().catch(() => {}); }}
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
          <p className="font-serif-italic text-sm text-crimson mb-1">
            Update check failed
          </p>
          <p className="font-mono text-xs text-ash break-words">
            {status.checkError.reason}
          </p>
        </div>
        <button
          type="button"
          onClick={() => { runCheck().catch(() => {}); }}
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
        <span className="font-serif-italic text-parchment">
          Update available — v{v.version}
        </span>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant="primary"
            onClick={() => { applyUpdate().catch(() => {}); }}
          >
            <Download className="h-3.5 w-3.5" /> Install
          </Button>
        </div>
      </div>
    );
  }

  return null;
}

export function UpdaterSettings() {
  const [status] = useUpdateStatus();
  const toast = useToast();

  const onCheck = () => {
    runCheck().then(() => {
      if (sharedStatus.state === 'idle') {
        toast.push('You are on the latest version.', 'success');
      }
    });
  };

  const onApply = () => {
    applyUpdate().catch((e) => toast.push(`Update failed: ${e}`, 'error'));
  };

  const onRestart = () => {
    relaunchApp().catch((e) => toast.push(`Restart failed: ${e}`, 'error'));
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          size="sm"
          variant="primary"
          onClick={onCheck}
          disabled={status.state === 'checking' || status.state === 'downloading'}
        >
          <RefreshCw
            className={`h-3.5 w-3.5 ${status.state === 'checking' ? 'animate-spin' : ''}`}
          />
          {status.state === 'checking' ? 'Checking…' : 'Check for updates'}
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
      </div>
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
    </div>
  );
}