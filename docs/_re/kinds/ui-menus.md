# Native UI / book menu system — toward an in-game mod menu

> 📖 Prose version on the docs site: **https://docs.rsmm.me/reverse-engineering/ui-menus/** (`apps/docs/src/content/docs/reverse-engineering/ui-menus.md`).
> This file stays as the raw RE field notes.


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
- `engine/entity_inspect.py` + `rsmm menu inspect` — structural entity summary
  and diff helper for comparing cooked pages from the live install.

## Phase 2 RE + plumbing (2026-07-06)

All headless-Ghidra (MCP bridge was down; `analyzeHeadless` on a project copy
per the ghidra-headless-bypass recipe — registrars/ctors were undefined code,
`DefineAndDecompile.java` defined them fine).

### Step 1 — page structural diff (`rsmm menu inspect --diff`)

`Credits_Book_Page` (37 sections, 34 classes) vs `Challenges_Book_Page`
(4 sections, 22 classes):

- Every page has a CONCRETE controller settings class deriving from
  `oIDtEntityCpntBookPageUiControllerSettings` (0x1768a9fd): Credits uses
  `TutoCompendiumPageEntityCpntSettings` (0x189e4bf5!), Challenges uses
  `ChallengesPageUiControllerEntityCpntSettings` (0x1aa76209).
- **Credits reuses the generic Tuto-compendium controller** — sub-page list +
  Prev/Next buttons + page-counter dots + auto page-turn timer. That is the
  ideal template controller for a multi-page MODS page (phase 1 already
  repurposes a TutoCompendium page).
- Sub-pages are wired as PATH STRINGS (`GameUis\All_Book_Pages\Credits\...` +
  `[Game Ui] <name>\Game Ui` picker strings) — same as Main_Book_Menu. No
  GUID slots involved. **Clone unit = the page entity alone**; children are
  referenced by path and can be shared or cloned independently.

### Step 2 — tab discovery: FIXED 5-SLOT ARRAY, no scan

Runtime classes (registrar → ctor → vftable):

| class | hash | size | ctor | vftable |
| --- | --- | --- | --- | --- |
| `oCDtEntityCpnt3DBookController` | 0x1781bd6c | 0x230 | FUN_140307b10 | 0x140f23368 (30 slots) |
| `oCDtEntityCpnt3DBookTabController` | 0x18ababa6 | — | FUN_140309a60 | descriptor global DAT_141470f20 |
| `oCDtEntityCpntBookMenuUiController` | — | 0x328 | FUN_1403e0580 | — |

- Settings deser `FUN_140307130` (settings class hash 0x1781bd84, v≤8):
  constructs the tab picker array with
  `_eh_vector_constructor_iterator_(count=5, size=0x40)` — **count 5 is a
  compiled-in constant**. Arrays at settings+0x1f8 (tabs) and +0x4b8.
- Resolve `FUN_140307d30` (vftable slot 5 = `BookController_ResolveSettings`
  symbol): fixed loop of 5, entries type-checked as `oCEntityCpntEntitySpawner`
  (descriptor DAT_141470d78) → runtime+0xf8..+0x118 = the 5 tab entities.
- Wire-up `FUN_1403083d0` (slot 28 = `BookController_ResolveTabs`): loops the
  5 entities, pulls each `3DBookTabController` cpnt → runtime+0x120..+0x148.
- **Conclusion: a 6th tab cannot be added by data.** Count is baked into the
  deserializer, the settings layout, the runtime layout, and every loop.
  The mod menu must REUSE an existing tab/page slot (phase-1 Tuto repurpose =
  correct architecture). A real "MODS" tab would need a loader detour on
  `BookController_ResolveTabs` to rewire one of the 5 slots (symbol + pattern
  are in place for that experiment).

### Step 3 — button press dispatch: SHIPPED `hook_ui.cpp`

- Per-frame task `oCEntityCpntButtonUi - Button input update`
  (`UiButton_InputPoll` = FUN_1407d6210, registered by FUN_1407d4d30):
  iterates all live ButtonUi cpnts; for each pressed button that passes its
  visibility/enable/focus gates calls FUN_140681820 (raw input latch) then
  **`UiButton_PressCommit` (FUN_14069f8e0) with the widget desc from
  cpnt+0x268** — the single choke point for every ButtonUi click.
- PressCommit runs the widget press state machine (+0x32c state / +0x328 mode,
  transitions via FUN_1406a05b0) then vcalls slot 2 (+0x10) on
  `*(widget+0x570)` = the owning controller's `oINavigableListener`.
- Loader: `hook_ui.cpp` post-detours PressCommit, gated
  `RSMM_ENABLE_UI_HOOK=1` (env or desktop loader-flags; surfaced in the
  desktop "Loader features" panel as safe). Emits `R.on("ui:press")` with
  `{widget, strings=[{off,s},...]}` — candidate identifier strings from a
  bounded scan of the widget struct, because the exact name offset inside
  `oCUIGameButtonDesc` is not pinned yet. **First playtest pins the offset**,
  then the payload can be hardened to a plain `name` field.
