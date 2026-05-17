# Roadmap

> Historical path note: where this file mentions `tools/<script>.py`,
> the current location is `src/rsmm/cli/<script>.py`; the equivalent
> CLI surface is `./rsmm <name>`.

## Recent landings (2026-05-17)

- ✅ **Uncooked asset mirror** — `data/uncooked/` extract pipeline
  (textures decoded BC1/BC3/BC5/RGBA8 → PNG, 4,776 PNGs; 15,431 .gen
  raw + 15,362 structural sidecars). See `docs/UNCOOKED_ASSETS.md`.
- ✅ **Pack guard** — `rsmm pack` refuses byte-identical-to-original
  files. `--allow-vanilla` for personal backup zips. Prevents accidental
  redistribution of copyrighted Ravenswatch assets.
- ✅ **Mass decompile** — 46,963 functions in
  `docs/_re/out/decompiled_all/`. Symbols + strings JSON exported.
  See `docs/_re/PIPELINE.md`.
- ✅ **Pattern-resolver + `rsmm.call`** — 53,427 byte-pattern
  signatures in `data/function_patterns.json` (99.50% self-validate).
  Loader DLL gains `rsmm.resolve(name)`, `rsmm.call(target, "sig",
  ...)`, and memory r/w. Community can now call any of 53k game
  functions by name from Lua. See `docs/_re/CALLING_GAME_FUNCTIONS.md`.
- ✅ **Seed surface mapped** — built-in `oe::UIntGameOption "Forced
  seed"` (id `0x1949b098`) identified at `0x1401c6d60` with companion
  enable bool. `mods/ExampleSeedPin/` demonstrates pin-to-fixed-seed
  for speedruns. See `docs/_re/SEED_MAPGEN.md`.

## #0 — Live path-redirect to give slot 7 (Mods) its own entity

**Status:** ✅ DONE. Implemented in
`loader/src/hook_engine.cpp` + `tools/make_social_mods_page_mod.py`.
Verified in-game: slot 7 renders a different entity than slot 4
(see Phase 3 of `FINDINGS.md`).

### What works

- Cooked file patch: slot 7 now references the fake path
  `GameUis\All_Book_Pages\Social\Mods_List.entity.ot`.
- Live loader hook: `FUN_140487040` is intercepted, the fake path
  is detected, and the cached handle of a chosen substitute entity
  is returned instead of the engine's `result=0` (path-miss).
- Substitute caching: first time the substitute path resolves to a
  non-zero handle during normal engine init, we snapshot it; later
  fake-path lookups return that handle.
- Process filter: only fires inside `Ravenswatch.exe`; the
  crashpad child loading our `winhttp.dll` is skipped to avoid
  `MH_ERROR_NOT_EXECUTABLE`.
- Diagnostic mode: `RSMM_TRACE_BURST=N` arms a one-shot broad
  string capture after the redirect fires.

### What this gives us

- A clean, slot-sized Mods page renders inside the Social book,
  fully interactive, distinct from any other slot.
- Current substitute: `Friend_List_Model.entity.ot` (no offset,
  slot-friendly layout, placeholder rows).
- Substitutes tried and their outcomes are catalogued in
  `FINDINGS.md` → "Phase 3 — Redirect outcome".

### What it does NOT give us

- Real mod names in rows: every slot-friendly book-page entity is
  template + controller, where rows are spawned at runtime from
  game data (Steam Friends, magical-objects registry, heroes
  list, etc.). The row content does not pass through
  `FUN_1401145b0` (Steam SDK uses its own char* path), so it
  cannot be intercepted from the oCString hook.
- Click → mod toggle: blocked on getting rows we control first.
- Any modal-style static-button-list substitute (e.g.
  `Modal_Social_Options_Menu`) has exactly the layout shape we
  want but is sized for a fullscreen overlay and covers the
  entire book panel when rendered into a slot.

## #1 — Phase 5: build a custom `Mods_List.entity.ot`

**Stage B status (2026-05-16):** ✅ DONE. The new cooked file
exists on disk at the encoded `Mods_List` path as a byte-clone of
Friend_List_Recent, registered in `asset_map.json`, installed via
`apply_mods.py`. `tools/ot_decoder.py` parses it cleanly. The
loader's redirect now resolves to a real (non-zero) handle from
`real_resource_lookup` and selects `real` over `sub`. See
`FINDINGS.md` → "Phase 5 Stage B" for the verified slice and
concrete next-session work (layout RE, FriendsList component
strip, text-bank rebind, per-row click identity).

**Why this is unavoidable.** Phase 4 (click pipeline) works — clicks in
the Mods slot translate to disk writes that toggle `enabled` flags.
But three substitute-specific defects remain and **none can be fixed
without a custom entity**:

1. **Layout.** Friend_List_Invite renders centered/floating inside the
   book panel, not anchored to the slot. Its internal `oC2dElementDesc`
   bounds were tuned for a different parent context. Modal substitutes
   (Modal_Social_Options_Menu) have the right static-button shape but
   are sized for fullscreen overlays and cover the entire book.
