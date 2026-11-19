import { useEffect, useRef, useState } from 'react';
import paladinPoster from '../assets/library-tome/paladin-poster.webp';

export function LibrarySpellbook() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const controller = new AbortController();
    let dispose: (() => void) | undefined;
    setReady(false);
    void import('../lib/library-tome')
      .then(async ({ mountLibraryTome }) => {
        if (controller.signal.aborted) return;
        const cleanup = await mountLibraryTome(canvas, controller.signal, (loaded) => {
          if (!controller.signal.aborted) setReady(loaded);
        });
        if (controller.signal.aborted) cleanup();
        else dispose = cleanup;
      })
      .catch(() => {
        // The illustration stays present when WebGL or the model is unavailable.
      });
    return () => {
      controller.abort();
      dispose?.();
    };
  }, []);

  return (
    <div className="empty-grimoire-book" data-ready={ready} aria-hidden="true">
      <img
        className="empty-grimoire-book-poster"
        src={paladinPoster}
        alt=""
        width={1008}
        height={720}
        draggable={false}
      />
      <canvas ref={canvasRef} className="empty-grimoire-book-canvas" />
      <span className="empty-grimoire-mote empty-grimoire-mote--one" />
      <span className="empty-grimoire-mote empty-grimoire-mote--two" />
      <span className="empty-grimoire-mote empty-grimoire-mote--three" />
    </div>
  );
}
