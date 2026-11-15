'use client';
import type { ModVersion } from '@rsmm/schemas';
import { ArrowDownToLine, ExternalLink, Loader2, X } from 'lucide-react';
import Link from 'next/link';
import { type MouseEvent, useEffect, useId, useRef, useState } from 'react';
import { getApiUrl } from '../../../lib/api-url';
import { watchAppLaunch } from '../../../lib/app-launch';
import { formatFileSize } from '../../../lib/mod-presentation';
import type { InstallerDownloads } from '../../../lib/releases';

function isPlainClick(event: MouseEvent<HTMLAnchorElement>) {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

export function ModActions({
  slug,
  version,
  managerDownloads,
}: { slug: string; version?: ModVersion; managerDownloads: InstallerDownloads }) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [opening, setOpening] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const returnFocus = useRef<HTMLAnchorElement>(null);
  const stopLaunch = useRef<(() => void) | null>(null);
  const titleId = useId();
  const descriptionId = useId();
  const appUrl = `rsmm://mods/${encodeURIComponent(slug)}`;

  useEffect(() => () => stopLaunch.current?.(), []);

  useEffect(() => {
    const node = dialog.current;
    if (!dialogOpen || !node) return;
    node.showModal();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      node.close();
      document.body.style.overflow = overflow;
    };
  }, [dialogOpen]);

  function openManager(event: MouseEvent<HTMLAnchorElement>) {
    if (!isPlainClick(event)) return;
    if (opening) {
      event.preventDefault();
      return;
    }
    if (!event.currentTarget.closest('dialog')) returnFocus.current = event.currentTarget;
    dialog.current?.close();
    setDialogOpen(false);
    stopLaunch.current?.();
    setOpening(true);
    stopLaunch.current = watchAppLaunch(
      () => setDialogOpen(true),
      () => setOpening(false),
    );
    // Keep the native link navigation in this click so the browser can ask
    // permission to open RSMM. It also remains usable without JavaScript.
  }

  function closeDialog() {
    dialog.current?.close();
    setDialogOpen(false);
    returnFocus.current?.focus({ preventScroll: true });
  }

  const downloadUrl = version
    ? `${getApiUrl().replace(/\/+$/, '')}/api/mods/${encodeURIComponent(slug)}/${encodeURIComponent(version.version)}/download`
    : null;
  return (
    <div className="mod-install">
      {version && downloadUrl ? (
        <>
          <a className="mod-download" href={downloadUrl}>
            <ArrowDownToLine size={20} aria-hidden />
            <span className="mod-download-copy">
              <span className="mod-download-label">Download mod</span>
              <span className="mod-download-meta">
                <span>Version {version.version}</span>
                <span aria-hidden>·</span>
                <span>{formatFileSize(version.sizeBytes)}</span>
              </span>
            </span>
          </a>
          <a className="mod-open-app" href={appUrl} onClick={openManager} aria-disabled={opening}>
            {opening ? (
              <Loader2 size={17} className="animate-spin motion-reduce:animate-none" aria-hidden />
            ) : (
              <ExternalLink size={17} aria-hidden />
            )}
            <output>{opening ? 'Opening RSMM…' : 'Open in mod manager'}</output>
          </a>
        </>
      ) : (
        <div className="mod-no-download">
          <strong>No download available yet</strong>
          <p>The author hasn’t published a downloadable version.</p>
        </div>
      )}
      {dialogOpen ? (
        <dialog
          ref={dialog}
          className="mod-manager-dialog"
          aria-labelledby={titleId}
          aria-describedby={descriptionId}
          onCancel={(event) => {
            event.preventDefault();
            closeDialog();
          }}
        >
          <div className="mod-manager-heading">
            <h2 id={titleId}>Didn’t open?</h2>
            <button
              type="button"
              className="mod-manager-close"
              aria-label="Close download options"
              onClick={closeDialog}
            >
              <X size={20} aria-hidden />
            </button>
          </div>
          <p id={descriptionId} className="mod-manager-description">
            If RSMM isn’t installed yet, choose your system to download it.
          </p>
          <div className="mod-manager-downloads">
            <a
              className="mod-manager-platform"
              href={managerDownloads.windows ?? '/download#windows'}
            >
              <ArrowDownToLine size={20} aria-hidden />
              <span>
                <strong>
                  {managerDownloads.windows ? 'Download for Windows' : 'Windows download options'}
                </strong>
                <span>Windows 10 / 11 · 64-bit</span>
              </span>
            </a>
            <a className="mod-manager-platform" href={managerDownloads.linux ?? '/download#linux'}>
              <ArrowDownToLine size={20} aria-hidden />
              <span>
                <strong>
                  {managerDownloads.linux ? 'Download for Linux' : 'Linux download options'}
                </strong>
                <span>Linux / Steam Deck</span>
              </span>
            </a>
          </div>
          <p className="mod-manager-next-step">
            After installing, return here to open this mod in RSMM.
          </p>
          <div className="mod-manager-footer">
            <a href={appUrl} onClick={openManager}>
              <ExternalLink size={16} aria-hidden />
              Already installed? Try again
            </a>
            <Link href="/download">Installation help</Link>
          </div>
        </dialog>
      ) : null}
    </div>
  );
}
