'use client';
import { TriangleAlert } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';

export function ModPrivateOnlyTag() {
  const [open, setOpen] = useState(false);
  const warningId = useId();
  const container = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
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
    <span
      ref={container}
      className="mod-private-only-tag"
      onPointerEnter={(event) => {
        if (event.pointerType !== 'touch') setOpen(true);
      }}
      onPointerLeave={() => {
        if (!container.current?.contains(document.activeElement)) setOpen(false);
      }}
      onFocus={() => setOpen(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <button
        type="button"
        className="mod-private-only-label"
        aria-label="Private games only mod warning"
        aria-describedby={open ? warningId : undefined}
        onClick={() => setOpen(true)}
      >
        <TriangleAlert size={14} aria-hidden />
        Private games only
      </button>
      {open ? (
        <span id={warningId} role="tooltip" className="mod-private-only-warning">
          <span>
            This mod can only be used in solo and private multiplayer games because it may give an
            unfair advantage.
          </span>
        </span>
      ) : null}
    </span>
  );
}
