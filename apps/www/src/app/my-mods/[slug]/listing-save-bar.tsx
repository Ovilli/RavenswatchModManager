'use client';

import { Button, Spinner } from '@rsmm/ui';
import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

export function ListingSaveBar({
  saving,
  uploading,
  error,
  onSave,
  onDiscard,
}: {
  saving: boolean;
  uploading: boolean;
  error?: string | null;
  onSave: () => void;
  onDiscard: () => void;
}) {
  const bar = useRef<HTMLElement>(null);
  useEffect(() => {
    const node = bar.current;
    if (!node) return;
    const measure = () =>
      document.body.style.setProperty(
        '--listing-save-bar-height',
        `${node.getBoundingClientRect().height}px`,
      );
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    measure();
    return () => {
      observer.disconnect();
      document.body.style.removeProperty('--listing-save-bar-height');
    };
  }, []);
  return createPortal(
    <section ref={bar} aria-label="Listing changes" className="listing-save-bar">
      <div className="container px-6">
        <div className="listing-save-bar-content">
          <div className="min-w-0 flex-1">
            <output className="block text-sm font-medium">
              {saving ? 'Saving changes…' : uploading ? 'Uploading photos…' : 'Unsaved changes'}
            </output>
            {error ? (
              <p role="alert" className="mt-1 text-sm text-crimson">
                {error}
              </p>
            ) : null}
          </div>
          <div className="flex shrink-0 gap-2">
            <Button type="button" variant="outline" size="sm" disabled={saving} onClick={onDiscard}>
              Discard
            </Button>
            <Button type="button" size="sm" disabled={saving || uploading} onClick={onSave}>
              {saving ? <Spinner /> : null} Save changes
            </Button>
          </div>
        </div>
      </div>
    </section>,
    document.body,
  );
}

export function ListingLeaveDialog({
  active,
  saving,
  onStay,
  onLeave,
}: {
  active: boolean;
  saving: boolean;
  onStay: () => void;
  onLeave: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current;
    if (active && !node?.open) node?.showModal();
    else if (!active && node?.open) node.close();
    return () => node?.close();
  }, [active]);
  if (!active) return null;
  return createPortal(
    <dialog
      ref={dialog}
      aria-labelledby="leave-listing-title"
      aria-describedby="leave-listing-description"
      onCancel={(event) => {
        event.preventDefault();
        onStay();
      }}
      className="m-auto w-[calc(100%-2rem)] max-w-md space-y-4 rounded-xl border border-border bg-background p-6 text-foreground backdrop:bg-black/70"
    >
      <h2 id="leave-listing-title" className="font-display text-2xl font-bold">
        Leave this listing?
      </h2>
      <p id="leave-listing-description" className="text-sm text-muted-foreground">
        {saving
          ? 'Your listing is still saving. Stay here until the save finishes.'
          : 'Your unsaved listing changes will be lost.'}
      </p>
      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="outline" onClick={onStay}>
          Keep editing
        </Button>
        <Button type="button" variant="destructive" disabled={saving} onClick={onLeave}>
          Discard and leave
        </Button>
      </div>
    </dialog>,
    document.body,
  );
}
