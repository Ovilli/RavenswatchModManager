# Desktop design system (Grimoire)

How the desktop app looks, and the rules screens follow to stay that way. The system itself lives in code. This file says what each piece is for, so a new screen can be built from the existing pieces instead of composing its own.

- `packages/ui/src/styles.css` holds the tokens and component classes. Its comments record why each earlier treatment was removed. Read them before changing a rule.
- **The web registry is the master style for search and filters.** `packages/ui/src/registry.css` and the shared `RegistrySearchBar`, `RegistryFilterDialog`, and `RegistryResultsControls` components own their visuals on web and desktop. This includes the desktop global search/command palette. Where these patterns differ from the generic desktop defaults below, the registry takes precedence. Change the shared implementation rather than adding desktop-only size, radius, color, or surface overrides.
- `packages/ui/tailwind.preset.cjs` turns the tokens into Tailwind utilities.
- `apps/desktop/src/components/chrome.tsx` holds the React helpers (`Button`, `Panel`, `MonoTag`, …).
- `apps/desktop/src/desktop.css` gives desktop titles their white `--text-title` color, including headings in shared components.
- `apps/desktop/src/lib/appearance.ts` holds the font, scale, density and motion settings. It is the only code that writes the font and scale variables.

## Principles

1. **Dark only.** `color-scheme: dark` is set once at the root. There are no light variants.
2. **Depth comes from surface steps, not borders.** A border is spent only where something is inset or interactive.
3. **Emphasis comes from being the only saturated thing on screen.** A primary button is a flat crimson fill with no glow. Destructive actions stay quiet until hovered.
4. **Nothing moves on hover.** Hover changes colour, background or border. Press feedback is the only transform.
5. **Shared patterns stay shared.** The registry owns search/filter patterns across web and desktop; the desktop shell uses the Grimoire defaults for its remaining controls.
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
| `text-title` | White titles and headings, scoped to the desktop app | Body copy and controls |
| `gilt` | Focus ring, selection, the `gilt` tone of buttons, tags and pills | Large fills |
| `moss`, `frost` | Telling groups apart in a list (chapter, rarity) | State. State colour is gilt or crimson |

- Desktop-specific colours use tokens. Shared registry patterns retain their canonical muted text and backdrop colours; third-party brand marks and mod-authored themed colours also keep their own values.
- Error text is `text-crimson` at full opacity. An opacity suffix (`text-crimson/80`) dims it back towards failing contrast. `text-destructive` is a fill colour (3.05:1 on pitch) and is not used for text.
- A tinted fill (`bg-crimson/10`, `bg-oxblood/20`) marks state: error, conflict, hover, active. It is not used to make a box. Boxes come from the surfaces below.

## Surfaces

| Depth | Use | Background |
|---|---|---|
| Page | body | pitch + vignette |
| Card, panel, rail | `Panel` (`.grimoire-card`) | `--surface-1` |
| Raised: modal, popover, menu | `Panel variant="raised"` | `--surface-2` |
| Registry filters and global search | Shared registry dialog styles | `--surface-1`, registry border and backdrop |
| Inset: log body, output, wells | `Panel variant="inset"` | pitch / 0.5 |
| Sidebar | `.app-sidebar` | `--surface-1` + the update prompt's raster grain |
| Conflict / warning strip | `.ember-banner` | crimson wash |

- A container that needs its own background and border uses one of these, not a hand-composed `bg-pitch/60 border border-border`.
- **Modal backdrop:** Generic desktop dialogs use `bg-pitch/80` behind a raised card, opened with `animate-fade-in`. Registry filters and global search use the registry's shared backdrop. The full-screen image viewer uses `bg-pitch/95`, because it replaces the screen rather than sitting over it.
- No `backdrop-blur` on surfaces. They are opaque, and the blur forced compositing layers that hid a WebKitGTK scroll artifact (see the `body` comment in `styles.css`).
- **Exception: the in-game overlay HUD** (`components/overlay-hud.tsx`). Its card is `bg-pitch/85` with `backdrop-blur-sm`, because it sits in its own window over the running game, which should stay faintly visible through it. Nothing in the main window follows it.
- **Exception: the startup update prompt** (`components/cli-update-dialog.css`). Its raised surface fades from crimson on the left through oxblood to pitch on the right, with a fine raster grain and a faded square grid. Layered inset lighting gives the top left a narrow parchment reflection at 18% opacity and a softer crimson glow at 8%, with faint bottom-right shading and a soft black drop shadow. There is no solid frame, and the lighting stays constant on hover. This treatment is local to the update prompt. Copy uses parchment for contrast against the colored surface; the close button uses a parchment circle with an oxblood icon.

## Text

**Roles.** Desktop-specific titles and headings are white (`--text-title`). Registry dialogs retain their shared foreground heading color. Primary body text is `parchment`, secondary `smoke`, tertiary `ash`. The aliases `text-text-primary/-secondary/-tertiary` say the same thing by role. Desktop title colors are applied centrally, including legacy display titles still carrying `text-parchment`; mod-authored item colors keep their explicit theme.

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

  These are defaults for desktop-specific controls. Shared registry search fields and the global search panel use 8px corners. Registry filter chips use pill radii, filter dialogs use 16px corners, and their icon controls use 8px corners. Browse and global search retain these canonical registry shapes.
