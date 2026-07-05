# Native UI / book menu system — toward an in-game mod menu

Goal: a **native** mod menu (enable/disable/uninstall mods in-game) built the same
way the game builds its own menus — NOT an injected ImGui overlay (a Vulkan ImGui
overlay existed pre-843a6c8 and was removed as never-feature-complete; the user
explicitly does not want that route).

## What the game's UI actually is (recon 2026-07-05)

**No middleware.** No Noesis/XAML/Scaleform/HTML strings. The entire UI is the
engine's own **entity-component system** — menus are `*.entity.ot` assets under
`GameUis/`, `Book_Menu/`, `Ui/` composed of widget components, driven by C++
controller components.

(Dear ImGui 1.91.7 IS compiled in, but only for the hash-gated dev overlay —
`g_bEnableDebug`, runtime-built CRC table, offline dead-end re-confirmed twice.
Irrelevant to this effort.)

### Widget components (generic, reusable in data)

`oCEntityCpntGameUi` (root/canvas), `WindowUi`, `LabelUi`, `PictureUi`,
`ButtonUi`, `GaugeUi`, `EditUi`, `InputUi`, `ScrollPanelUi`,
`NavigableZoneUi` / `NavigableListenerUi` (gamepad/mouse focus),
`oe::UiLayouterEntityCpnt` (layout), `oCEntityCpnt3dText`.

### The main menu = the "Book"

- `oCDtEntityCpnt3DBookController(Settings)` — the 3D book.
- `oCDtEntityCpnt3DBookTabController(Settings)` — one per physical tab; settings
  deserializer (`FUN_140309940`, settings vftable 0x140f228c0 slot 3) reads just
  **3 sub-object/picker refs** — tab→page wiring is pure DATA.
- Tab mesh entities: `Book_Menu/Book_<Play|Social|System|Tuto|Compendium|Back|Pad_Input>_Tab_Mesh_Controller.entity.ot`.
- `oCDtEntityCpntBookMenuUiController(Settings)` — orchestrator; settings deser
  `FUN_1403dfe90` (vftable 0x140f34738 slot 3): ~8 picker/sub-object refs +
  2 struct readers (`FUN_1403b21b0` @+0x238, `FUN_140408c60` @+0x2d8),
  version-gated on class hash `0x1768bccf` (v≤5). No inline page list —
  pages hang off tabs/pickers.
- Page interface: `oIDtEntityCpntBookPageUiController`; concrete pages under
  `GameUis/All_Book_Pages/*.entity.ot`: Challenges, Compendium (x3 sub-kinds),
  HeroMeta, PlayBookPage, SelectHero, SelectChallenge, CustomizeChallenge,
  Social, Recap, Credits, BookOptions, TutoCompendium…
- Reusable building block: `oe::dt::ButtonListUiControllerEntityCpnt` (generic
  button list), `MultiChoiceOptionUiControllerEntityCpnt` (options rows).

### Buttons / actions

`oCEntityCpntButtonUiSettings` deserializer `FUN_1407d51c0` (vftable 0x140f8bea0
slot 3): scalars + many sub-object refs, version-gated hash `0x11d9f9cd` (v≤6).
No action-string field — button behavior is dispatched to the owning page's C++
controller (and/or bound via `oe::EntityCpntMethodPicker`, seen in the debug
window component). ⇒ a mod page gets custom behavior via a **loader detour on
the button-press dispatch**, routing presses from entities named `RSMM_*` to Lua.

## Architecture for the mod menu (data + loader, no new native UI code)

1. **Page + tab are data**: clone an existing book page entity (candidate: the
   options/social page with a `ButtonListUiController`) + a tab mesh controller
   entity; register both via `UsedRscList` (proven additive path); repoint the
   book/tab picker GUID refs with `entity_edit.swap_refs` (refs = 16-byte GUID
   handles, proven rewirable).
