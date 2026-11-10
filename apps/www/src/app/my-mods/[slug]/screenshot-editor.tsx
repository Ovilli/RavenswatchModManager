'use client';

import { Accessibility } from '@dnd-kit/dom';
import {
  DragDropProvider,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from '@dnd-kit/react';
import { isSortable, useSortable } from '@dnd-kit/react/sortable';
import { MAX_MOD_PHOTOS } from '@rsmm/schemas';
import { Button, Input, Spinner } from '@rsmm/ui';
import { ImagePlus, MoreHorizontal, Plus, X } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import type { Screenshot } from '../../../lib/screenshot-gallery';
import type { useScreenshotGallery } from '../../../lib/use-screenshot-gallery';

type Gallery = ReturnType<typeof useScreenshotGallery>;

const galleryAccessibility = Accessibility.configure({
  announcements: {
    dragstart({ operation: { source } }: DragStartEvent) {
      if (isSortable(source)) return `Picked up photo ${source.initialIndex + 1}.`;
    },
    dragover({ operation: { source } }: DragOverEvent) {
      if (isSortable(source))
        return source.index === 0
          ? 'Photo moved to cover position.'
          : `Photo moved to position ${source.index + 1}.`;
    },
    dragend({ operation: { source }, canceled }: DragEndEvent) {
      if (canceled) return 'Reordering canceled. The photo order has not changed.';
      if (isSortable(source)) return `Photo dropped at position ${source.index + 1}.`;
    },
  },
});

export function ScreenshotEditor({ gallery }: { gallery: Gallery }) {
  const { screenshots, progress } = gallery;
  const input = useRef<HTMLInputElement>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const dragDepth = useRef(0);
  const [isFileOver, setFileOver] = useState(false);
  const full = screenshots.length >= MAX_MOD_PHOTOS;
  const disabled = !!progress || full;
  const [editing, setEditing] = useState<{ shot: Screenshot; trigger: HTMLButtonElement } | null>(
    null,
  );

  return (
    <section
      aria-labelledby="listing-photos-heading"
      className="relative space-y-4"
      onDragEnter={(event) => {
        if (!event.dataTransfer.types.includes('Files')) return;
        event.preventDefault();
        dragDepth.current += 1;
        setFileOver(true);
      }}
      onDragOver={(event) => {
        if (!event.dataTransfer.types.includes('Files')) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = disabled ? 'none' : 'copy';
      }}
      onDragLeave={() => {
        dragDepth.current = Math.max(0, dragDepth.current - 1);
        if (dragDepth.current === 0) setFileOver(false);
      }}
      onDrop={(event) => {
        if (!event.dataTransfer.types.includes('Files')) return;
        event.preventDefault();
        dragDepth.current = 0;
        setFileOver(false);
        void gallery.upload(Array.from(event.dataTransfer.files));
      }}
    >
      <div className="flex items-center justify-between gap-4">
        <h2 id="listing-photos-heading" className="text-xl font-semibold">
          Photos
        </h2>
        {screenshots.length > 0 ? (
          <button
            ref={addButton}
            type="button"
            aria-label="Add photos"
            disabled={disabled}
            onClick={() => input.current?.click()}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-secondary text-foreground hover:bg-secondary/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Plus className="h-5 w-5" aria-hidden="true" />
          </button>
        ) : null}
      </div>
      <input
        ref={input}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        multiple
        aria-label="Upload photos"
        hidden
        disabled={disabled}
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          event.target.value = '';
          void gallery.upload(files);
        }}
      />
      <p id="photo-reorder-help" className="sr-only">
        The first photo is the cover. Press Space to pick up a photo, use the arrow keys to move it,
        and press Space to drop. Press Escape to cancel.
      </p>
      <div
        aria-live="polite"
        className={progress ? 'space-y-2 text-sm text-muted-foreground' : 'sr-only'}
      >
        {progress ? (
          <>
            <p className="flex items-center gap-2">
              <Spinner /> Uploading {progress.index + 1} of {progress.total}…
            </p>
            <progress
              aria-label="Photo upload progress"
              className="block h-1.5 w-full accent-primary"
              value={progress.index * 100 + progress.percent}
              max={progress.total * 100}
            />
          </>
        ) : null}
        <span className="sr-only">{gallery.announcement}</span>
      </div>
      {gallery.issues.length > 0 ? (
        <div role="alert" className="space-y-2 text-sm">
          <p className="font-medium">Some photos couldn’t be added</p>
          <ul className="space-y-1 text-sm text-muted-foreground">
            {gallery.issues.map(({ file, message }, index) => (
              <li key={`${index}-${file.name}`} className="break-words">
                <span className="font-medium text-foreground">{file.name}:</span> {message}
              </li>
            ))}
          </ul>
          {gallery.retryFiles.length > 0 ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!!progress}
              onClick={() => void gallery.upload(gallery.retryFiles)}
            >
              Retry failed uploads
            </Button>
          ) : null}
        </div>
      ) : null}
      {screenshots.length > 0 ? (
        <DragDropProvider
          plugins={(defaults) =>
            defaults.map((plugin) => (plugin === Accessibility ? galleryAccessibility : plugin))
          }
          onDragEnd={(event) => {
            const { source } = event.operation;
            if (!isSortable(source)) return;
            if (!event.canceled) gallery.move(String(source.id), source.index);
            requestAnimationFrame(() => {
              if (source.element instanceof HTMLElement)
                source.element.focus({ preventScroll: true });
            });
          }}
        >
          <ol aria-label="Photo display order" className="grid grid-cols-2 gap-3 sm:gap-4">
            {screenshots.map((shot, idx) => (
              <SortablePhoto
                key={shot.url}
                shot={shot}
                idx={idx}
                gallery={gallery}
                onEdit={(trigger) => setEditing({ shot, trigger })}
                onDelete={() => {
                  gallery.remove(shot.url);
                  if (screenshots.length === 1)
                    requestAnimationFrame(() => addButton.current?.focus());
                }}
              />
            ))}
            {!full ? (
              <li className="min-w-0">
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => input.current?.click()}
                  className="flex aspect-[4/3] w-full flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-secondary/30 text-sm font-medium text-muted-foreground hover:border-foreground/60 hover:bg-secondary/50 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Plus className="h-6 w-6" aria-hidden="true" /> Add more
                </button>
              </li>
            ) : null}
          </ol>
        </DragDropProvider>
      ) : (
        <div className="flex min-h-80 flex-col items-center justify-center gap-5 rounded-xl border border-dashed border-border bg-secondary/20 px-6 py-12 text-center">
          <ImagePlus
            className="h-10 w-10 text-muted-foreground"
            strokeWidth={1.5}
            aria-hidden="true"
          />
          <div className="space-y-1.5">
            <p className="text-lg font-medium">Drag your photos here</p>
            <p className="text-sm text-muted-foreground">PNG, JPEG or WebP · Up to 8 MB each</p>
          </div>
          <Button
            ref={addButton}
            type="button"
            disabled={disabled}
            variant="secondary"
            onClick={() => input.current?.click()}
          >
            Add photos
          </Button>
        </div>
      )}
      {full ? (
        <p className="text-sm text-muted-foreground">
          Photo limit reached. Delete a photo to add another.
        </p>
      ) : null}
      {isFileOver ? (
        <div
          className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center rounded-xl border-2 border-primary bg-background/95 p-6 text-center text-lg font-medium"
          aria-live="polite"
        >
          {progress
            ? 'Please wait for your upload to finish'
            : full
              ? 'Delete a photo to make room'
              : 'Drop photos to add them'}
        </div>
      ) : null}
      {editing ? (
        <PhotoEditor
          shot={editing.shot}
          returnFocus={editing.trigger}
          onSave={(caption) => gallery.setCaption(editing.shot.url, caption)}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}
    </section>
  );
}

