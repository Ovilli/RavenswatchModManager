# Desktop design system (Grimoire)

How the desktop app looks, and the rules screens follow to stay that way. The system itself lives in code. This file says what each piece is for, so a new screen can be built from the existing pieces instead of composing its own.

- `packages/ui/src/styles.css` holds the tokens and component classes. Its comments record why each earlier treatment was removed. Read them before changing a rule.
- `packages/ui/tailwind.preset.cjs` turns the tokens into Tailwind utilities.
- `apps/desktop/src/components/chrome.tsx` holds the React helpers (`Button`, `Panel`, `MonoTag`, …).
- `apps/desktop/src/lib/appearance.ts` holds the font, scale, density and motion settings. It is the only code that writes the font and scale variables.

## Principles

1. **Dark only.** `color-scheme: dark` is set once at the root. There are no light variants.
2. **Depth comes from surface steps, not borders.** A border is spent only where something is inset or interactive.
3. **Emphasis comes from being the only saturated thing on screen.** A primary button is a flat crimson fill with no glow. Destructive actions stay quiet until hovered.
4. **Nothing moves on hover.** Hover changes colour, background or border. Press feedback is the only transform.
5. **One of each.** One focus ring, one radius family, one primary colour.
6. **Text clears WCAG AA on pitch.** Crimson is a fill and never text.

## Colour

| Token | Use | Never |
|---|---|---|
| `pitch` | The page | — |
| `oxblood` | Accent fills, hover and active washes | Text |
| `crimson` | Primary fill, active state, error border and fill | Text. `text-crimson` already resolves to the bright `--crimson-text` |
| `char` | Lines, ornament, disabled fills, scrollbar | Text |
| `ash` | Tertiary text: subtitles, hints, metadata, placeholders | — |
| `smoke` | Secondary text | — |
| `parchment` | Primary text | — |
| `gilt` | Focus ring, selection, the `gilt` tone of buttons, tags and pills | Large fills |
| `moss`, `frost` | Telling groups apart in a list (chapter, rarity) | State. State colour is gilt or crimson |

- Every colour is a token. The only literals are third-party brand marks (the Google mark on sign-in) and colours a mod declares for its own themed UI (`item-grid-field.tsx`).
- Error text is `text-crimson` at full opacity. An opacity suffix (`text-crimson/80`) dims it back towards failing contrast. `text-destructive` is a fill colour (3.05:1 on pitch) and is not used for text.
- A tinted fill (`bg-crimson/10`, `bg-oxblood/20`) marks state: error, conflict, hover, active. It is not used to make a box. Boxes come from the surfaces below.

## Surfaces

| Depth | Use | Background |
|---|---|---|
| Page | body | pitch + vignette |
| Card, panel, rail | `Panel` (`.grimoire-card`) | `--surface-1` |
| Raised: modal, popover, menu | `Panel variant="raised"` | `--surface-2` |
| Inset: log body, output, wells | `Panel variant="inset"` | pitch / 0.5 |
| Sidebar, top bar | `.surface-grain` | `--surface-1` + grain |
| Conflict / warning strip | `.ember-banner` | crimson wash |

- A container that needs its own background and border uses one of these, not a hand-composed `bg-pitch/60 border border-border`.
- **Modal backdrop:** `bg-pitch/80` on an `absolute inset-0` layer behind a raised card, opened with `animate-fade-in`. The full-screen image viewer uses `bg-pitch/95`, because it replaces the screen rather than sitting over it.
- No `backdrop-blur` on surfaces. They are opaque, and the blur forced compositing layers that hid a WebKitGTK scroll artifact (see the `body` comment in `styles.css`).
- **Exception: the in-game overlay HUD** (`components/overlay-hud.tsx`). Its card is `bg-pitch/85` with `backdrop-blur-sm`, because it sits in its own window over the running game, which should stay faintly visible through it. Nothing in the main window follows it.

## Text

**Roles.** Primary is `parchment`, secondary `smoke`, tertiary `ash`. The aliases `text-text-primary/-secondary/-tertiary` say the same thing by role.

**Faces.** Every face goes through four CSS variables, so the Appearance presets restyle the whole app.

| Class | For | Notes |
|---|---|---|
| `font-fraktur` | Headings | The display serif (Alegreya bold). The class name is historical |
| `font-serif-italic` | Nav labels, summaries, body copy in cards | Upright on purpose. Small slanted text was the hardest thing in the app to read |
| `font-serif` | Emphasised labels | Upright, weight 600 |
| `font-mono` | **Labels only**: tags, pills, field labels | Uppercased and tracked. An input with this class keeps its case |
| `font-data` | **Content**: paths, ids, log lines, CLI output, hashes, numbers | Case and spacing preserved |

**Size ramp.**

