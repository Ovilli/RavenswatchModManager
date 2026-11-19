# Shared collection cards preview

Before: `main` at `96681bfb`.
After: the `codex/standardize-collection-cards` implementation in this PR.

Each before/after pair uses a 1440 × 1000 browser viewport, the same data, appearance, and account state. Before images were captured before editing the base implementation. All cover images finished loading before capture.

- `desktop-before.png` / `desktop-after.png`: desktop Browse → Collections, expanded sidebar, English, default appearance. The same three public collections are supplied from a fixed API response.
- `web-before.png` / `web-after.png`: website `/c`, signed out, using that same public collection response. Collections now uses the registry's responsive tracks, which retain empty columns rather than stretching a short result set.
- `manage-before.png` / `manage-after.png`: website `/my-mods` with a local preview session and three public mod fixtures, including a missing cover and unpublished version. This demonstrates that management controls remain outside the shared card link. No authenticated production requests or writes were made.

Also checked web Collections at 390 × 844 and desktop Collections at 960 × 800, search filtering, keyboard navigation, localized counts, and management link destinations. Desktop captures exercise the browser UI; native installation and game launch are outside this change.