- Symbols added (all pattern-backed, status ok): `UiButton_PressCommit`,
  `UiButton_InputPoll`, `BookController_ResolveSettings`,
  `BookController_ResolveTabs`.

### Step 5 — intent protocol: SHIPPED

- Loader: `rsmm._internal.intent_write(op, mod_id)` (validated allowlist
  enable/disable/uninstall + strict mod-id shape) appends JSONL to
  `<cooking>/.rsmm_intents.jsonl` next to `.rsmm_state.json`.
- Lua: `R.mods.list()` (id/name/version/author/enabled rows) and
  `R.mods.request(op, id)` in rsmm.lua.
- Host: `rsmm intents list|apply|clear` (`cli/cmd_intents.py`) — re-validates
  (file is user-writable, not trusted), last-intent-per-mod wins,
  enable/disable flip manifest `enabled`, uninstall rmtree-with-containment,
  then re-runs `rsmm apply`, then deletes the file. Tested
  (tests/test_intents.py).

### 2026-07-06 playtest #1: crash, root-caused + fixed

First armed session crashed in-book (AV read of `0xffffffffffffffff`,
minidump `CrashDB/reports/543b2805…dmp`, faulting module OUR `WINHTTP.dll`
+0x2dba1 = `hook_press_commit`). Root cause: the `readable()` helper's
`for (x = a; x < a + size;)` loop — for a sentinel qword `-1` (UI linked
lists use `0xffffffffffffffff` as terminator, cf. DAT_1412f2c88), `a + size`
WRAPS, the loop runs zero times, and the function falls through to
`return true` → the string probe dereferenced -1. Fixed in hook_ui.cpp AND
hook_skills.cpp (same latent bug): reject non-canonical/wrapping ranges
(`a >= 0x800000000000 || size > 0x800000000000 - a`). The hook also now logs
the first 24 presses to `mods/_log.txt` so the name offset can be pinned
without a subscriber mod. Useful crash facts: the loader init runs in TWO
processes (second one fails all pattern resolves + MH rc=7 — pre-existing,
harmless); minidumps parse fine with the `minidump` pip package + MinGW
`addr2line -e dist/winhttp.dll <imagebase+rva>`.

### Interactive layer v1 (2026-07-06)

`rsmm menu build` now also emits `mods/RSMMMenu/init.lua` (static template
`mod_menu.INIT_LUA`, R.*-only, lint-clean):

- selection model over the same sorted mod list the page shows;
- `ui:press` candidates matched against `Next_Button`/`Prev_Button`
  (PROVISIONAL binding until the name offset is pinned): NEXT arrow =
  select next mod, PREV arrow = queue enable/disable toggle via
  `R.mods.request` → intents file;
- gated on `gameplay:BOOK_MENU_OPEN/CLOSED` when the gameplay bus is armed
  (falls back to always-on without it).

Consumption loop closed host-side: `rsmm intents apply` re-runs
`rsmm menu build` first when RSMMMenu is installed (page reflects new
states), and `rsmm watch` polls `<cooking>/.rsmm_intents.jsonl` each cycle
and auto-consumes. `rsmm lint` learned the `ui:*` event namespace. Both
flags persisted in `rsmm_loader_flags.json` (RSMM_ENABLE_UI_HOOK +
RSMM_ENABLE_GAMEPLAY_EVENTS).

### Playtest #2 results (2026-07-06): loop PROVEN, arrows insufficient

Full end-to-end loop verified in game: page renders, clicks select mods
(`[rsmm-menu] selected 2/43: ...`), double-click queues
(`queued enable CustomItemLogic`), intent lands on disk, `rsmm intents apply`
flips the manifest, rebuilds the page, re-applies. Widget offsets PINNED from
press captures: **+0x280 = widget name** (`OPTION_BUTTON`, `Button`, ...),
**+0x1e8 = rendered label**. But: the book's page-turn arrows all reuse the
options-arrow widget → every arrow reports `name="OPTION_BUTTON"`,
indistinguishable → the click/double-click protocol was a workaround, not UI.

## Phase 3 (2026-07-07): dedicated MODS tab with REAL buttons

User requirement: "completely new tab + buttons, not arrows".

- A 6th physical tab is impossible by data: `BookController_ResolveSettings`
  builds a FIXED 5-entry picker array (`_eh_vector_constructor_iterator_`
  count=5). So the Tutorial tab slot is repurposed instead.
- Donor: `Social_Book_Page` — its left column is 6 REAL spawned buttons
  (`Social_Category_Button` instances) labeled from `Common~GAM.xls` bank
  keys. `ui:press` carries the rendered label → each button individually
  addressable from Lua.
