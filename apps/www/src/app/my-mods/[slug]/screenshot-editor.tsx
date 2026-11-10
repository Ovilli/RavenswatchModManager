'use client';

import { Accessibility } from '@dnd-kit/dom';
import {
  DragDropProvider,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from '@dnd-kit/react';
import { isSortable, useSortable } from '@dnd-kit/react/sortable';
import { Button, Input, Spinner } from '@rsmm/ui';
import { GripVertical, Trash2 } from 'lucide-react';
import { MAX_SCREENSHOTS, type Screenshot } from '../../../lib/screenshot-gallery';
import type { useScreenshotGallery } from '../../../lib/use-screenshot-gallery';

const galleryAccessibility = Accessibility.configure({
  announcements: {
    dragstart({ operation: { source } }: DragStartEvent) {
      if (isSortable(source)) return `Picked up screenshot ${source.initialIndex + 1}.`;
    },
    dragover({ operation: { source } }: DragOverEvent) {
      if (isSortable(source)) return `Screenshot moved to position ${source.index + 1}.`;
    },
    dragend({ operation: { source }, canceled }: DragEndEvent) {
      if (canceled) return 'Reordering canceled. The image order has not changed.';
      if (isSortable(source)) return `Screenshot dropped at position ${source.index + 1}.`;
    },
  },
});

export function ScreenshotEditor({
  gallery,
  onPreview,
}: {
  gallery: ReturnType<typeof useScreenshotGallery>;
  onPreview: (index: number) => void;
}) {
  const { screenshots, progress } = gallery;
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-medium">Screenshots</h3>
        <span className="text-xs tabular-nums text-muted-foreground">
          {screenshots.length} / {MAX_SCREENSHOTS}
        </span>
      </div>
      <p id="screenshot-help" className="text-xs leading-relaxed text-muted-foreground">
        Select multiple images at once. Drag an image by its grip to change the display order.
        Changes save automatically.
      </p>
      <p id="screenshot-reorder-help" className="sr-only">
        Press Space to pick up an image, use the arrow keys to move it, and press Space to drop.
        Press Escape to cancel.
      </p>
      <div className="space-y-2 pt-1">
        <label htmlFor="screenshot-files" className="block text-sm font-medium">
          Add screenshots
        </label>
        <input
          id="screenshot-files"
          type="file"
          accept="image/png,image/jpeg,image/webp"
          multiple
          aria-describedby="screenshot-help screenshot-limits"
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            e.target.value = '';
            void gallery.upload(files);
          }}
          disabled={!!progress || screenshots.length >= MAX_SCREENSHOTS}
          className="block w-full min-w-0 rounded text-sm text-muted-foreground file:mr-3 file:rounded-md file:border-0 file:bg-secondary file:px-3 file:py-2.5 file:text-sm file:font-medium file:text-secondary-foreground hover:file:bg-secondary/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
        />
        <p id="screenshot-limits" className="text-xs text-muted-foreground">
          {screenshots.length >= MAX_SCREENSHOTS
            ? 'Gallery full. Remove a screenshot to add another.'
            : `PNG, JPEG, or WebP · Up to 8 MB each · ${MAX_SCREENSHOTS - screenshots.length} remaining`}
        </p>
      </div>
      <div aria-live="polite" className="space-y-2 text-xs text-muted-foreground">
        {progress ? (
          <>
            <p className="flex items-center gap-2">
              <Spinner /> Uploading {progress.index + 1} of {progress.total}…
            </p>
            <p className="break-all">{progress.name}</p>
            <progress
              aria-label="Screenshot upload progress"
              className="h-1.5 w-full accent-primary"
              value={progress.index * 100 + progress.percent}
              max={progress.total * 100}
            />
          </>
        ) : null}
        {gallery.saveStatus ? <p>{gallery.saveStatus}</p> : null}
        <span className="sr-only">{gallery.announcement}</span>
      </div>
      {gallery.saveError ? (
        <div role="alert" className="space-y-2 text-sm">
          <p className="break-words text-foreground">
            Gallery changes haven’t been saved. {gallery.saveError}
          </p>
          <Button type="button" size="sm" variant="outline" onClick={() => void gallery.save()}>
            Retry save
          </Button>
        </div>
      ) : null}
      {gallery.issues.length > 0 ? (
        <div role="alert" className="space-y-2 text-sm">
          <p className="font-medium">Some images couldn’t be added</p>
          <ul className="space-y-1 text-xs text-foreground">
            {gallery.issues.map(({ file, message }, index) => (
              <li key={`${index}-${file.name}`} className="break-words">
                <span className="font-medium">{file.name}:</span> {message}
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
            if (event.canceled) return;
            const { source } = event.operation;
            if (isSortable(source)) gallery.move(String(source.id), source.index);
          }}
        >
          <ol
            aria-label="Screenshot display order"
            className="grid grid-cols-1 gap-3 sm:grid-cols-2"
          >
            {screenshots.map((shot, idx) => (
              <SortableScreenshot
                key={shot.url}
                shot={shot}
                idx={idx}
                total={screenshots.length}
                gallery={gallery}
                onPreview={onPreview}
              />
            ))}
          </ol>
        </DragDropProvider>
      ) : (
        <p className="py-3 text-sm text-muted-foreground">
          Add screenshots to show players what your mod looks like.
        </p>
      )}
    </div>
  );
}

