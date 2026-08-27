import { isRateLimited } from '@rsmm/api-client';
import { openUrl } from '@tauri-apps/plugin-opener';
import { Check, ExternalLink, Link2, Loader2, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { api, describeApiError } from '../lib/api';
import { appendLauncherLog, readLauncherLog } from '../lib/launcher-log';
import { buildLogReport } from '../lib/log-share';
import type { LocalMod } from '../lib/rsmm';
import { listLocalMods } from '../lib/rsmm';
import { detectOs } from '../lib/telemetry';
import { Button, CopyButton, Fleuron, MonoTag, Panel } from './chrome';
import { useToast } from './toast';

const RSMM_VERSION = import.meta.env.VITE_RSMM_VERSION ?? '0.0.0-dev';

/**
 * "Share log" — turn a run's log into a link instead of a wall of pasted text.
 *
 * The whole point of the dialog is the preview pane. This uploads a file off
 * the user's machine to a URL they are about to hand to a stranger, so it
 * shows the exact bytes first and never uploads anything the user has not had
 * the chance to read. Redaction defaults on for the same reason.
 */
export function ShareLogDialog({
  loaderLines,
  loaderPath,
  onClose,
}: {
  loaderLines: string[];
  loaderPath?: string | null;
  onClose: () => void;
}) {
  const toast = useToast();
  const [note, setNote] = useState('');
  const [redact, setRedact] = useState(true);
  const [includeLauncher, setIncludeLauncher] = useState(true);
  const [includeMods, setIncludeMods] = useState(true);
  const [showPreview, setShowPreview] = useState(false);
  const [mods, setMods] = useState<LocalMod[] | null>(null);
  const [launcherLog, setLauncherLog] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shared, setShared] = useState<{ url: string; expiresAt: string } | null>(null);

  // Gathered up front, not at upload time: the preview has to show what will
  // actually be sent, and a fetch hidden behind the button would make the
  // preview a lie.
  useEffect(() => {
    void listLocalMods()
      .then(setMods)
      .catch(() => setMods([]));
    void readLauncherLog()
      .then((raw) => setLauncherLog(raw.split('\n').slice(-300).join('\n')))
      .catch(() => setLauncherLog(''));
  }, []);

  const report = useMemo(
    () =>
      buildLogReport({
        rsmmVersion: RSMM_VERSION,
        os: detectOs(),
        loaderLines,
        loaderPath,
        launcherLog: includeLauncher ? launcherLog : null,
        mods: includeMods ? (mods ?? []) : undefined,
        note,
        redact,
      }),
    [loaderLines, loaderPath, includeLauncher, launcherLog, includeMods, mods, note, redact],
  );

  const upload = async () => {
    setUploading(true);
    setError(null);
    try {
      const res = await api.logs.share({
        content: report.content,
        source: report.source,
        rsmmVersion: RSMM_VERSION,
        os: detectOs(),
        meta: report.meta,
      });
      setShared({ url: res.url, expiresAt: res.expiresAt });
      // Recorded locally so the link is recoverable after the dialog closes —
      // a share the user loses the URL to is a share they upload twice.
      await appendLauncherLog('info', 'Shared diagnostic log', {
        url: res.url,
        expiresAt: res.expiresAt,
        bytes: report.content.length,
      });
      toast.push('Log uploaded — link copied below.', 'success');
    } catch (err) {
      setError(
        isRateLimited(err)
          ? `Too many uploads — try again in ${err.retryAfter}s. (Shares are rate limited to keep this from being used as file hosting.)`
          : describeApiError(err),
      );
    } finally {
      setUploading(false);
    }
  };

  const expiryLabel = shared
    ? new Date(shared.expiresAt).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      })
    : '';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-pitch/80 p-4">
      <Panel className="max-h-[90vh] w-full max-w-3xl overflow-auto">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="font-fraktur text-2xl text-parchment">Share this log</h3>
            <p className="font-serif-italic mt-1 text-sm text-ash">
              Uploads the log once and gives you a link to paste into a bug report — no more pasting
              thousands of lines into chat.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="text-ash transition-colors hover:text-parchment"
          >
            <X className="h-5 w-5" aria-hidden />
          </button>
        </div>

        <Fleuron className="my-3" />

        {shared ? (
          <div className="space-y-3">
            <p className="font-serif-italic text-parchment">
              Uploaded. Paste this link wherever you are asking for help.
            </p>
            <div className="flex flex-wrap items-center gap-2 border border-gilt/40 bg-pitch/60 p-3">
              <span className="font-mono min-w-0 flex-1 break-all text-sm text-gilt">
                {shared.url}
              </span>
              <CopyButton value={shared.url} />
              <Button type="button" size="sm" onClick={() => void openUrl(shared.url)}>
                <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                Open
              </Button>
            </div>
            <p className="font-serif-italic text-xs text-ash">
              The link stops working on {expiryLabel} and the text is deleted then. Anyone with the
              link can read it, so treat it as public.
            </p>
            <div className="flex justify-end">
              <Button type="button" variant="gilt" onClick={onClose}>
                Done
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <label className="block">
              <span className="font-mono text-xs uppercase tracking-wider text-ash">
                What went wrong? (optional)
              </span>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={2}
                placeholder="Crashes a few seconds after entering Dark Hills with 3 mods on."
                className="mt-1 w-full border border-border bg-pitch/60 px-3 py-2 text-sm text-parchment placeholder:text-ash focus:border-gilt/60 focus:outline-none"
              />
            </label>

            <div className="flex flex-wrap gap-4">
              <Toggle checked={redact} onChange={setRedact} label="hide personal details" />
              <Toggle
                checked={includeLauncher}
                onChange={setIncludeLauncher}
                label="include app log"
              />
              <Toggle checked={includeMods} onChange={setIncludeMods} label="include mod list" />
            </div>

            {redact ? (
              <p className="font-serif-italic text-xs text-ash">
                Your Windows account name, home folder, e-mail addresses, Steam IDs, player names
                and IP addresses are replaced with placeholders. Check the preview — this is pattern
                matching, not a guarantee.
              </p>
            ) : (
              <p className="font-serif-italic text-xs text-crimson">
                Redaction is off. The upload will include your account name, file paths and any
                player names the loader logged.
              </p>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <MonoTag>{(report.content.length / 1024).toFixed(1)} KB</MonoTag>
              <MonoTag>{report.content.split('\n').length} lines</MonoTag>
              {report.truncated ? <MonoTag tone="gilt">oldest lines dropped</MonoTag> : null}
              <Button type="button" size="sm" onClick={() => setShowPreview((p) => !p)}>
                {showPreview ? 'Hide' : 'Preview'} exactly what is uploaded
              </Button>
            </div>

            {showPreview ? (
              <pre className="font-mono max-h-64 overflow-auto whitespace-pre-wrap break-words border border-border bg-pitch/60 p-3 text-[11px] text-parchment/90">
                {report.content}
              </pre>
            ) : null}

            {error ? (
              <div className="border border-crimson/50 bg-crimson/10 p-3">
                <p className="font-serif-italic text-sm text-parchment">{error}</p>
              </div>
            ) : null}

            <div className="flex items-center justify-end gap-2">
              <Button type="button" onClick={onClose}>
                Cancel
              </Button>
              <Button
                type="button"
                variant="gilt"
                disabled={uploading}
                onClick={() => void upload()}
              >
                {uploading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                ) : (
                  <Link2 className="h-3.5 w-3.5" aria-hidden />
                )}
                {uploading ? 'Uploading…' : 'Upload and get link'}
              </Button>
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <label className="font-mono flex cursor-pointer items-center gap-2 text-xs text-ash">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3.5 w-3.5 accent-crimson"
      />
      {label}
      {checked ? <Check className="h-3 w-3 text-gilt" aria-hidden /> : null}
    </label>
  );
}