- `engine/mods_tab.py` (`build_tab_assets`): clones the social page as NEW
  asset `RSMM_Mods_Page` (internal instance renamed so `[Game Ui]`/`[State]`
  pickers can't collide with the live social page), swaps the 6 category
  bank keys + page title to `RSMM_*`, redirects category 1's sub-page to
  `Tuto_Page_1` (the page phase 1 relabels with the mod list), overrides
  `Main_Book_Menu` to point the Tuto tab's page slot at the clone, appends
  bank texts (`MODS`, `Mod list`, `Next mod`, `Prev mod`, `Toggle selected`)
  to `Common~GAM.xls` + language siblings. Ships via the proven
  new-asset/UsedRscList pipeline; social page untouched.
- `init.lua` v3: label-driven bindings rendered from `mods_tab.BUTTON_*`
  constants (single source of truth, tested); name-based and
  click/double-click handlers kept as fallback.
- Wired into `rsmm menu build` (opt-out `--no-tab`), manifest marked
  `experimental = true`. Tests: `tests/test_mods_tab.py` +
  `test_init_lua_shape` guard label/key consistency and live-install
  invariants. Applied 2026-07-08; asset registered
  (`[new] RSMMMenu: registering ... RSMM_Mods_Page`).

## Phase 4 (2026-07-08): TRUE 6th tab — deep RE + component append

User rejected the Tuto-slot repurpose: wants a genuinely NEW tab. Findings:

### How the 5 tabs actually work (complete chain)

- **Scene data**: `EntitySettings\Book_Menu\Book_Mesh_Controller.entity.ot`
  (NOT in the shipped asset map — encode paths via the cipher directly) is
  the 3D book scene. Per tab it has an `X Tab 3d Node` cpnt (parent:
  `Root Left Tab 3d Node`) + an `X Tab Spawner` cpnt
  (`oCEntityCpntEntitySpawnerSettings`) that spawns
  `Book_Menu\Book_X_Tab_Mesh_Controller.entity.ot` at that node. SEVEN
  spawners exist: 5 page tabs + Back + Input — physical bookmarks beyond
  the 5-array are already vanilla-normal.
- **Bookmark entity**: `Book_X_Tab_Mesh_Controller.entity.ot` = tiny clone
  of `Book_Tab_Mesh_Controller_Model` (plane mesh + per-tab material
  `M_Book_*_Tab.mat.ot` + `Dt Book Tab Controller` cpnt with select/out
  anims and HIDE_TAB/SHOW_TAB listeners). Position is anim/index-computed,
  not stored per node (node diffs = GUID + name + one rotation).
- **The book controller** (`Dt Book Controller`, in the same scene file,
  section w/ ordered pickers): 2 graphic objects, page-turn L/R states,
  disable tester, **Back + Input spawner pickers** (runtime +0x68/+0x70),
  3 testers, **5 tab spawner pickers** (INLINE FIXED array → runtime
  +0xf8..0x118), page L/R + old-texture states, **5 book states**
  (Lobby/InGameSettings/Score/EndCredits/Empty → +0x98 array). All loop
  bounds are immediates (5); arrays inline in the 0x230 object → NOT
  growable in place.
- **Clicks are NOT 3D picking and NOT UiButtons**: `Main_Book_Menu` has a
  `Nav_Zone` with 5 navigable elements (`Play_Nav`, `Compendium_Nav`,
  `System_Nav`, `Tuto_Nav`, `Social_Nav`) + 5 `[Navigable Listener Ui]`
  cpnts — the tab hit-areas live on the 2D UI layer, pure data.

### Component-append primitive (NEW, `engine/entity_append.py`)

Entity cooked layout: section 0 = directory (`u32 count` + count× u32
class-table index), sections 1..count = one self-framed component record
each (first u32 = class index, 16-byte instance GUID right after the first
inner END marker), last section = trailer. `cooked.emit(cooked.parse(x))`
is byte-identical on the 188KB scene. Appending = bump count + append class
index + insert record before trailer — the entity-file analog of the
versiondef MO-vector append proven for custom items. Helpers:
`replace_blob_strings` (lstr surgery inside one record), `remint_guid`,
`append_components`, `find_component`, `validate_layout`.

### Shipped in `rsmm menu build` (opt-out `--no-bookmark`)

`mods_tab.build_bookmark_assets`: clones `Tuto Tab 3d Node` +
`Tuto Tab Spawner` (renamed `RSMM ...`, GUIDs reminted, entity ref →
`Book_Menu\RSMM_Tab_Mesh_Controller.entity.ot`), appends both to the book
scene (275 → 277 components), ships the bookmark entity as a new asset
(clone of the Tuto bookmark w/ `M_Book_Input_Tab` material so it's visually
distinct). UsedRscList: RSMM_Tab registered, vanilla scene record untouched
(dedup verified). Applied 2026-07-08.

### Playtest #4 results (2026-07-08): social clone + bookmark both fail

- No 6th bookmark visible. Follow-up RE: all 5 page-tab NODES carry the
  SAME position (x=0.0973/y=3.466 under `Root Left Tab 3d Node`) and all 5
  bookmark ENTITIES are byte-identical except GUID/material — the visible
  vertical spread is computed at runtime by the book controller BY ARRAY
  INDEX. An unknown 6th bookmark either never spawns (spawn likely
  controller-triggered per known picker) or lands exactly under Tuto's.
  A working 6th tab = loader-side controller surgery (position + click +
  flip are all index-driven). Bookmark build kept as opt-in
  (`rsmm menu build --bookmark`), in-game inert; scene APPEND itself loaded
  crash-free → the component-append primitive is in-game safe.
- The social-page clone rendered its text over EVERY page, cut/mis-scaled:
  its native `Dt Social Book Page` controller (owns categories/sub-pages/
  button spawning — `Category_Button_Spawner` + `SpawnerValue` label
  injection, all native-driven) doesn't participate in the slot show/hide
  flow. Social donor SCRAPPED.

## Phase 5 (2026-07-08): buttons appended INTO the Tuto frame page

`Tuto_Compendim_Page` fully decoded (27 sections): `Game Ui` root,
`Page Nave Zone` (NavigableZoneUi), WindowUi cpnts `Input Frame` /
`Next Button` / `Prev Button`, the TutoCompendium controller, 9
`oCEntityGameUiSpawner` sub-page refs, 2dElement frames, and TWO
`oCUIGameButtonDesc` records (`Prev_Button` / `Next_Button`, arrow icon
buttons — hence `name="OPTION_BUTTON"` in presses).

Anatomy of a page button (both records self-framed → cloneable):

- **WindowUi record**: name lstr, **desc link BY NAME** (`Next_Button`
  lstr), `[Game Ui] <page>\Game Ui` parent picker, `[NavigableZone Ui]
  <page>\Page Nave Zone` picker (nav registration), anchor floats.
  GUID at the standard record offset (after first inner END).
- **ButtonDesc record**: position as f32 fractions (Next arrow x=0.99078
  — raw bytes `a4 70 7d 3f`, unique in the record — y=0.5), textures,
  flip/rotation, hover colors. No GUID.

`mods_tab.build_tab_assets` v2: clones the page's own Next pair 3× as
`RSMM Btn Next/Prev/Toggle` + descs `RSMM_Next_Mod` / `RSMM_Prev_Mod` /
`RSMM_Toggle_Mod` at x=0.68/0.55/0.42 (y=0.5), appends all six components
to the page (same-file clone: parent + nav pickers resolve unchanged). No
foreign controllers, no new assets, no Main_Book_Menu override. init.lua
matches the desc names against `ev.name`/`ev.label`/candidate strings.

**Loader guard** (hook_ui.cpp): the page controller doesn't know the
cloned buttons, so `*(widget+0x570)` (press listener, vcalled slot 2 by
the native commit) may be null — `hook_press_commit` now skips the native
commit for listenerless widgets and only emits `ui:press`.

## Next steps (ordered)

1. **Playtest #5** (user): Tuto tab → do 3 extra arrow buttons render
   mid-page (x≈0.42/0.55/0.68)? Click each → `[ui-hook] press` lines; do
   the payload strings carry the `RSMM_*` desc name? If yes → bindings
   fire (`[rsmm-menu] selected/queued`). If the desc name does NOT
   surface, pin which widget field does (candidate strings) and extend
   the hook payload.
2. Button look/labels: swap arrow texture for a labeled style (LabelUi or
   `oCTextStyle` route) once identity is proven.
3. TRUE 6th tab (user requirement, unresolved): loader detour on
   `BookController_ResolveSettings/Tabs` (symbols + patterns ready) to
   trigger + position our appended tab spawner, then a 6th Nav element in
   `Main_Book_Menu`'s Nav_Zone (append primitive) for click; revert the
   Tuto-slot use once clickable.

## Open questions

- Entity cooked format: whole-file clone + GUID/text swap is proven; structural
  layout edits (new rows) are NOT — may need the versioned entity codec
  (same grammar family as rewarddef; see docs/_re/kinds/rewards.md discoveries).
  Fallback: fixed row count (e.g. 8 mod slots + pagination in Lua).
- Widget-desc name offset (pinned by first `ui:press` playtest).
- Whether the BookMenu controller (page orchestrator, distinct from the 3D
  book's 5 physical tabs) tolerates a page swap on one of its 7 path-string
  page refs — likely yes since refs are plain paths; would give the mod page
  a whole tab without touching the 5-slot array.
