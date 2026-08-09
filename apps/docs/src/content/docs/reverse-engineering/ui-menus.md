---
title: UI & the book menu
description: The game's entity-component UI, the fixed five-tab book, the button-press choke point, and how the in-game mod menu is built out of data plus one detour.
---

:::note
Status: phases 1–5 shipped (in-game mod list, intent protocol, cloned page
buttons). A genuinely new 6th tab remains blocked on loader-side controller
surgery. The goal is a **native** menu built the way the game builds its own — not
an injected ImGui overlay.
:::

## What the game's UI actually is

**No middleware.** No Noesis/XAML/Scaleform/HTML strings. The entire UI is the
engine's own **entity-component system**: menus are `*.entity.ot` assets under
`GameUis/`, `Book_Menu/`, `Ui/` composed of widget components and driven by C++
controller components.

(Dear ImGui 1.91.7 *is* compiled in, but only for the hash-gated dev overlay — see
[Dev/debug mode](/reverse-engineering/notes/). Irrelevant here.)

Widget components, generic and reusable from data: `oCEntityCpntGameUi`
(root/canvas), `WindowUi`, `LabelUi`, `PictureUi`, `ButtonUi`, `GaugeUi`, `EditUi`,
`InputUi`, `ScrollPanelUi`, `NavigableZoneUi` / `NavigableListenerUi` (gamepad and
mouse focus), `oe::UiLayouterEntityCpnt`, `oCEntityCpnt3dText`.

## The main menu is the "Book"

- `oCDtEntityCpnt3DBookController(Settings)` — the 3D book.
- `oCDtEntityCpnt3DBookTabController(Settings)` — one per physical tab; its
  settings deserializer reads just **3 sub-object/picker refs**, so tab→page
  wiring is pure data.
- `oCDtEntityCpntBookMenuUiController(Settings)` — orchestrator; ~8 picker refs +
  2 struct readers, version-gated on class hash `0x1768bccf`. No inline page list —
  pages hang off tabs and pickers.
- Page interface `oIDtEntityCpntBookPageUiController`; concrete pages under
  `GameUis/All_Book_Pages/*.entity.ot` (Challenges, Compendium, HeroMeta,
  PlayBookPage, SelectHero, Social, Recap, Credits, BookOptions, TutoCompendium…).
- Reusable blocks: `oe::dt::ButtonListUiControllerEntityCpnt`,
  `MultiChoiceOptionUiControllerEntityCpnt`.

Cross-entity refs are **path strings**, not GUIDs — pages are wired as
`GameUis\All_Book_Pages\Play_Book_Page.entity.ot` plus `[Game Ui] <page>\Game Ui`
picker strings. `[Named Event Sender]` / `[Named Event Listener]` components exist
in page data, so buttons → named events → the loader's existing `R.on("gameplay:*")`
is an interactivity bridge needing no new C++ hook. A `**`-prefixed label renders
literally, so literal labels need no text-bank key. Only the
`EntitySettings/...gen` file exists per entity — the bare `.entity.ot` path is
virtual.

## The five tabs are a compiled-in constant

| Class | Hash | Size | Ctor | Vftable |
| --- | --- | --- | --- | --- |
| `oCDtEntityCpnt3DBookController` | `0x1781bd6c` | `0x230` | `FUN_140307b10` | `0x140f23368` (30 slots) |
| `oCDtEntityCpnt3DBookTabController` | `0x18ababa6` | — | `FUN_140309a60` | descriptor `DAT_141470f20` |
| `oCDtEntityCpntBookMenuUiController` | — | `0x328` | `FUN_1403e0580` | — |

The settings deserializer builds the tab picker array with
`_eh_vector_constructor_iterator_(count=5, size=0x40)` — **count 5 is a compiled-in
constant**. `BookController_ResolveSettings` runs a fixed loop of 5, type-checking
entries as `oCEntityCpntEntitySpawner` → runtime `+0xf8..+0x118`;
`BookController_ResolveTabs` loops the same 5 → runtime `+0x120..+0x148`.

:::caution
**A 6th tab cannot be added by data.** The count is baked into the deserializer,
the settings layout, the runtime layout and every loop. A real MODS tab needs a
loader detour on `BookController_ResolveTabs` to rewire one of the 5 slots.
:::

Clicks on tabs are **not** 3D picking and not `ButtonUi`: `Main_Book_Menu` has a
`Nav_Zone` with 5 navigable elements plus 5 `[Navigable Listener Ui]` components —
the hit areas live on the 2D UI layer, as pure data.

## Button press dispatch

The per-frame task `oCEntityCpntButtonUi - Button input update`
(`UiButton_InputPoll`) iterates live ButtonUi components; each pressed button that
passes its visibility/enable/focus gates goes through a raw input latch and then
**`UiButton_PressCommit`** with the widget desc from `cpnt+0x268` — the single
choke point for every ButtonUi click. PressCommit runs the widget press state
machine (`+0x32c` state, `+0x328` mode) then vcalls slot 2 on `*(widget+0x570)`,
the owning controller's `oINavigableListener`.

Widget offsets pinned from press captures: **`+0x280` = widget name**,
**`+0x1e8` = rendered label**.

`hook_ui.cpp` post-detours PressCommit (gated by `RSMM_ENABLE_UI_HOOK`, surfaced
in the desktop loader-flags panel) and emits `R.on("ui:press")`. Because the page
controller doesn't know cloned buttons, `*(widget+0x570)` may be null — the hook
skips the native commit for listenerless widgets and only emits the event.

