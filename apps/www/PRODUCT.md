# RSMM website

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Ravenswatch players browse mods, understand what they change, and download them or open them in the desktop mod manager. Authors publish and maintain mod listings.

## Product Purpose

Make community mods discoverable and usable. On a mod page, players need to understand the mod and find its download without navigating release history.

## Capabilities and Constraints

- Next.js website backed by the RSMM API, sharing components with the desktop application.
- Listings contain a cover image, optional screenshots with captions, videos, description, tags, dependencies, versions, and reviews.
- Preserve public URLs, author attribution, download links, app links, moderation, sensitive-content handling, and crawlable descriptions.
- Current design scope includes the registry explore page and public mod detail pages. The author upload experience is outside this scope.

## Evidence on Hand

Existing public mod records and author-supplied artwork. Do not invent screenshots, compatibility claims, or review statistics for real mods.

## Product Principles

- Prioritize understanding the mod and downloading the current release.
- Show complete images on mod detail pages rather than cropping away information. Registry cards share the homepage card component and image treatment.
- Group metadata with the decision it informs.
- Keep release history accessible without making it the default experience.
- On the registry, retain global navigation above a compact, pinned toolbar with the result count, centered search, and sort/view controls. Put Filters inside the search field and all filter options in its modal. Use a full-width card grid capped at four columns.
