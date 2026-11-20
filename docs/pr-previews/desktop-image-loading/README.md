# Desktop hero portraits and review avatars

Base: `main` at `1608f868`.

All pairs use a 1280 × 900 viewport, English, and the default appearance.
Before captures use the base component/CSS and desktop image policy; after
captures use the proposed changes. No production data was changed.

- `library-before.png` / `library-after.png`: WebKit, the built-in Library
  preview's **Fresh start** profile. Every CSS animation is paused with
  `currentTime = 0`, retaining the same per-card negative delays. The GLB
  request is blocked in both captures so the bundled book poster is stable.
- `reduced-motion-before.png` / `reduced-motion-after.png`: the same page with
  `prefers-reduced-motion: reduce`, showing all six portraits.
- `review-before.png` / `review-after.png`: Chromium, the **No Overtime Tint**
  detail page, scrolled to the public reviews. The real Skigim review and
  Google avatar URL match the reported example. Both captures use the same
  signed-out session and apply `img-src` directly from `tauri.conf.json` as
  an HTTP CSP header. A temporary browser response transform enables the
  native-only detail query. Other dev-server policy is left alone to allow HMR.

The six hero assets decode successfully even before the fix. In WebKit's
flattened rendering, the later card-back element paints over the portrait.
An explicit foreground z-index makes the portrait win that fallback paint
order. Chromium continues to cull the front when the card turns over.

The review's avatar fails before with an `img-src` CSP violation and loads
with a nonzero natural width after. The updated policy also allows the
Discord and GitHub avatar hosts used by the configured sign-in providers.

## Verification

- `pnpm --filter desktop test`: 40 files, 455 tests passed, including the new
  image-policy regression coverage.
- `pnpm --filter desktop check-types`: passed.
- `pnpm --filter desktop build:vite`: passed (existing chunk-size and module
  bundling warnings).
- `pnpm exec biome lint apps/desktop/src/lib/image-policy.test.ts`: passed.
- WebKit and Chromium smoke checks of the built production bundle, served
  with the full configured CSP: all six portraits decode, and the foreground
  paint order is present in the compiled CSS.
- Chromium pixel checks: hiding a front-facing portrait changes the rendered
  card; hiding the front face of a card rotated 180° does not change the
  rendered card, confirming that the card-back behavior still works.

These are browser-engine checks on macOS, not a native Windows/Linux package
run. The screenshots reproduce the rendering and CSP failures independently
of native installation or game state.
