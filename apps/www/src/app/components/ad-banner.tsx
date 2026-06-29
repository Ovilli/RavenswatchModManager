'use client';
import { useEffect, useRef } from 'react';

declare global {
  interface Window {
    adsbygoogle?: unknown[];
  }
}

const AD_CLIENT = 'ca-pub-9139637424510522';

interface AdBannerProps {
  /** AdSense ad-unit slot id (from the AdSense console). */
  slot: string;
  className?: string;
}

/**
 * A single responsive AdSense ad unit. The loader script lives in the root
 * layout (production only); this component renders the <ins> slot and queues
 * one fill request. In dev it renders a labelled placeholder so layout is
 * visible without loading real ads.
 */
export function AdBanner({ slot, className }: AdBannerProps) {
  const pushed = useRef(false);

  useEffect(() => {
    if (process.env.NODE_ENV !== 'production') return;
    // StrictMode mounts effects twice in dev; the ref keeps prod safe too.
    if (pushed.current) return;
    pushed.current = true;
    try {
      window.adsbygoogle = window.adsbygoogle || [];
      window.adsbygoogle.push({});
    } catch {
      // adsbygoogle not ready yet — it drains the queue when the loader runs.
    }
  }, []);

  if (process.env.NODE_ENV !== 'production') {
    return (
      <div
        className={`flex h-24 w-full items-center justify-center rounded-md border border-dashed border-border/60 text-xs text-muted-foreground ${className ?? ''}`}
        aria-hidden="true"
      >
        Ad slot {slot} (hidden in dev)
      </div>
    );
  }

  return (
    <ins
      className={`adsbygoogle block ${className ?? ''}`}
      style={{ display: 'block' }}
      data-ad-client={AD_CLIENT}
      data-ad-slot={slot}
      data-ad-format="auto"
      data-full-width-responsive="true"
    />
  );
}
