import { NextResponse } from 'next/server';

export const runtime = 'edge';
export const dynamic = 'force-static';

const PUBLISHER_ID =
  process.env.NEXT_PUBLIC_ADSENSE_PUBLISHER_ID ?? 'ca-pub-9139637424510522';
const AD_SLOT =
  process.env.NEXT_PUBLIC_ADSENSE_BANNER_SLOT ?? '1934448674';

const ENABLED =
  PUBLISHER_ID.startsWith('ca-pub-') && PUBLISHER_ID !== 'ca-pub-0000000000000000';

const adsenseHead = ENABLED
  ? `<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${PUBLISHER_ID}" crossorigin="anonymous"></script>`
  : '';

const adsenseBody = ENABLED
  ? `
    <ins class="adsbygoogle"
         style="display:block;width:100%;height:100%"
         data-ad-client="${PUBLISHER_ID}"
         data-ad-slot="${AD_SLOT}"
         data-ad-format="auto"
         data-full-width-responsive="true"></ins>
    <script>(adsbygoogle = window.adsbygoogle || []).push({});</script>
  `
  : `<p class="placeholder">ad slot · awaiting AdSense</p>`;

const html = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>RSMM ad slot</title>
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <style>
      :root { color-scheme: dark; }
      html, body { margin: 0; padding: 0; height: 100%; background: transparent; font-family: system-ui, sans-serif; }
      .slot { display: flex; align-items: center; justify-content: center; height: 100%; width: 100%; }
      .placeholder { color: #9b8f6b; font-size: 12px; letter-spacing: 0.22em; text-transform: uppercase; font-family: ui-monospace, monospace; }
      ins.adsbygoogle { display: block; width: 100%; height: 100%; }
    </style>
    ${adsenseHead}
  </head>
  <body>
    <div class="slot">${adsenseBody}</div>
  </body>
</html>`;

export function GET() {
  return new NextResponse(html, {
    status: 200,
    headers: {
      'content-type': 'text/html; charset=utf-8',
      'cache-control': 'public, max-age=300, s-maxage=300',
    },
  });
}