2. **Exit/Back button is dead.** Substitute's back button fires an
   event whose listener is in the parent Friend-list flow; the
   listener does not exist in our slot's parent tree, so dispatch is
   a no-op.
3. **Rows show friends, not mod names.** Friend_List_* are templates
   populated at runtime by the Steam Friends API. Row text never
   passes through `FUN_1401145b0`, so we cannot intercept it from the
   oCString hook.

A custom entity solves all three at once: we own the bounds, we own
the event sinks, and we own the row text source (text-bank-keyed
labels we override at build time with mod names).

### What it requires

**Status:** plan only. This is the real next phase to actually
display mod names + toggle state.

### Why

Every vanilla candidate has been exhausted (see Phase 3 of
`FINDINGS.md` → substitute table). To display arbitrary text in
N rows inside the slot, we need an entity whose layout fits the
slot *and* whose row labels are statically embedded (or keyed to
`Common~GAM.xls` entries we can override at build time).

No such entity exists in vanilla. We have to construct one.

### What it requires

1. **`oCEntitySettings` binary schema.** From the
   `MagicalObjects_Compendium_Page` decode we already have a
   working size profile: 38 classes, root is an
   `oCEntitySettingsResource[385218467]` containing a tree of
   `oCEntitySettings[205233578]` children.
2. **Schemas for the UI component classes used by the smallest
   working static-button entity.** The minimum set is:

   ```
   oCEntitySettings                            (base)
   oCEntityCpntWindowUiSettings                (panel container)
   oCEntityCpntButtonUiSettings                (button row)
   oCEntityCpntLabelUiSettings                 (text label)
   oC2dPictureDesc / oCUISplitPictureDesc      (background tile)
   oC2dLabelDesc + oCTextStyle                 (rendered text)
   oCUINavigableZoneDesc                       (input zone)
   oCEntityCpntPicker / oCEntityValueUnion     (link a label to a
                                                text-bank key)
   ```

3. **Class table + section markers.** The cooked file format uses
   `1111bbaa` BEGIN / `2222bbaa` END markers around each section;
   we already parse and emit these reliably in `tools/ot_decoder.py`
   and `tools/make_social_mods_page_mod.py`.
4. **A new 16-byte entity GUID** for the root.
5. **The cooked-encoded output path.** `asset_map.json` maps
   `GameUis\All_Book_Pages\Social\Mods_List.entity.ot` → the
   obfuscated path inside `_Cooking/`. The Caesar/substitution
   cipher in `tools/cipher.py` should encode this correctly.

### Where to start

1. Decode a minimal Modal/Button entity with `tools/ot_decoder.py`
   to map the exact byte layout of each component class. Best
   candidate: `GameUis\Options\Option_ApplyButton.entity.ot` —
   it's a single-button entity, smallest reasonable scaffold.
2. Build a re-encoder for the minimum class set in
   `tools/ot_reencoder.py`. Start with `oCEntityCpntButtonUiSettings`
   and `oCEntityCpntLabelUiSettings`.
3. Write `tools/make_mods_list_mod.py` that emits a fresh
   `Mods_List.entity.ot` containing N button rows, each bound to
   a text-bank key like `RSMM_Mod_Slot_0`, `RSMM_Mod_Slot_1`, …
4. Have the same script also extend `make_text_mod.py` to write
   those keys with mod names from `mods/*/manifest.toml`.
5. Drop the cooked file at the encoded `Mods_List.entity.ot`
   path. The live hook now sees a real (non-zero) lookup result
   and the redirect either returns the new file's handle
   directly or is rendered unnecessary.

### Once display works: row click → mod toggle

Modal_Social_Options_Menu's modal-style button arrangement was
fully **interactive** when we tested it as substitute (the user
could invite friends through the rendered Friend_List_Invite,
for example). So once we have buttons in a static cooked file
under our control, the click events will fire. Wiring those
to a mod-toggle action means:

- Either reusing an existing engine event the button can fire
  (open-url, modal-spawn, etc.) and hijacking its destination,
- Or hooking the engine event-dispatcher and detecting clicks
  from button entities we recognize as ours (by entity GUID).

The latter is the cleaner long-term path because it scopes
mod-toggle behavior to our own button instances.

## #2 — Add a real new "Mods" tab/button to the in-game menu

**Status:** structural patch DONE in `tools/make_real_menu_button_mod.py`.
The patched file (a) parses cleanly through `tools/ot_decoder.py`, (b)
has 12 picker entries in State Init (was 10), (c) has 68 top-level
sections (was 66). Awaiting in-game verification of:
- whether the new button is visible at all,
- whether its on-screen position collides with the Discord button (we
  byte-clone the Discord Spawner — if position is an explicit float in
  the spawner payload, the clone overlaps; if NavigableZone auto-stacks,
  the new button appears below Exit),
- what label it shows (it inherits the Discord button's text-bank key,
  so it'll display whatever `Menu_Discord` is currently mapped to in
  the active language).

Follow-up after a successful test: pin down the position field in
`oCEntityCpntEntitySpawnerSettings` and offset the clone.

### What it requires