function SortablePhoto({
  shot,
  idx,
  gallery,
  onEdit,
  onDelete,
}: {
  shot: Screenshot;
  idx: number;
  gallery: Gallery;
  onEdit: (trigger: HTMLButtonElement) => void;
  onDelete: () => void;
}) {
  const { ref, isDragging } = useSortable({ id: shot.url, index: idx });
  return (
    <li
      ref={ref}
      // biome-ignore lint/a11y/noRedundantRoles lint/a11y/useSemanticElements: Keep list semantics instead of dnd-kit's button role around nested controls.
      role="listitem"
      aria-label={`Reorder photo ${idx + 1}${idx === 0 ? ', cover photo' : ''}`}
      aria-describedby="photo-reorder-help"
      className={`group/photo relative aspect-[4/3] min-w-0 cursor-grab select-none rounded-xl bg-secondary/40 first:col-span-2 first:aspect-video active:cursor-grabbing focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${isDragging ? 'z-20 ring-2 ring-primary' : ''}`}
    >
      <img
        src={shot.url}
        alt={shot.caption || `Photo ${idx + 1}`}
        draggable={false}
        loading={idx === 0 ? 'eager' : 'lazy'}
        className="pointer-events-none h-full w-full rounded-xl object-contain"
      />
      <span className="absolute left-3 top-3 hidden rounded-md bg-white px-3 py-1.5 text-xs font-semibold text-pitch group-first/photo:block">
        Cover photo
      </span>
      <PhotoMenu
        idx={idx}
        onEdit={onEdit}
        onMove={(index) => gallery.move(shot.url, index)}
        onDelete={onDelete}
      />
    </li>
  );
}

