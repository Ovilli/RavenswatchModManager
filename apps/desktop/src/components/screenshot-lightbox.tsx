import { ChevronLeft, ChevronRight, X } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { useT } from '../lib/i18n-react';
import { useModalChrome } from './chrome';

/**
 * Full-screen screenshot viewer, shared by the mod page and the collection
 * page — each used to carry its own copy. Escape closes, the arrow keys page;
 * focus moves to the close button on open and back to the thumbnail that
 * opened it on close, so the viewer is reachable without tabbing through the
 * page behind it.
 *
 * @param name  the mod's name, for the alt text when a shot has no caption.
 */
export function ScreenshotLightbox({
  shots,
  idx,
  name,
  onClose,
  onPrev,
  onNext,
}: {
  shots: { url: string; caption?: string }[];
  idx: number;
  name?: string;
  onClose: () => void;
  onPrev: () => void;
  onNext: () => void;
}) {
  const t = useT();
  const closeRef = useRef<HTMLButtonElement>(null);
  // Escape is handled by the window listener below, alongside the arrows.
  useModalChrome(closeRef);
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
      else if (e.key === 'ArrowLeft') onPrev();
      else if (e.key === 'ArrowRight') onNext();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, onPrev, onNext]);

  const active = shots[idx];
  if (!active) return null;
  const label =
    active.caption ||
    (name ? t('{name} screenshot {n}', { name, n: idx + 1 }) : t('Screenshot {n}', { n: idx + 1 }));

  return (
    <dialog open aria-label={label} className="fixed inset-0 z-[90] bg-pitch/95">
      <div className="absolute inset-0 overflow-y-auto">
        <button
          type="button"
          onClick={onClose}
          className="absolute inset-0 h-full w-full cursor-default"
          aria-label={t('Close preview')}
        />
        <div className="pointer-events-none relative flex min-h-full items-center justify-center px-4 py-16 sm:px-20">
          <figure
            onClick={(e) => e.stopPropagation()}
            className="pointer-events-auto flex w-full max-w-6xl flex-col items-center gap-4"
          >
            <img
              src={active.url}
              alt={label}
              className="max-w-full rounded-md object-contain shadow-2xl"
            />
            <figcaption className="max-w-3xl text-center text-sm text-ash">
              {active.caption ||
                t('Screenshot {n} of {total}', { n: idx + 1, total: shots.length })}
            </figcaption>
            <p className="font-mono text-xs text-ash/70">
              {idx + 1} / {shots.length}
            </p>
          </figure>
        </div>
      </div>
      <button
        ref={closeRef}
        type="button"
        onClick={onClose}
        className="fixed right-4 top-4 z-20 rounded bg-oxblood/60 p-2 text-parchment transition-colors duration-150 hover:bg-oxblood"
        aria-label={t('Close')}
      >
        <X className="h-5 w-5" />
      </button>
      {shots.length > 1 ? (
        <>
          <button
            type="button"
            onClick={onPrev}
            className="fixed left-2 sm:left-4 top-1/2 z-20 -translate-y-1/2 rounded bg-oxblood/60 p-3 text-parchment transition-colors duration-150 hover:bg-oxblood"
            aria-label={t('Previous')}
          >
            <ChevronLeft className="h-6 w-6" />
          </button>
          <button
            type="button"
            onClick={onNext}
            className="fixed right-2 sm:right-4 top-1/2 z-20 -translate-y-1/2 rounded bg-oxblood/60 p-3 text-parchment transition-colors duration-150 hover:bg-oxblood"
            aria-label={t('Next')}
          >
            <ChevronRight className="h-6 w-6" />
          </button>
        </>
      ) : null}
    </dialog>
  );
}