- **Borders.** `border-border` for structural lines. Card and button hairlines are built into their classes. `border-gilt/…` marks selected, and `border-crimson/…` marks error or primary.

## Spacing and layout

- **Page frame.** `.rsmm-main` pads the page (`px-6 py-6 md:px-8`) and content sits in `mx-auto max-w-7xl`. Screens don't add their own outer padding.
- **Native window chrome.** A transparent, non-shrinking `h-12` drag region sits above the main content in both sidebar states, with window controls over its right edge. Main content uses `pt-2` beneath it. Keep this region in flow so update banners stay below it and remain clickable.
- **Sidebar footer.** Launch Modded, Settings, then Sign in/account. Settings is a direct navigation link; Commands and Log live in the account menu. The collapsed rail keeps a visible launch icon and Settings gear, with names in their hover/focus tooltips. The launch disclosure appears only when expanded; Launch Vanilla is also available through the command palette.
- **Browse toolbar.** Reuse the web registry's search, filter, sort, and view controls without restyling them. The shared search/filter bar is 40px tall with an 8px radius and 32px icon/filter controls. The desktop toolbar may wrap to fit the available content width.
- **Browse mod grid.** Web and desktop use `.registry-grid` from `packages/ui/src/registry.css`, including the shared `RegistryGridSkeleton`. Do not add local grid breakpoints or gap utilities. It fits one to five columns to the available content width, accounting for the sidebar, with a 280px preferred minimum card width, 32px column gaps and 48px row gaps. The grid caps at 1920px; filtered results retain their track widths. Card content uses 24px above the body, 16px between sections, and 8px within tag/stat groups. These measurements are rem-based on a 4px scale and follow Appearance scaling. Artwork remains 16:9 with a centered cover crop. List spacing also lives in the shared `.registry-list` rule.
- **Global search.** The command palette uses `RegistrySearchBar` as the full-width, 40px top row of one 8px-radius panel, with results immediately below it. The shared registry dialog styles own its surface, border, and backdrop; its header has no nested input border or inset container. Result rows match the sidebar navigation's lightened hover and selected surfaces: char at 50%/55%, with a subtle parchment/gilt border. Keep command navigation, keyboard behavior, and desktop font/scale preferences intact.
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
| Browse and global search | `RegistrySearchBar` + shared registry styles; global search supplies combobox semantics and keyboard navigation |
| Other desktop search fields | `.input-grim` with a leading icon |
| Browse filters | `RegistryFilterDialog` + shared registry styles |
| Text field / textarea | `.field-grim`. Face, size and width come from the call site |
| Select | `.select-grim`, or `.select-inline` inside another control |
| Nav item | `.nav-link-grim` + `.nav-icon` |
| Screenshot viewer | `ScreenshotLightbox` (`components/screenshot-lightbox.tsx`) |
| Modal | A `fixed inset-0` overlay containing the backdrop above and a raised card. The card has `role="dialog"`, `aria-modal="true"` and a label, and calls `useModalChrome(focusRef, onClose)` for Escape and for moving focus in and back out |

The shadcn-style primitives in `packages/ui/src/components/` serve the website. Registry components in that package are shared with the desktop app; other desktop controls use the helpers above.

### Private games only

Registry mods carrying a protected private-only tag use `PrivateGamesOnlyBadge` in browse cards, browse rows, and both detail layouts. Reuse the shared tag classifier so legacy aliases receive the same treatment. The warning remains visible regardless of the ordinary two-tag card limit; raw restriction tags are not repeated in the ordinary tag list.

This badge matches the website: sentence-case gilt text, a warning triangle, and a gilt wash. Its translated explanation says the mod **may** give an unfair advantage. Hover, keyboard focus, or tap opens a black, borderless tooltip with a soft drop shadow (a deliberate exception to the usual raised-surface treatment). It is portaled outside scrolling panels, clamped to the viewport, and flips above the badge when needed. Escape, blur, outside press, and resizing dismiss it. Scrolling dismisses hover warnings; a focused badge keeps its warning anchored while visible. Activating the badge does not open the surrounding mod card or row. Text sizes follow the app's UI scale.

Sidebar tooltips use the same dark tooltip treatment with `--radius-sm`. The Search tooltip names both mods and commands and includes the Ctrl+K shortcut; the Browse search field filters the registry only.

## Layers

Overlay z-index, lowest to highest:

| z | Overlay |
|---|---|
| 30 | Native drag region |
| 40 | Window controls |
| 45 | Sidebar tooltips |
| 50 | Command palette |
| 70 | Dialogs |
| 75 | Changelog, mod config |
| 80 | Updater |
| 85 | AI disclosure |
| 90 | Screenshot viewer |

A new overlay takes its place in this order.