function PhotoMenu({
  idx,
  onEdit,
  onMove,
  onDelete,
}: {
  idx: number;
  onEdit: (trigger: HTMLButtonElement) => void;
  onMove: (index: number) => void;
  onDelete: () => void;
}) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  useEffect(() => {
    if (!open) return;
    const dismiss = () => menu.current?.hidePopover();
    document.addEventListener('scroll', dismiss, true);
    window.addEventListener('resize', dismiss);
    return () => {
      document.removeEventListener('scroll', dismiss, true);
      window.removeEventListener('resize', dismiss);
    };
  }, [open]);
  function close() {
    menu.current?.hidePopover();
    trigger.current?.focus({ preventScroll: true });
  }
  function show(last = false) {
    if (!trigger.current || !menu.current) return;
    const rect = trigger.current.getBoundingClientRect();
    menu.current.showPopover();
    const height = menu.current.offsetHeight;
    setPosition({
      top: Math.max(8, Math.min(rect.bottom + 8, window.innerHeight - height - 8)),
      left: Math.max(8, Math.min(rect.right - 208, window.innerWidth - 216)),
    });
    const items = menu.current.querySelectorAll<HTMLButtonElement>('button:not(:disabled)');
    items[last ? items.length - 1 : 0]?.focus();
  }
  return (
    <>
      <button
        ref={trigger}
        type="button"
        aria-label={`Photo ${idx + 1} options`}
        aria-haspopup="menu"
        aria-controls={id}
        aria-expanded={open}
        onClick={() => (open ? close() : show())}
        onKeyDown={(event) => {
          if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
          event.preventDefault();
          show(event.key === 'ArrowUp');
        }}
        className="absolute right-2 top-2 flex h-11 w-11 items-center justify-center rounded-full bg-white text-pitch shadow-md hover:bg-white/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:right-3 sm:top-3"
      >
        <MoreHorizontal className="h-5 w-5" aria-hidden="true" />
      </button>
      <div
        ref={menu}
        id={id}
        popover="auto"
        role="menu"
        aria-label={`Photo ${idx + 1} actions`}
        onToggle={(event) => setOpen(event.newState === 'open')}
        style={position}
        className="fixed m-0 w-52 rounded-xl bg-popover p-1.5 text-sm text-popover-foreground shadow-xl [&>button]:flex [&>button]:min-h-11 [&>button]:w-full [&>button]:items-center [&>button]:rounded-md [&>button]:px-3 [&>button]:text-left [&>button:hover]:bg-secondary [&>button:focus]:bg-secondary [&>button:focus]:outline-none [&>button:disabled]:opacity-40"
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.preventDefault();
            close();
            return;
          }
          if (event.key === 'Tab') {
            menu.current?.hidePopover();
            trigger.current?.focus();
            return;
          }
          if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
          event.preventDefault();
          const items = Array.from(
            event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'),
          );
          const current = items.indexOf(document.activeElement as HTMLButtonElement);
          const next =
            event.key === 'Home'
              ? 0
              : event.key === 'End'
                ? items.length - 1
                : (current + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
          items[next]?.focus();
        }}
      >
        <button
          type="button"
          role="menuitem"
          onClick={() => {
            close();
            if (trigger.current) onEdit(trigger.current);
          }}
        >
          Add alt-text caption
        </button>
        <button
          type="button"
          role="menuitem"
          disabled={idx === 0}
          onClick={() => {
            close();
            onMove(0);
          }}
        >
          Make cover photo
        </button>
        <button
          type="button"
          role="menuitem"
          onClick={() => {
            close();
            const tile = trigger.current?.closest('li');
            const next =
              tile?.nextElementSibling?.querySelector('button') ??
              tile?.previousElementSibling?.querySelector('button');
            next?.focus({ preventScroll: true });
            onDelete();
          }}
        >
          Delete
        </button>
      </div>
    </>
  );
}