function SortableScreenshot({
  shot,
  idx,
  total,
  gallery,
  onPreview,
}: {
  shot: Screenshot;
  idx: number;
  total: number;
  gallery: ReturnType<typeof useScreenshotGallery>;
  onPreview: (index: number) => void;
}) {
  const { ref, handleRef, isDragging } = useSortable({
    id: shot.url,
    index: idx,
    disabled: total < 2,
  });
  return (
    <li
      ref={ref}
      className={`min-w-0 space-y-2 rounded-md border bg-card p-2 ${isDragging ? 'relative z-10 border-primary' : 'border-border/40'}`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="pl-1 text-xs tabular-nums text-muted-foreground">
          {idx + 1} of {total}
        </span>
        <Button
          ref={handleRef}
          type="button"
          variant="ghost"
          size="icon"
          aria-label={`Reorder screenshot ${idx + 1}`}
          aria-describedby="screenshot-reorder-help"
          title="Drag to reorder"
          disabled={total < 2}
          className="h-11 w-11 touch-none cursor-grab active:cursor-grabbing"
        >
          <GripVertical aria-hidden="true" className="h-4 w-4" />
        </Button>
      </div>
      <button
        type="button"
        onClick={() => onPreview(idx)}
        aria-label={`Preview screenshot ${idx + 1}`}
        className="group relative block aspect-video w-full overflow-hidden rounded bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <img
          loading="lazy"
          src={shot.url}
          alt={shot.caption || `Screenshot ${idx + 1}`}
          className="h-full w-full object-contain transition-opacity group-hover:opacity-90"
        />
        <span className="absolute bottom-1 left-1 rounded bg-black/60 px-1.5 py-0.5 text-xs text-white">
          Preview
        </span>
      </button>
      <Input
        aria-label={`Caption for screenshot ${idx + 1}`}
        value={shot.caption ?? ''}
        onChange={(e) => gallery.setCaption(shot.url, e.target.value)}
        onBlur={() => void gallery.save()}
        placeholder="Caption (optional, max 200 chars)"
        maxLength={200}
      />
      <Button
        type="button"
        size="sm"
        variant="outline"
        aria-label={`Remove screenshot ${idx + 1}`}
        onClick={() => gallery.remove(shot.url)}
      >
        <Trash2 aria-hidden="true" className="h-3.5 w-3.5" /> Remove
      </Button>
    </li>
  );
}
