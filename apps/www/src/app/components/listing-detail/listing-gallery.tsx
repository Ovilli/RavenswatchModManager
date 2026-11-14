'use client';
import { ChevronLeft, ChevronRight, EyeOff, Grid2X2, ImageOff, Play, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { ModMedia } from '../../../lib/mod-presentation';
import { toEmbedUrl } from '../../../lib/video-embed';

function GalleryImage({ item, priority = false }: { item: ModMedia; priority?: boolean }) {
  const [failed, setFailed] = useState(false);
  if (failed)
    return (
      <span className="mod-media-empty">
        <ImageOff size={24} aria-hidden />
        <span>Image unavailable</span>
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

export function ListingGallery({
  media,
  name,
  nsfw = false,
}: { media: ModMedia[]; name: string; nsfw?: boolean }) {
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
        <p>No images added yet.</p>
      </div>
    );

  const renderCurrent = () => {
    if (current.kind === 'image') return <GalleryImage key={current.url} item={current} priority />;
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
        Watch video<span>Opens in a new tab</span>
      </a>
    );
  };

  return (
    <section className="mod-gallery" aria-label={`${name} images and videos`}>
      {hidden ? (
        <div className="mod-media-gate mod-media-empty">
          <EyeOff size={28} aria-hidden />
          <p>This mod contains mature content.</p>
          <button className="mod-reveal" type="button" onClick={() => setRevealed(true)}>
            Show media
          </button>
        </div>
      ) : (
        <div className="mod-mosaic" data-count={Math.min(media.length, 5)}>
          {media.slice(0, 5).map((item, index) => (
            <button
              className="mod-mosaic-tile"
              type="button"
              key={item.url}
              aria-label={`View ${item.label}`}
              onClick={() => open(index)}
            >
              {item.kind === 'image' ? (
                <GalleryImage item={item} priority={index === 0} />
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
            {media.length > 1 ? `Show all media (${media.length})` : 'View full image'}
          </button>
        </div>
      )}
      <dialog
        ref={dialog}
        className="mod-lightbox"
        aria-label={`${name} media viewer`}
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
                aria-label="Close media viewer"
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
                    <button type="button" onClick={() => move(-1)} aria-label="Previous media">
                      <ChevronLeft size={22} aria-hidden />
                    </button>
                    <span>
                      {activeIndex + 1} / {media.length}
                    </span>
                    <button type="button" onClick={() => move(1)} aria-label="Next media">
                      <ChevronRight size={22} aria-hidden />
                    </button>
                  </div>
                ) : null}
              </div>
              {media.length > 1 ? (
                <div className="mod-thumbnails" ref={thumbnails} aria-label="Choose media">
                  {media.map((item, index) => (
                    <button
                      type="button"
                      key={item.url}
                      aria-label={`Show ${item.label}`}
                      aria-pressed={index === activeIndex}
                      onClick={() => setSelected(index)}
                    >
                      {item.kind === 'image' ? (
                        <GalleryImage item={item} />
                      ) : (
                        <span>
                          <Play size={20} aria-hidden />
                          Video
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