| Size | Use |
|---|---|
| `text-3xl` | Page title (`SectionHeader`) |
| `text-2xl` | Empty-state title |
| `text-xl` | Modal title, compact section title |
| `text-base` | Body |
| `text-sm` | Secondary and meta |
| `text-xs` | Tags and hints, and the floor |

Sizes are rem, so they follow the UI scale (80–150%). No arbitrary sizes below `text-xs`, and no `px` type.

**Tracking.** `font-mono` brings its own `0.08em`. Headings and eyebrows take no extra `tracking-[…]`.

## Shape

- **Radius.**
  - `rounded` (= `rounded-sm`, 6px) for buttons, inputs, chips, icons and small boxes.
  - `rounded-md` (10px) for cards, panels and modals. `.grimoire-card` sets this already.
  - `rounded-lg` for the crest only.
  - `rounded-full` for pills, switches, counters and avatars.

  `rounded-md` on a control is the card radius on the wrong thing.
- **Borders.** `border-border` for structural lines. Card and button hairlines are built into their classes. `border-gilt/…` marks selected, and `border-crimson/…` marks error or primary.

## Spacing and layout

- **Page frame.** `.rsmm-main` pads the page (`px-6 py-6 md:px-8`) and content sits in `mx-auto max-w-7xl`. Screens don't add their own outer padding.
- **Rhythm.**
  - `space-y-6` between sections.
  - `space-y-3`/`space-y-4` inside a section.
  - `gap-2` inside a control group.
  - `gap-3` between controls.
  - `gap-4`/`gap-6` between columns.
- **Panels.** `Panel` pads `p-6`. Nested or dense panels use `p-3`–`p-5`. Compact density and embedded panels (`[data-embedded]`) tighten card padding from the stylesheet, so a screen never hard-codes a dense variant.
- **Headers.** Page and panel headers use `SectionHeader` (`compact` inside a panel). Its right slot never shrinks, and the row wraps.
- **Breakpoints watch the viewport, not the content column.** At a 960px window the column is about 670px, yet `md:` fires. Prefer wrapping flex rows over breakpoint switches.

## Interaction

- **Focus.** `:focus-visible` draws a 2px gilt outline at a 2px offset, and nothing else draws a ring. A control may change its own border on focus (`.input-grim`, `.field-grim`, `.select-grim`). It never adds `focus:ring-*` and never adds `focus:outline-none`: that utility outranks `:focus-visible` and removes the only keyboard indicator. The one exception is a modal card that is `useModalChrome`'s programmatic focus target (`tabIndex={-1}`), whose own controls carry the ring.
- **Motion.**
  - 150ms `ease-grimoire` for state changes.
  - `animate-fade-in` for overlays.
  - `animate-page-in` for routes.
  - `animate-ink-stamp` for a toggle landing.

  Hover transforms are not used. If one is ever added, it must also be listed under `[data-motion="reduced"]` in `styles.css`. Durations collapse under both the in-app toggle and the OS reduced-motion setting.
- **Disabled.** `opacity-50` and `pointer-events-none`.

## Components

| Pattern | Use |
|---|---|
| Button | `Button`, `variant` default / primary / gilt / danger, `size` sm / md |
| Text or icon action (dismiss ×, inline link-action) | A raw `<button type="button">` with no box: `text-ash hover:text-parchment transition-colors duration-150` |
| On/off | `InkSwitch` |
| Copy to clipboard | `CopyButton` |
| Tag | `MonoTag`, tone default / crimson / gilt |
| Metric | `StatPill`, tone default / gilt / crimson |
| Section divider | `Fleuron` |
| Page / panel header | `SectionHeader` |
| Empty state | `EmptyState` |
| Card / panel | `Panel`, variant default / raised / inset |
| Cover art | `Cover`, `CoverPlaceholder` |
| Authored Markdown | `Markdown` |
| Search field | `.input-grim` with a leading icon. Its left padding is the icon's space |
| Text field / textarea | `.field-grim`. Face, size and width come from the call site |
| Select | `.select-grim`, or `.select-inline` inside another control |
| Nav item | `.nav-link-grim` + `.nav-icon` |
| Screenshot viewer | `ScreenshotLightbox` (`components/screenshot-lightbox.tsx`) |
| Modal | A `fixed inset-0` overlay containing the backdrop above and a raised card. The card has `role="dialog"`, `aria-modal="true"` and a label, and calls `useModalChrome(focusRef, onClose)` for Escape and for moving focus in and back out |

The shadcn-style components in `packages/ui/src/components/` serve the website. The desktop app uses its own helpers above.

## Layers

Overlay z-index, lowest to highest:

| z | Overlay |
|---|---|
| 30 | Top bar |
| 40 | Window controls |
| 50 | Command palette |
| 70 | Dialogs |
| 75 | Changelog, mod config |
| 80 | Updater |
| 85 | AI disclosure |
| 90 | Screenshot viewer |

A new overlay takes its place in this order.
