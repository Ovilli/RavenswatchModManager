---
name: RSMM public mod detail
description: Implemented surface guidance for browsing media, understanding a mod, and downloading its current release.
---

# Public mod-detail surface

## Overview

This document describes the public `/registry/[slug]` page. It is a surface extension of RSMM's existing dark, warm fantasy identity, not a replacement design system. Global color and typography authority remains in `src/app/globals.css`, `src/app/layout.tsx`, and the shared `packages/ui/tailwind.preset.cjs`. The author upload experience is outside this scope.

The Airbnb listing reference informs the page's composition: identity and proof, a wide media gallery, then a reading column beside an action card. The title area follows the user's Gymshark reference: tags above the name, a short description directly below the title, then download count on the left and a compact rating on the right. RSMM's palette, typefaces, and site shell remain its own. The page lets a player inspect the mod, understand its requirements, and download the current version without opening release history.

This record was compared with `mod-detail-view.tsx`, `mod-detail.css`, `mod-gallery.tsx`, `mod-actions.tsx`, and `mod-reviews.tsx` in `src/app/registry/[slug]/`, plus `src/lib/mod-presentation.ts`, `src/app/nav.tsx`, and the global sources above. Product constraints are recorded in `PRODUCT.md`.

## Colors

The page consumes the existing pitch background, parchment text, crimson actions, oxblood hover state, gilt emphasis, char borders, and two dark surface tones. These inherited CSS variables remain the source of truth; this document does not create a second palette.

Muted text on this surface uses the local warm neutral `--mod-muted` (`hsl(32 17% 68%)`). Gilt identifies keyboard focus, review stars, download icons, and the selected viewer thumbnail. The compact title-area rating uses a filled star in the text color. The mature-content label uses the existing brighter `--crimson-text` token. Near-black image wells allow letterboxing without changing author artwork.

**The Current Action Rule.** The prominent crimson control downloads the selected current release. Historical downloads and opening the desktop manager use quieter outlined treatments.

## Typography

Headings inherit Alegreya with Georgia as fallback; body and controls inherit Alegreya Sans. The existing blackletter wordmark stays in the shared shell.

| Role | Implemented treatment |
| --- | --- |
| Mod name | Bold serif (700), `clamp(30px, 3vw, 40px)`, line height 1.08; 32px at the mobile breakpoint |
| Section heading | Bold serif (700), 26px, line height 1.2; 24px on mobile |
| Download-card heading | Bold serif (700), 24px; 22px on mobile |
| Summary | 21px, line height 1.5; 20px on mobile |
| Description | 16px, line height 1.75, maximum width 72ch |
| Facts and secondary controls | Generally 13–16px; file sizes and viewer position use tabular numerals |

Long titles, author names, version strings, descriptions, and review content wrap within their columns. These are page-specific roles, not a new global type ramp.

## Layout

The desktop page is centered at a maximum width of 1120px with 32px side gutters. Breadcrumbs lead to tags above the mod name. A separate row below the name places downloads on the left and the rating on the right, followed by the full-width gallery. A section navigation row follows the gallery.

The reading column contains the description, installation requirements, project links, reviews, and collapsed version history. The right column contains the current download, version and file size, desktop-manager link, updated date, license when available, author attribution and follow control below the card, and reporting access beneath the author row. The action column is 340px wide, becoming 300px below 900px; the column gap ranges from 32px to 80px.

The shared navigation measures its header's border-box height with `ResizeObserver` and exposes it as `--site-header-height`. The section navigation sticks exactly at that measured height, keeping the two headers joined as the layout changes. The action card's sticky position and section destinations' scroll offsets use the measured height plus 80px, keeping actions and anchor headings below the navigation stack. The CSS uses a 61px fallback before the measured value is available.

At 760px and below, the page uses 20px side gutters and one column. The download card appears before the author and long reading content, using its existing document order. It is no longer sticky. The gallery shows the first complete image in a 4:3 well, with access to every item through the media viewer.

**The Download Before Detail Rule.** On small screens, preserve the download card's place immediately after the gallery and section navigation; do not push the primary action below the description or release history.

## Elevation & Depth

The download card has a borderless `--surface-2` background matching the tag badges and author initials. Its internal divider and secondary-button outline remain.

The surface uses dark tonal separation and fine borders. The download card and gallery add no drop shadow; the existing site background retains its atmospheric treatment. On this route, the shared header uses the same fully opaque background as the section navigation, with its backdrop blur removed so scrolling text cannot show through the joined headers. The native media dialog occupies the viewport on pitch with a dark backdrop.

