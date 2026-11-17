import { type RefObject, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

/** One tooltip layer for sidebar controls, outside its scrolling nav. */
export function SidebarTooltip({
  sidebarRef,
}: {
  sidebarRef: RefObject<HTMLElement | null>;
}) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const label = anchor?.dataset.sidebarTooltip;
  const shortcut = anchor?.dataset.sidebarTooltipShortcut;
  const side = anchor?.dataset.sidebarTooltipSide ?? 'right';

  useEffect(() => {
    const sidebar = sidebarRef.current;
    if (!sidebar) {
      setAnchor(null);
      return;
    }
    const show = (event: Event) => {
      if (event instanceof PointerEvent && event.pointerType === 'touch') return;
      const target =
        event.target instanceof Element
          ? event.target.closest<HTMLElement>('[data-sidebar-tooltip]')
          : null;
      setAnchor(target?.getAttribute('aria-expanded') === 'true' ? null : target);
    };
    const leave = (event: MouseEvent | FocusEvent) => {
      const target = event.relatedTarget;
      if (target instanceof Node && tooltipRef.current?.contains(target)) return;
      if (target instanceof Element && target.closest('[data-sidebar-tooltip]')) return;
      setAnchor(null);
    };
    const dismiss = () => setAnchor(null);
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') dismiss();
    };
    sidebar.addEventListener('pointerover', show);
    sidebar.addEventListener('pointerout', leave);
    sidebar.addEventListener('focusin', show);
    sidebar.addEventListener('focusout', leave);
    sidebar.addEventListener('click', dismiss);
    document.addEventListener('keydown', keydown);
    document.addEventListener('scroll', dismiss, true);
    window.addEventListener('resize', dismiss);
    return () => {
      sidebar.removeEventListener('pointerover', show);
      sidebar.removeEventListener('pointerout', leave);
      sidebar.removeEventListener('focusin', show);
      sidebar.removeEventListener('focusout', leave);
      sidebar.removeEventListener('click', dismiss);
      document.removeEventListener('keydown', keydown);
      document.removeEventListener('scroll', dismiss, true);
      window.removeEventListener('resize', dismiss);
    };
  }, [sidebarRef]);

  useLayoutEffect(() => {
    if (!anchor || !label || !tooltipRef.current) return;
    const place = () => {
      if (!tooltipRef.current) return;
      const trigger = anchor.getBoundingClientRect();
      const tooltip = tooltipRef.current.getBoundingClientRect();
      setPosition({
        left: Math.max(
          8,
          Math.min(
            side === 'bottom' ? trigger.right - tooltip.width : trigger.right,
            window.innerWidth - tooltip.width - 8,
          ),
        ),
        top: Math.max(
          8,
          Math.min(
            side === 'bottom'
              ? trigger.bottom
              : trigger.top + (trigger.height - tooltip.height) / 2,
            window.innerHeight - tooltip.height - 8,
          ),
        ),
      });
    };
    place();
    const observer = new ResizeObserver(place);
    observer.observe(anchor);
    observer.observe(tooltipRef.current);
    return () => observer.disconnect();
  }, [anchor, label, side]);

  if (!anchor || !label) return null;

  return createPortal(
    <div
      ref={tooltipRef}
      role="tooltip"
      className="sidebar-tooltip"
      data-side={side}
      style={position}
      onPointerLeave={(event) => {
        if (!(event.relatedTarget instanceof Node && anchor.contains(event.relatedTarget)))
          setAnchor(null);
      }}
    >
      <span>
        {label}
        {shortcut ? (
          <kbd className="rounded bg-parchment/10 px-1.5 py-0.5 font-data text-xs text-ash">
            {shortcut}
          </kbd>
        ) : null}
      </span>
    </div>,
    document.body,
  );
}
