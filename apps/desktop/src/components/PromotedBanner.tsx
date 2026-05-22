import { useEffect, useState } from 'react';

const AD_ORIGIN =
  import.meta.env.VITE_ADS_ORIGIN ?? 'https://ravenswatch.ovilli.de';
const AD_BANNER_PATH = '/ads/banner';

/**
 * Embeds an ad slot served by the docs site as an iframe. The docs site
 * sits on a real domain so AdSense (or any other ad SDK) can run there
 * within Google's terms. The Tauri client only loads the slot via iframe.
 */
export default function PromotedBanner({ vertical }: { vertical?: boolean } = {}) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (loaded) return;
    const t = window.setTimeout(() => {
      if (!loaded) setFailed(true);
    }, 8000);
    return () => window.clearTimeout(t);
  }, [loaded]);

  const src = `${AD_ORIGIN}${AD_BANNER_PATH}`;

  if (failed) {
    return (
      <div
        className={
          vertical
            ? 'grimoire-card flex flex-col items-center gap-2 px-3 py-3 w-full'
            : 'grimoire-card flex items-center gap-3 px-3 py-2 max-w-md'
        }
      >
        <span className="font-mono text-xs uppercase tracking-[0.22em] text-ash">
          ad slot offline
        </span>
      </div>
    );
  }

  const sizeClass = vertical ? 'h-32 w-full' : 'h-20 w-full max-w-md';

  return (
    <div className={`grimoire-card overflow-hidden ${sizeClass}`}>
      <iframe
        title="Sponsored content"
        src={src}
        loading="lazy"
        sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox"
        referrerPolicy="no-referrer-when-downgrade"
        onLoad={() => setLoaded(true)}
        onError={() => setFailed(true)}
        className="h-full w-full border-0 bg-transparent"
      />
    </div>
  );
}