## Shapes

The gallery and download card share gently rounded 14px corners. Main actions use 8px corners; compact media controls, historical download buttons, and thumbnail frames use approximately 6–7px corners. Tag links use 5px corners. Circular author initials preserve the familiar attribution pattern. These local shapes describe the finished page rather than redefining shared radius tokens.

Tags are borderless badges with white text on `--surface-2`, matching the author-initials background. Hover lightens the badge while preserving white text and the shared keyboard focus outline.

## Components

### Gallery and viewer

The gallery adapts its grid to one through five visible items; additional items remain accessible in the viewer. The cover comes first, followed by screenshots and videos, with duplicate URLs removed. Captions supply image labels when present. Every image, including thumbnails, uses `object-fit: contain`.

Selecting a tile or the media button opens a native modal dialog. It provides a labeled close button, Escape dismissal, previous/next controls, left/right keyboard navigation, a position count, captions, and a horizontally scrollable thumbnail strip. The selected thumbnail has a gilt outline and is brought into view as selection changes. Background scrolling is locked while the viewer is open and restored on close. Recognized video sources embed in the viewer; other video links open explicitly in a new tab.

Mature media requires the player to choose “Show media” before the gallery or viewer content is exposed. Missing images show “Image unavailable”; an empty gallery shows “No images added yet.”

**The Complete Image Rule.** Preserve the whole author image in the gallery, viewer, and thumbnails. Let the surrounding well absorb differences in aspect ratio.

### Download card

The primary link says “Download mod,” uses the real download endpoint, and has a minimum height of 48px. Inside the button, a smaller regular-weight caption beneath the icon-and-label row displays the chosen version and file size. The two rows have no extra gap and 6px vertical padding, keeping the normal button height at 48px while allowing longer content to wrap. The published latest-version match is preferred; the first returned release is the fallback. With no release, the card explains that no download is available. “Open in mod manager” remains a secondary link to the existing `rsmm://` scheme.

### Metadata and reading content

Mods with a `private-only` tag show one gilt “Private games only” badge with the warning triangle before ordinary tags. Legacy `cheat` / `cheats` and `private only` tags are recognized case-insensitively. Hover, keyboard focus, or tap shows: “This mod can only be used in solo and private multiplayer games because it may give an unfair advantage.” The popup has a black background, no border, and a soft offset drop shadow. It stays hoverable and dismisses on pointer leave, blur, Escape, or an outside tap. Publishers can add the label in the listing editor; once saved, only RSMM admins can remove it. Admins have a label control beneath the reporting action on the public mod page. The API protects the tag across metadata edits and new uploads, including concurrent writes. This label does not itself enforce in-game multiplayer restrictions.

Category belongs in the breadcrumb; tags remain links above the mod name. Download count appears only when supplied. The rating link shows one filled star, the average, and a parenthesized review count, without a denominator or extra label. The average and count share the reviews section's query; an unknown count is omitted, and an empty result says “No reviews yet.” The short description sits directly below the title; author attribution and the follow control sit beneath the download card and above Report. Dependency names link to their public mod pages, with game-build and SDK requirements grouped under “Before you install.” Updated date and license sit beside the download decision. The initial description uses the sanitized server-rendered content, preserving readable and crawlable mod information.

### Reviews and version history

Reviews retain sign-in, author/co-author restrictions, author replies, and review edit/delete behavior, with explicit loading, empty, and retry states. Rating buttons have labels, pressed state, and 44px targets. Version history is a closed native disclosure by default; its navigation link also opens the destination. Each release retains its download, date, file size, and optional release-note disclosure.

### Interaction states

Local interactive controls use a visible 2px gilt focus outline with a 4px offset; image-tile focus is drawn inside the image well. Most viewer controls have 44px targets. Hover feedback is limited to brief color, border, or opacity transitions (140–150ms); the history chevron rotates on expansion. Reduced-motion preferences disable local transitions.

## Do's and Don'ts

- **Do** preserve the inherited RSMM palette, typefaces, header, and public routes.
- **Do** keep complete artwork, the current download, and mod understanding ahead of release history.
- **Do** group requirements, attribution, and download facts with the decisions they support.
- **Do** retain actual author content and honest absent-data states.
- **Don't** introduce cropped listing art, invented compatibility claims, or fabricated ratings and download counts.
- **Don't** promote this page's listing composition, local muted color, or corner sizes into a site-wide redesign.
- **Don't** use this record to extend the redesign into author upload flows.