1. **Full `oCEntitySettingsResource` schema.** The MainMenu is an
   `oCGameStream` (see `FINDINGS.md`) whose single root entity is
   `BOOK_SPAWNER -> Book_Menu\Book_Mesh_Controller.entity.ot`. That
   controller cooked file contains 75 classes including the actual
   button/tab definitions (`oCDtEntityCpnt3DBookControllerSettings`,
   `oCEntityCpntNamedEventSenderSettings`, etc.). To add an entry we
   need to insert a new entity into this file — which means knowing the
   binary layout of each component class.

2. **Re-encoder for arbitrary classes.** `tools/ot_reencoder.py` currently
   supports only a handful of small classes (plus GUID patching for the
   smallest `oCEntitySettingsResource` cohort). The menu work still needs
   broader schemas, at least for:

   ```
   oCEntitySettings
   oCEntityCpntPicker
   oCEntityCpntValuePicker
   oCEntityCpntNamedEventSenderSettings
   oCEntityCpntNamedEventListenerSettings
   oCEntityCpnt3dGraphicObjectSettings
   oCDtEntityCpnt3DBookControllerSettings
   ```

3. **A fresh 128-bit GUID for the new entity.** Already nailed down —
   each entity carries a 16-byte UUID-like ID at body offset 0x11.
   UUIDv4 should work but needs runtime validation.

4. **An event sink.** The new button has to *do something* when
   clicked. Options:
   - Reuse an existing engine event (e.g. open-url) and combine with our
     URL-redirect trick — minimal but still web-based.
   - Reuse an engine event that opens a sub-menu, then point that
     sub-menu at our content. Needs more entity work.
   - In-process DLL/Vulkan path (parked under `loader/` and `layer/`).
     Anti-tamper was the blocker before.

### Where to start

1. **Schema mining.** Run `tools/class_diff.py oCEntitySettingsResource`
   bucketed by size; pick the smallest non-trivial cohort (~80 bytes)
   and diff. The body=49 cohort is already decoded (GUID + flags).
2. **Iterate on Book_Mesh_Controller.** It's the largest single entity
   file using all the menu classes. Map out its sections with
   `tools/ot_decoder.py --raw`, identify a candidate "tab" entity to
   *clone* (rather than build from scratch), and bytewise-copy it with a
   tweaked label string reference.
3. **Use a copy-and-tweak strategy first.** Don't try to construct an
   entity from zero; duplicate an existing button's bytes, regenerate
   its 16-byte GUID, replace its visible-label string ID.
4. **Drop the modified `Book_Mesh_Controller` cooked file at its
   encoded path under `_Cooking/` via `apply_mods.py`.**

### Why deferred

Each component class is a separate empirical RE task. With the existing
hijack already giving us a working "Mods" entry, this is *polish* rather
than functionality. The right window to tackle it is when (a) we want
multiple mod-manager menu items rather than one button or (b) we can
spend an afternoon disassembling `Ravenswatch.exe` to recover schemas
directly from the engine's class-registration code.

### Acceptance criteria for "done"

- A new visible tab/button in the Ravenswatch main menu, distinct from
  any vanilla button.
- Label sourced from a text bank we control.
- Click action either opens our manager UI or executes a controlled
  engine event.
- Reversible via `tools/apply_mods.py --restore-all`, leaving zero trace
  in `Book_Mesh_Controller`.

## #3 — Hook API (`rsmm.hook`)

**Status:** blocked on anti-tamper.

`rsmm.call` now lets mods invoke any of 53k game functions. The
missing surface is *interception* — observer/mutator callbacks per
function. The MinHook engine in `src/loader/src/hook_engine.cpp` is
wired but stubbed: every hookpoint we've tried so far (`CreateFileW`,
`IDXGISwapChain::Present`-equivalents) crashes the game at startup
under the anti-tamper integrity check.

Paths forward:

1. **Inject before anti-tamper init.** TLS-callback DLL injection
   runs before the exe's entry point. Confirm whether AT's first
   integrity sweep is after this point.
2. **Hook outside `.text`.** Vulkan loader / Steam SDK / FMOD all
   provide function pointers we own indirectly; redirect through
   our shim without touching the game image.
3. **Use the pattern resolver for an "indirect call" hook.** Resolve
   the target, install a software trap in our DLL that intercepts
   only when called from inside `rsmm.call_hooked()` — non-invasive
   to the game image.

Until one of those lands, expose `rsmm.hook` returning an explicit
"not supported on this title" error so modders fail at write-time,
not run-time.

## #4 — Pattern-DB self-rebuild on game update

When Steam pushes a Ravenswatch update, the pattern signatures in
`data/function_patterns.json` need a regen against the new exe. Two
pieces of UX missing:

- `./rsmm doctor` should hash the installed exe and compare against the
  `image_base + filesize` recorded inside `function_patterns.json`'s
  header (TODO: write it). Mismatch → warn modders that
  `rsmm.resolve` may degrade.
- `./rsmm rebuild-fn-patterns` one-shot wrapper that re-runs the Ghidra
  dump + `gen_function_patterns.py` + `test_pattern_resolve.py --all`
  and reports the unique-rate.

Estimated total runtime per regen: ~30 min.
