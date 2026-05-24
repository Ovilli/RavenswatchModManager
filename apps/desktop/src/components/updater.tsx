import { Download, RefreshCw, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { ProgressBar } from '@rsmm/ui';
import { appendLauncherLog } from '../lib/launcher-log';
import { type AvailableUpdate, checkForUpdate, relaunchApp } from '../lib/updater';
import { Button } from './chrome';
import { useToast } from './toast';

interface UpdateStatus {
  state: 'idle' | 'checking' | 'available' | 'downloading' | 'ready' | 'error' | 'dismissed';
  update?: AvailableUpdate;
  error?: string;
  progress?: { downloaded: number; total: number | null };
}

function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
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

async function runCheck(silent: boolean): Promise<void> {
  if (sharedStatus.state === 'checking' || sharedStatus.state === 'downloading') return;
  setStatus({ state: 'checking' });
  try {
    const update = await checkForUpdate();
    if (!update) {
      setStatus(silent ? { state: 'idle' } : { state: 'idle' });
      return;
    }
    setStatus({ state: 'available', update });
  } catch (e) {
    // Surface the underlying error so users can tell a transient network blip
    // from a real updater misconfiguration (wrong pubkey, malformed feed, …).
    const detail = e instanceof Error ? e.message : String(e);
    const message = `Could not check for updates right now: ${detail}`;
    setStatus({ state: 'error', error: message });
    void appendLauncherLog('warn', 'Update check failed', { error: detail });
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
    await relaunchApp();
  } catch (e) {
    setStatus({ state: 'error', error: String(e), update });
  }
}

export function UpdaterBanner() {
  const [status, set] = useUpdateStatus();
  const toast = useToast();
  const startedRef = useRef(false);

  useEffect(() => {
    if (autoCheckScheduled || startedRef.current) return;
    autoCheckScheduled = true;
    startedRef.current = true;
    // Small delay so the first paint isn't blocked by a network round-trip.
    const handle = window.setTimeout(() => {
      runCheck(true).catch(() => {
        /* silent */
      });
    }, 1500);
    return () => window.clearTimeout(handle);
  }, []);

  if (status.state === 'available' && status.update) {
    return (
      <div
        role="status"
        className="ember-banner flex items-center justify-between gap-3 border-b border-border px-4 py-2"
      >
        <span className="font-serif-italic text-parchment">
          Update available — v{status.update.version}
          <span className="font-mono ml-2 text-ash">(current v{status.update.currentVersion})</span>
        </span>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant="primary"
            onClick={() => {
              applyUpdate().catch((e) => toast.push(`Update failed: ${e}`, 'error'));
            }}
          >
            <Download className="h-3.5 w-3.5" /> Install &amp; restart
          </Button>
          <button
            type="button"
            onClick={() => set({ state: 'dismissed', update: status.update })}
            aria-label="Dismiss update notice"
            className="font-mono text-ash hover:text-parchment"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
    );
  }

  if (status.state === 'downloading') {
    const p = status.progress;
    return (
      <div className="ember-banner flex items-center gap-3 border-b border-border px-4 py-2">
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

  if (status.state === 'ready') {
    return (
      <div className="ember-banner flex items-center gap-3 border-b border-border px-4 py-2">
        <RefreshCw className="h-4 w-4 text-gilt" />
        <span className="font-serif-italic text-parchment">Update installed. Restarting…</span>
      </div>
    );
  }

  return null;
}

export function UpdaterSettings() {
  const [status] = useUpdateStatus();
  const toast = useToast();

  const onCheck = () => {
    runCheck(false).then(() => {
      if (sharedStatus.state === 'idle') {
        toast.push('You are on the latest version.', 'success');
      }
    });
  };

  const onApply = () => {
    applyUpdate().catch((e) => toast.push(`Update failed: ${e}`, 'error'));
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
        {status.state === 'available' && status.update ? (
          <Button type="button" size="sm" variant="primary" onClick={onApply}>
            <Download className="h-3.5 w-3.5" /> Install v{status.update.version}
          </Button>
        ) : null}
      </div>
      {status.state === 'available' && status.update?.body ? (
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
