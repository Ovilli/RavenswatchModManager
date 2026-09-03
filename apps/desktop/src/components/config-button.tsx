/**
 * "Configure" button for a mod that declares config fields.
 *
 * Settings used to live on the mod's STORE page, which put a local, personal
 * control on a page that is otherwise about the published mod. They then moved
 * to the Library's config view — but this button *linked* there, so editing one
 * mod's settings navigated the whole Library into a wall of every configurable
 * mod's panel. It now opens that one mod's panel in a dialog and leaves the
 * screen where it was; the toolbar's Config view remains the way to see them
 * all at once.
 *
 * `hasConfig` rides along on the mod list payload rather than being asked per
 * mod: the answer is needed for every visible row, and one `rsmm json config
 * get` spawn per installed mod to learn a boolean is not worth it. The real
 * schema (and any parse error in it) is loaded by the panel this opens.
 */
import { SlidersHorizontal, X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useT } from '../lib/i18n-react';
import { Button } from './chrome';
import { ModConfigPanel } from './mod-config-panel';

export function ConfigButton({
  modId,
  modName,
  hasConfig,
  enabled,
  onToggleEnabled,
  className,
}: {
  modId: string;
  modName?: string;
  hasConfig?: boolean;
  enabled?: boolean;
  onToggleEnabled?: () => void;
  className?: string;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const discard = useCallback(() => {
    setConfirming(false);
    setDirty(false);
    setOpen(false);
  }, []);

  // The panel has no autosave, so closing with edits pending asks first. That
  // prompt is rendered INSIDE the dialog rather than through `window.confirm`:
  // the webview can answer a native confirm without ever showing it, which
  // made the close button look dead instead of guarded.
  const close = useCallback(() => {
    if (dirty) {
      setConfirming(true);
      return;
    }
    discard();
  }, [dirty, discard]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      // Escape backs out of the discard prompt first, so it can never be the
      // key that throws the edits away.
      if (confirming) setConfirming(false);
      else close();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, close, confirming]);

  // Move focus into the dialog on open and hand it back to the trigger on
  // close. Escape is already handled above by a window listener, so this is
  // the missing half: portalled to the body, the card comes after the whole
  // app in DOM order, and without a focus move the first tab stop was the
  // sidebar rather than anything in the panel.
  const cardRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const trigger = document.activeElement as HTMLElement | null;
    cardRef.current?.focus();
    return () => {
      trigger?.focus?.();
    };
  }, [open]);

  const markDirty = useCallback((_id: string, next: boolean) => setDirty(next), []);

  if (!hasConfig) return null;
  // Icon only: the row already carries a switch, the overlay button and
  // uninstall, and a fourth labelled control overflowed it. The label lives in
  // title + aria-label so it stays reachable.
  return (
    <>
      <button
        type="button"
        className={`btn-grim shrink-0 px-2 py-1.5 ${className ?? ''}`}
        title={t("Configure — open this mod's settings")}
        aria-label={t('Configure this mod')}
        aria-haspopup="dialog"
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
      >
        <SlidersHorizontal className="h-4 w-4" />
      </button>

      {open
        ? createPortal(
            <div
              // biome-ignore lint/a11y/useSemanticElements: see ai-disclosure.tsx — <dialog>'s top-layer backdrop conflicts with the app's overlay stacking
              role="dialog"
              aria-modal="true"
              aria-label={t('Configure {name}', { name: modName ?? modId })}
              className="fixed inset-0 z-[75] flex items-center justify-center p-4 animate-fade-in"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="absolute inset-0 bg-pitch/85" onClick={close} />
              {/* Fixed-height column: header, then the only scroller. The close
                  button used to hang off the card's top edge in a centred flex,
                  so every height change the panel made (skeleton -> fields,
                  error banner appearing) re-centred the card and dragged the
                  button with it — sometimes clean off the top of the screen. */}
              <div
                ref={cardRef}
                tabIndex={-1}
                className="grimoire-card relative flex max-h-[86vh] w-[min(720px,94vw)] flex-col p-4 focus:outline-none"
              >
                <header className="flex shrink-0 items-center justify-between gap-3 pb-3">
                  <h2 className="font-fraktur truncate text-xl text-parchment">
                    {modName ?? modId}
                  </h2>
                  <button
                    type="button"
                    onClick={close}
                    className="btn-grim shrink-0 px-2 py-1.5"
                    aria-label={t('Close config')}
                    title={t('Close')}
                  >
                    <X className="h-4 w-4" />
                  </button>
                </header>

                <div className="min-h-0 flex-1 overflow-y-auto pr-1">
                  <ModConfigPanel
                    modId={modId}
                    modName={modName ?? modId}
                    enabled={enabled}
                    onToggleEnabled={onToggleEnabled}
                    onDirtyChange={markDirty}
                    frameless
                  />
                </div>

                {confirming ? (
                  <div className="ember-banner mt-3 flex shrink-0 flex-wrap items-center justify-between gap-3 px-4 py-3">
                    <span className="font-serif-italic text-base">
                      {t('Unsaved config changes. Discard them?')}
                    </span>
                    <span className="flex items-center gap-2">
                      <Button type="button" size="sm" onClick={() => setConfirming(false)}>
                        {t('Keep editing')}
                      </Button>
                      <Button type="button" size="sm" variant="danger" onClick={discard}>
                        {t('Discard')}
                      </Button>
                    </span>
                  </div>
                ) : null}
              </div>
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
