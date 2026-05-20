import React, { useEffect, useState } from 'react';
import { Button } from './chrome';

type Promo = {
  id: string;
  title: string;
  description?: string;
  image?: string;
  url: string;
  sponsor?: string;
};

const FALLBACK: Promo[] = [
  {
    id: 'partner-1',
    title: 'Support the Modding Community',
    description: 'Check out curated tools and partner content hand-picked for Ravenswatch mod authors.',
    image: undefined,
    url: 'https://github.com/your-org',
    sponsor: 'RSMM',
  },
];

const STORAGE_KEY = 'rsmm.promos.v1';
const TTL = 1000 * 60 * 60 * 24; // 24h

export default function PromotedBanner({ vertical }: { vertical?: boolean } = {}) {
  const [promo, setPromo] = useState<Promo | null>(null);

  useEffect(() => {
    let mounted = true;

    async function load() {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) {
          const parsed = JSON.parse(raw);
          if (Date.now() - parsed.ts < TTL && parsed.data && parsed.data.length) {
            if (mounted) setPromo(parsed.data[0]);
            return;
          }
        }

        // try remote fetch from /promos.json (served by frontend/public)
        try {
          const resp = await fetch('/promos.json', { cache: 'no-store' });
          if (resp.ok) {
            const data: Promo[] = await resp.json();
            if (data && data.length) {
              localStorage.setItem(STORAGE_KEY, JSON.stringify({ ts: Date.now(), data }));
              if (mounted) setPromo(data[0]);
              return;
            }
          }
        } catch (e) {
          // ignore and fall back
        }

        // fallback to embedded promos
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ ts: Date.now(), data: FALLBACK }));
        if (mounted) setPromo(FALLBACK[0]);
      } catch (err) {
        if (mounted) setPromo(FALLBACK[0]);
      }
    }

    load();
    return () => {
      mounted = false;
    };
  }, []);

  if (!promo) return null;

  const openLink = async (url: string) => {
    try {
      // Avoid dynamic import that Vite may try to pre-bundle. Use the Tauri global bridge when available.
      // window.__TAURI__ is injected in the Tauri webview; check for shell.open
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const tauri: any = (window as any).__TAURI__;
      if (tauri && tauri.shell && typeof tauri.shell.open === 'function') {
        await tauri.shell.open(url);
        return;
      }
    } catch (e) {
      // ignore
    }

    // fallback to browser open
    window.open(url, '_blank', 'noopener');
  };

  if (vertical) {
    return (
      <div className="grimoire-card flex flex-col items-center gap-2 px-3 py-3 w-full">
        <div className="cover-placeholder w-14 h-14 flex items-center justify-center text-sm">{promo.sponsor ?? 'Ad'}</div>
        <div className="text-center">
          <div className="font-fraktur text-sm text-parchment">{promo.title}</div>
          {promo.description ? <div className="text-sm text-smoke font-serif-italic">{promo.description}</div> : null}
        </div>
        <div>
          <Button type="button" size="sm" onClick={() => openLink(promo.url)}>
            Learn
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="grimoire-card flex items-center gap-3 px-3 py-2 max-w-md">
      <div className="flex-0 w-12 h-12 cover-placeholder flex items-center justify-center text-sm">{promo.sponsor ?? 'Ad'}</div>
      <div className="flex-1">
        <div className="flex items-baseline justify-between gap-3">
          <div>
            <div className="font-fraktur text-sm text-parchment">{promo.title}</div>
            {promo.description ? <div className="text-sm text-smoke font-serif-italic">{promo.description}</div> : null}
          </div>
          <div className="ml-2">
            <Button type="button" size="sm" onClick={() => openLink(promo.url)}>
              Learn
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