function PhotoEditor({
  shot,
  returnFocus,
  onSave,
  onClose,
}: {
  shot: Screenshot;
  returnFocus: HTMLButtonElement;
  onSave: (caption: string) => void;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [caption, setCaption] = useState(shot.caption ?? '');
  const captionId = useId();
  useEffect(() => {
    const node = dialog.current;
    node?.showModal();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      node?.close();
      document.body.style.overflow = overflow;
      returnFocus.focus({ preventScroll: true });
    };
  }, [returnFocus]);
  return (
    <dialog
      ref={dialog}
      aria-label="Edit photo"
      onClose={() => {
        // Ignore a queued close from Strict Mode's effect cleanup if reopened.
        if (!dialog.current?.open) onClose();
      }}
      className="m-auto max-h-[90dvh] w-[calc(100%-2rem)] max-w-3xl overflow-y-auto rounded-xl bg-background p-0 text-foreground shadow-2xl backdrop:bg-black/70"
    >
      <div className="flex items-center justify-between px-5 py-3">
        <h3 className="text-lg font-semibold">Edit photo</h3>
        <button
          type="button"
          aria-label="Close photo editor"
          onClick={onClose}
          className="flex h-11 w-11 items-center justify-center rounded-full hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <X className="h-5 w-5" aria-hidden="true" />
        </button>
      </div>
      <img
        src={shot.url}
        alt={shot.caption || 'Photo preview'}
        className="max-h-[55dvh] w-full bg-secondary/30 object-contain"
      />
      <form
        className="space-y-4 p-5"
        onSubmit={(event) => {
          event.preventDefault();
          onSave(caption);
          onClose();
        }}
      >
        <div className="space-y-2">
          <label htmlFor={captionId} className="text-sm font-medium">
            Caption
          </label>
          <Input
            id={captionId}
            value={caption}
            onChange={(event) => setCaption(event.target.value)}
            placeholder="Add a caption"
            maxLength={200}
          />
        </div>
        <div className="flex justify-end gap-3">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit">Done</Button>
        </div>
      </form>
    </dialog>
  );
}
