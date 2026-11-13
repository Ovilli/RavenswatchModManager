'use client';
import { TriangleAlert } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { ModPrivateOnlyControls } from './mod-private-only-controls';

export function ModPrivateOnlyTag({ slug }: { slug: string }) {
  const [open, setOpen] = useState(false);
  const warningId = useId();
  const popupId = useId();
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (container.current?.contains(document.activeElement)) trigger.current?.focus();
        setOpen(false);
      }
    };
    const dismissOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !container.current?.contains(event.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('keydown', dismissOnEscape);
    document.addEventListener('pointerdown', dismissOutside);
    return () => {
      document.removeEventListener('keydown', dismissOnEscape);
      document.removeEventListener('pointerdown', dismissOutside);
    };
  }, [open]);

  return (
    <div
      ref={container}
      className="mod-private-only-tag"
      onPointerEnter={(event) => {
        if (event.pointerType !== 'touch') setOpen(true);
      }}
      onPointerLeave={() => {
        if (!container.current?.contains(document.activeElement)) setOpen(false);
      }}
      onFocus={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(true);
      }}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <button
        ref={trigger}
        type="button"
        className="mod-private-only-label"
        aria-label="Private games only mod warning"
        aria-describedby={open ? warningId : undefined}
        aria-expanded={open}
        aria-controls={open ? popupId : undefined}
        onClick={() => setOpen(true)}
      >
        <TriangleAlert size={14} aria-hidden />
        Private games only
      </button>
      {open ? (
        <div id={popupId} className="mod-private-only-warning">
          <div className="mod-private-only-warning-content">
            <p id={warningId} role="tooltip">
              This mod can only be used in solo and private multiplayer games because it may give an
              unfair advantage.
            </p>
            <ModPrivateOnlyControls slug={slug} privateOnly />
          </div>
        </div>
      ) : null}
    </div>
  );
}
