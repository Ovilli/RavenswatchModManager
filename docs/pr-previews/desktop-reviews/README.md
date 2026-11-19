# Shared desktop reviews

Before: `main` at `96681bfb` (the PR's starting base).
After: the review implementation in this PR.

All before/after pairs use 1280 × 1000 viewports, the same More Choices listing,
fixture review, signed-in player, English locale, and default appearance. The
collection fixture is Build Variety with that same mod. `minimum-window.jpg`
uses the desktop app's 960 × 600 minimum window size.

Desktop before images were captured from the untouched base before editing.
Web before uses the base branch's review components with the same local data.
Desktop captures run the Vite browser preview; a temporary preview transform
enables the otherwise native-only mod detail query. API and session responses,
including all writes, are local fixtures. No test reviews were posted to the
live registry. These screenshots do not claim native Windows/Linux execution.

- `mod-*`, `collection-*`, `web-*`: comparable before/after page states.
- `write-review.jpg`: shared composer, review list, rating, and author reply.
- `saved-review.jpg`: saved review with update/delete controls and new average.
- `author-reply.jpg`: author editing a reply; self-review is unavailable.
- `collection-review.jpg`: the same shared UI on a collection.
- `minimum-window.jpg`: shared detail layout responds to available content width.

Browser checks covered review create/update/delete (including cancel), author
reply update/delete, collection review creation, signed-out sign-in navigation,
and a web edit appearing in the desktop after window focus. Unit tests cover
credentialed requests to both existing endpoint families, cache bypass after
writes, and the shared reader/reviewer/author/loading states.
