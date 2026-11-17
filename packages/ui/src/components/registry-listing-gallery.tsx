'use client';
import { ChevronLeft, ChevronRight, EyeOff, Grid2X2, ImageOff, Play, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { toEmbedUrl } from '../lib/video-embed';

export type RegistryMedia =
  | { kind: 'image'; url: string; label: string }
  | { kind: 'video'; url: string; label: string };

function GalleryImage({
  item,
  priority = false,
  unavailable,
}: {
  item: RegistryMedia;
  priority?: boolean;
  unavailable?: string;
}) {
  const [failed, setFailed] = useState(false);
  if (failed)
    return (
      <span className="mod-media-empty">
        <ImageOff size={24} aria-hidden />
        <span>{unavailable ?? 'Image unavailable'}</span>
      </span>
    );
  return (
    <img
      src={item.url}
      alt={item.label}
      loading={priority ? 'eager' : 'lazy'}
      fetchPriority={priority ? 'high' : 'auto'}
      onError={() => setFailed(true)}
    />
  );
}

export function RegistryListingGallery({
  media,
  name,
  nsfw = false,
  labels = {},
}: {
  media: RegistryMedia[];
  name: string;
  nsfw?: boolean;
  labels?: {
    imageUnavailable?: string;
    empty?: string;
    watchVideo?: string;
    opensInNewTab?: string;
    gallery?: string;
    matureContent?: string;
    showMedia?: string;
    view?: (label: string) => string;
    showAllMedia?: (count: number) => string;
    viewFullImage?: string;
    viewer?: string;
    close?: string;
    previous?: string;
    next?: string;
    choose?: string;
    show?: (label: string) => string;
    video?: string;
  };
}) {
  const [selected, setSelected] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const thumbnails = useRef<HTMLDivElement>(null);
  const activeIndex = Math.min(selected, Math.max(0, media.length - 1));
  const current = media[activeIndex];
  const hidden = nsfw && !revealed;
  const viewerOpen = expanded && !hidden && Boolean(current);
  const move = (direction: number) =>
    setSelected(
      (index) => (Math.min(index, media.length - 1) + direction + media.length) % media.length,
    );
  const open = (index: number) => {
    setSelected(index);
    setExpanded(true);
  };

  useEffect(() => {
    if (!viewerOpen) return;
    const selectedThumb =
      thumbnails.current?.querySelectorAll<HTMLButtonElement>('button')[activeIndex];
    if (selectedThumb && thumbnails.current) {
      const strip = thumbnails.current;
      const thumbLeft = selectedThumb.offsetLeft;
      if (thumbLeft < strip.scrollLeft) strip.scrollLeft = thumbLeft;
      else if (thumbLeft + selectedThumb.offsetWidth > strip.scrollLeft + strip.clientWidth)
        strip.scrollLeft = thumbLeft + selectedThumb.offsetWidth - strip.clientWidth;
    }
  }, [activeIndex, viewerOpen]);

  useEffect(() => {
    if (!viewerOpen) return;
    const node = dialog.current;
    node?.showModal();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      node?.close();
      document.body.style.overflow = previousOverflow;
    };
  }, [viewerOpen]);

  if (!current)
    return (
      <div className="mod-gallery mod-gallery-empty">
        <ImageOff size={24} aria-hidden />
        <p>{labels.empty ?? 'No images added yet.'}</p>
      </div>
    );

  const renderCurrent = () => {
    if (current.kind === 'image')
      return (
        <GalleryImage
          key={current.url}
          item={current}
          unavailable={labels.imageUnavailable}
          priority
        />
      );
    const embed = toEmbedUrl(current.url);
    return embed ? (
      <iframe
        key={current.url}
        src={embed}
        title={current.label}
        allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
        allowFullScreen
      />
    ) : (
      <a
        className="mod-external-video"
        href={current.url}
        target="_blank"
        rel="noopener noreferrer"
      >
        <Play size={30} aria-hidden />
        {labels.watchVideo ?? 'Watch video'}
        <span>{labels.opensInNewTab ?? 'Opens in a new tab'}</span>
      </a>
    );
  };

  return (
    <section className="mod-gallery" aria-label={labels.gallery ?? `${name} images and videos`}>
      {hidden ? (
        <div className="mod-media-gate mod-media-empty">
          <EyeOff size={28} aria-hidden />
          <p>{labels.matureContent ?? 'This mod contains mature content.'}</p>
          <button className="mod-reveal" type="button" onClick={() => setRevealed(true)}>
            {labels.showMedia ?? 'Show media'}
          </button>
        </div>
      ) : (
        <div className="mod-mosaic" data-count={Math.min(media.length, 5)}>
          {media.slice(0, 5).map((item, index) => (
            <button
              className="mod-mosaic-tile"
              type="button"
              key={item.url}
              aria-label={labels.view?.(item.label) ?? `View ${item.label}`}
              onClick={() => open(index)}
            >
              {item.kind === 'image' ? (
                <GalleryImage
                  unavailable={labels.imageUnavailable}
                  item={item}
                  priority={index === 0}
                />
              ) : (
                <span className="mod-video-preview">
                  <Play size={28} aria-hidden />
                  {item.label}
                </span>
              )}
            </button>
          ))}
          <button className="mod-show-media" type="button" onClick={() => open(0)}>
            <Grid2X2 size={16} aria-hidden />
            {media.length > 1
              ? (labels.showAllMedia?.(media.length) ?? `Show all media (${media.length})`)
              : (labels.viewFullImage ?? 'View full image')}
          </button>
        </div>
      )}
      <dialog
        ref={dialog}
        className="mod-lightbox"
        aria-label={labels.viewer ?? `${name} media viewer`}
        onClose={() => setExpanded(false)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
            event.preventDefault();
            move(event.key === 'ArrowLeft' ? -1 : 1);
          }
        }}
      >
        {viewerOpen ? (
          <div className="mod-lightbox-content">
            <div className="mod-lightbox-heading">
              <span>{name}</span>
              <button
                type="button"
                aria-label={labels.close ?? 'Close media viewer'}
                onClick={() => setExpanded(false)}
              >
                <X size={24} aria-hidden />
              </button>
            </div>
            <div className="mod-lightbox-image">{renderCurrent()}</div>
            <div className="mod-lightbox-footer">
              <div className="mod-lightbox-caption">
                <p aria-live="polite" aria-atomic="true">
                  {current.label}
                </p>
                {media.length > 1 ? (
                  <div className="mod-media-pagination">
                    <button
                      type="button"
                      onClick={() => move(-1)}
                      aria-label={labels.previous ?? 'Previous media'}
                    >
                      <ChevronLeft size={22} aria-hidden />
                    </button>
                    <span>
                      {activeIndex + 1} / {media.length}
                    </span>
                    <button
                      type="button"
                      onClick={() => move(1)}
                      aria-label={labels.next ?? 'Next media'}
                    >
                      <ChevronRight size={22} aria-hidden />
                    </button>
                  </div>
                ) : null}
              </div>
              {media.length > 1 ? (
                <div
                  className="mod-thumbnails"
                  ref={thumbnails}
                  aria-label={labels.choose ?? 'Choose media'}
                >
                  {media.map((item, index) => (
                    <button
                      type="button"
                      key={item.url}
                      aria-label={labels.show?.(item.label) ?? `Show ${item.label}`}
                      aria-pressed={index === activeIndex}
                      onClick={() => setSelected(index)}
                    >
                      {item.kind === 'image' ? (
                        <GalleryImage unavailable={labels.imageUnavailable} item={item} />
                      ) : (
                        <span>
                          <Play size={20} aria-hidden />
                          {labels.video ?? 'Video'}
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </dialog>
    </section>
  );
}
