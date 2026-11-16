import { RefreshCw, X } from 'lucide-react';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import {
  getLaunchActive,
  getPendingCliUpdate,
  subscribeChannelPhases,
} from '../lib/channel-status';
import { useT } from '../lib/i18n-react';
import { relaunchApp } from '../lib/updater';
import { Button } from './chrome';
import './cli-update-dialog.css';

/** Offer a staged CLI once per app session, after the other startup notices. */
export function CliUpdateDialog({
  enabled,
  preview = false,
}: { enabled: boolean; preview?: boolean }) {
  const pending = useSyncExternalStore(subscribeChannelPhases, getPendingCliUpdate);
  const launching = useSyncExternalStore(subscribeChannelPhases, getLaunchActive);
  const [dismissed, setDismissed] = useState(false);

  if (!enabled || dismissed || launching || (!pending && !preview)) return null;

  return (
    <CliUpdateCard
      onLater={() => setDismissed(true)}
      onUpdate={preview ? async () => setDismissed(true) : relaunchApp}
    />
  );
}

export function CliUpdateCard({
  onLater,
  onUpdate,
}: { onLater: () => void; onUpdate: () => Promise<void> }) {
  const t = useT();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const updating = useRef(false);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const previous = document.activeElement as HTMLElement | null;
    // Native modality keeps keyboard focus in the dialog and the app inert.
    dialog.showModal();
    dialog.focus();
    return () => {
      dialog.close();
      previous?.focus?.();
    };
  }, []);

  const update = async () => {
    if (updating.current) return;
    updating.current = true;
    setBusy(true);
    setError(null);
    try {
      await onUpdate();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      updating.current = false;
      setBusy(false);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      tabIndex={-1}
      aria-labelledby="cli-update-title"
      aria-busy={busy}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onLater();
      }}
      onKeyDown={(event) => {
        if (event.key !== 'Tab') return;
        const buttons =
          event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)');
        const first = buttons[0];
        const last = buttons[buttons.length - 1];
        if (!first || !last) {
          event.preventDefault();
          dialogRef.current?.focus();
        } else if (
          event.shiftKey &&
          (document.activeElement === first || document.activeElement === event.currentTarget)
        ) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }}
      className="cli-update-dialog grimoire-card grimoire-card--raised m-auto h-fit max-h-[calc(100vh-2rem)] w-[min(560px,calc(100%-2rem))] overflow-y-auto p-6 text-parchment backdrop:bg-pitch/80 focus:outline-none"
    >
      <header className="flex items-start justify-between gap-4">
        <h2 id="cli-update-title" className="font-fraktur text-3xl text-parchment">
          {t('Update available')}
        </h2>
        <button
          type="button"
          aria-label={t('Close')}
          onClick={onLater}
          disabled={busy}
          className="-mr-1 -mt-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-parchment/85 text-oxblood transition-colors hover:bg-parchment disabled:pointer-events-none disabled:opacity-50"
        >
          <X className="h-5 w-5" aria-hidden />
        </button>
      </header>
      {error ? (
        <p role="alert" className="mt-4 break-words text-sm text-parchment">
          {t('Could not restart the app: {error}', { error })}
        </p>
      ) : null}
      <footer className="mt-6 flex flex-wrap justify-end gap-3">
        <Button
          type="button"
          className="cli-update-dialog__defer"
          onClick={onLater}
          disabled={busy}
        >
          {t('Update on close')}
        </Button>
        <Button type="button" variant="primary" onClick={() => void update()} disabled={busy}>
          {busy ? <RefreshCw className="h-4 w-4 animate-spin" aria-hidden /> : null}
          {busy ? t('Restarting…') : t('Update now')}
        </Button>
      </footer>
    </dialog>
  );
}
