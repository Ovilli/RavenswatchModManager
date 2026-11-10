'use client';

import { Button, Input, Spinner } from '@rsmm/ui';
import { ChevronLeft, ChevronRight, Trash2 } from 'lucide-react';
import { MAX_SCREENSHOTS } from '../../../lib/screenshot-gallery';
import type { useScreenshotGallery } from '../../../lib/use-screenshot-gallery';

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
        Select multiple images at once. Use the arrows to change their display order. Changes save
        automatically.
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
        <ol aria-label="Screenshot display order" className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {screenshots.map((shot, idx) => (
            <li key={shot.url} className="min-w-0 space-y-2 rounded-md border border-border/40 p-2">
              <div className="flex items-center justify-between gap-2">
                <span className="pl-1 text-xs tabular-nums text-muted-foreground">
                  {idx + 1} of {screenshots.length}
                </span>
                <div className="flex gap-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label={`Move screenshot ${idx + 1} earlier`}
                    title="Move earlier"
                    aria-disabled={idx === 0}
                    className="aria-disabled:opacity-40"
                    onClick={() => gallery.move(shot.url, -1)}
                  >
                    <ChevronLeft aria-hidden="true" className="h-4 w-4" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label={`Move screenshot ${idx + 1} later`}
                    title="Move later"
                    aria-disabled={idx === screenshots.length - 1}
                    className="aria-disabled:opacity-40"
                    onClick={() => gallery.move(shot.url, 1)}
                  >
                    <ChevronRight aria-hidden="true" className="h-4 w-4" />
                  </Button>
                </div>
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
          ))}
        </ol>
      ) : (
        <p className="py-3 text-sm text-muted-foreground">
          Add screenshots to show players what your mod looks like.
        </p>
      )}
    </div>
  );
}