:::danger[Sentinel wrap bug — fixed]
The first armed session crashed reading `0xffffffffffffffff`. The old `readable()`
helper looped `for (x = a; x < a + size;)`; for a `-1` sentinel (UI linked lists
use it as a terminator) `a + size` **wraps**, the loop runs zero times, and the
function falls through to `return true`. Fixed by rejecting non-canonical/wrapping
ranges — and this is why all page-state guarding now lives in the one
`mem_safe.h` implementation.
:::

## Building the mod menu

1. **Page and tab are data** — clone an existing book page entity and a tab mesh
   controller entity, register both via `UsedRscList`, repoint the picker refs.
2. **Labels and art** — text-bank append plus texture overrides.
3. **Actions** — the loader hook on button press → `R.on("ui:press")` → Lua.
4. **Mod ops** — Lua toggles Lua-mods live; asset enable/disable/uninstall writes
   an intent file the host CLI consumes (the game runs under Proton, the CLI lives
   on the host, so it can't shell out in process).

### Shipped pieces

- `engine/entity_strings.py` — lstr surgery (scan/replace length-prefixed strings
  in section payloads; byte-stable, reversible, typo-guarded). The generic
  clone-and-retarget primitive for all entity work.
- `engine/mod_menu.py` + `rsmm menu build|remove` — repurposes `Tuto_Page_1` as an
  "RSMM Mods" page: label keys swapped to `RSMM_Menu_*` and appended to the text
  bank in all languages with the generated mod list. Emitted as a normal override
  mod; reads pristine bytes from `.rsmm.bak`, so rebuild-after-apply is idempotent.
  The base page and bank are cloned from the **user's** install at build time — no
  game bytes in the repo.
- `engine/entity_inspect.py` + `rsmm menu inspect` — structural entity summary and
  diff.
- **Intent protocol** — `rsmm._internal.intent_write(op, mod_id)` (allowlisted
  enable/disable/uninstall, strict id shape) appends JSONL to
  `<cooking>/.rsmm_intents.jsonl`; Lua gets `R.mods.list()` / `R.mods.request()`;
  the host gets `rsmm intents list|apply|clear`, which re-validates (the file is
  user-writable, so untrusted), applies last-intent-per-mod, and re-runs
  `rsmm apply`. `rsmm watch` auto-consumes.
- **Component-append primitive** (`engine/entity_append.py`) — entity cooked layout
  is section 0 = directory (`u32 count` + count × u32 class index), sections
  1..count = one self-framed component record each (first u32 = class index,
  16-byte instance GUID after the first inner END), last section = trailer.
  `cooked.emit(cooked.parse(x))` is byte-identical on the 188 KB book scene, so
  appending = bump count, append class index, insert record before the trailer —
  the entity-file analog of the versiondef vector append proven for items.

### What failed, and why

- **Social-page donor — scrapped.** The clone rendered its text over *every* page,
  cut and mis-scaled: its native `Dt Social Book Page` controller (which owns
  categories, sub-pages and button spawning) doesn't participate in the slot
  show/hide flow.
- **Appended 6th bookmark — inert.** All 5 page-tab nodes carry the *same*
  position and all 5 bookmark entities are byte-identical except GUID and
  material; the visible vertical spread is computed at runtime **by array index**.
  A 6th bookmark either never spawns or lands exactly under the Tuto one. The
  scene append itself loaded crash-free, so the append primitive is in-game safe —
  it's the index-driven controller that has to change.

### What works

Buttons appended **into** the Tuto frame page. `Tuto_Compendim_Page` decodes to 27
sections including two `oCUIGameButtonDesc` records (`Prev_Button` / `Next_Button`
arrow icons — which is why presses reported `name="OPTION_BUTTON"`). Both records
are self-framed and therefore cloneable:

- **WindowUi record**: name lstr, desc link **by name**, `[Game Ui] <page>\Game Ui`
  parent picker, `[NavigableZone Ui] … \Page Nave Zone` picker (nav registration),
  anchor floats, GUID at the standard record offset.
- **ButtonDesc record**: position as f32 fractions, textures, flip/rotation, hover
  colors. No GUID.

`build_tab_assets` clones the page's own Next pair three times as
`RSMM Btn Next/Prev/Toggle` with descs `RSMM_Next_Mod` / `RSMM_Prev_Mod` /
`RSMM_Toggle_Mod`, appending all six components to the page — same-file clone, so
parent and nav pickers resolve unchanged. No foreign controllers, no new assets, no
`Main_Book_Menu` override.

The end-to-end loop is proven in-game: the page renders, clicks select mods,
queueing writes an intent, `rsmm intents apply` flips the manifest, rebuilds the
page and re-applies.

## Open

- **A true 6th tab** — loader detour on `BookController_ResolveSettings`/`Tabs`
  (symbols and patterns are in place) to trigger and position an appended tab
  spawner, plus a 6th Nav element in `Main_Book_Menu`'s Nav_Zone for the click.
- **Structural entity edits** — whole-file clone plus GUID/text swap is proven;
  adding *new rows* to a versioned record is not. Fallback: a fixed row count with
  pagination in Lua.
- Whether the BookMenu controller tolerates a page swap on one of its 7
  path-string page refs — likely yes, since the refs are plain paths, and it would
  give the mod page a whole tab without touching the 5-slot array.
