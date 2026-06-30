# AdSense setup (apps/www)

Operational notes for the Google AdSense integration on rsmm.me. Most of this is
already wired in code; the remaining work is **console configuration** that can't
live in the repo.

## What's already in code

| Piece | Location |
|-------|----------|
| Loader script (prod only) | `src/app/layout.tsx` — `<Script src=".../adsbygoogle.js?client=ca-pub-9139637424510522">` |
| Site-ownership meta tag | `src/app/layout.tsx` — `metadata.other['google-adsense-account']` |
| Ad unit component | `src/app/components/ad-banner.tsx` (renders `<ins class="adsbygoogle">`, dev shows a placeholder) |
| `ads.txt` | `public/ads.txt` |
| CSP allowances | `next.config.mjs` (`pagead2.googlesyndication.com`, etc.) |
| Privacy / cookies disclosure | `src/app/privacy/page.tsx` §7 |

Publisher ID: **`ca-pub-9139637424510522`** (single source of truth is
`AD_CLIENT` in `ad-banner.tsx` + the loader/meta in `layout.tsx` — keep them in sync).

## Required console step — GDPR consent (CMP)

Google requires a **certified Consent Management Platform** to serve ads to
EEA / UK / Switzerland traffic. We use **Google's own CMP (Funding Choices /
"Privacy & messaging")** — no banner code in this repo; Google injects and manages
the prompt and wires Google Consent Mode automatically.

To enable:

1. AdSense console → **Privacy & messaging**.
2. Create a **GDPR message** (and an optional CCPA/US-states message).
3. Target it at the `rsmm.me` site, publish.
4. Google serves the prompt to EEA/UK visitors via the existing `adsbygoogle.js`
   loader — nothing else to deploy.

The privacy policy (§7) already promises this prompt, so the message **must** be
published for the policy to be accurate.

> Do **not** also add a custom cookie banner — it would double-prompt and can
> conflict with Funding Choices' Consent Mode signalling.

## Approval checklist

- [ ] Site live on the apex domain with original content (registry + guides).
- [ ] Funding Choices GDPR message published (see above).
- [ ] `ads.txt` reachable at `https://rsmm.me/ads.txt` and lists the pub ID.
- [ ] Privacy Policy + Contact + About reachable from the footer (they are).
- [ ] Content Policy / DMCA page reachable from the footer (`/dmca`) — required for a
      user-generated-content site running ads; shows a takedown process for
      copyrighted/infringing uploads.
- [ ] No "under construction" / placeholder pages indexed.