2. **Labels/art**: text bank append (`text_patches`) + texture overrides.
3. **Actions**: loader hook on button press → `R.on("ui:button", name)` → Lua.
4. **Mod ops**: Lua toggles Lua-mods live; asset enable/disable/uninstall writes
   an intent JSON next to `.rsmm_state.json`; host-side `rsmm` consumes it
   (game runs under Proton, CLI lives on the host — can't shell out in-process).

## Phase 1 SHIPPED (2026-07-05): read-only in-game mod list

Deeper recon of `Main_Book_Menu.entity.ot` (54 KB, 93 sections) changed the plan
— the wiring is much friendlier than assumed:

- **Cross-entity refs are PATH STRINGS**, not GUIDs: pages are wired as
  `GameUis\All_Book_Pages\Play_Book_Page.entity.ot` + `[Game Ui] <page>\Game Ui`
  picker strings inside the BookMenu controller settings. 7 pages: Play,
  Compendium, System, Tuto_Compendim, Social, Score, End_Credits.
- **`[Named Event Sender]` and `[Named Event Listener]` components exist in
  page data** (Score page sends `ACTIVITIES ANIM START` etc; Main_Book_Menu
  listens for `GO_TO_PLAY` → `[Executing Methods]`). Buttons → named events →
  the loader's existing `R.on("gameplay:*")` = the interactivity bridge, no
  new C++ hook needed for phase 2 (only structural entity edits).
- **`**`-prefixed label text renders literally** (Score page: `**3.4`) — no
  text-bank key needed for literal labels.
- Only the `EntitySettings/...gen` file exists per entity (the bare
  `.entity.ot` path is virtual).

Shipped on top of that:
- `engine/entity_strings.py` — lstr surgery (scan/replace length-prefixed
  strings in section payloads; byte-stable identity, reversible, typo-guarded).
  This is the generic clone-and-retarget primitive for ALL entity work.
- `engine/mod_menu.py` + `rsmm menu build|remove` — repurposes
  `Tuto_Page_1` (Tuto tab's quick-guide page: 2 titles + 1 paragraph + 3 rows)
  as an "RSMM Mods" page: label keys swapped to `RSMM_Menu_*`, keys appended to
  `Tutorials~GAM.xls` bank (all languages) with the generated mod list. Emitted
  as normal override mod `mods/RSMMMenu`; `rsmm apply` installs. Reads pristine
  bytes from `.rsmm.bak` so rebuild-after-apply is idempotent. Base page/bank
  cloned from the USER'S install at build time — no game bytes in the repo.
  In-game verification pending playtest (open the book → Tuto tab).

## Next steps (ordered)

1. Dump + structurally diff 2 simple pages (`Credits_Book_Page` vs
   `Challenges_Book_Page`) — map the settings-resource `.gen` container, find the
   per-page controller class ids, GUID ref slots, label refs. Decide whether the
   clone unit is the page entity alone or page+children subtree.
2. RE how the book discovers tabs at runtime (decompile `3DBookController`
   runtime cpnt setup/PostLoad — children scan vs explicit picker list). This
   decides where the new tab must be referenced.
3. Find the button-press dispatch in the runtime `ButtonUi` /
   `NavigableListenerUi` cpnt vftable → loader detour (`hook_ui.cpp`) + Lua
   event, gated `RSMM_ENABLE_UI_HOOK`.
4. Prototype: clone Social tab + a page, retitle "MODS", playtest that it opens.
5. Mod-list page content: rows from `mods/` scan (loader io) + intent-file
   protocol + `rsmm intents` host command.

## Open questions

- Entity cooked format: whole-file clone + GUID/text swap is proven; structural
  layout edits (new rows) are NOT — may need the versioned entity codec
  (same grammar family as rewarddef; see docs/_re/kinds/rewards.md discoveries).
  Fallback: fixed row count (e.g. 8 mod slots + pagination in Lua).
- Whether book pages are per-tab prefabs or instantiated by the BookMenu
  controller from its own picker list (step 2 answers this).
