# Skills (talents) system — RE findings + feasibility verdict

> Scope: the requirement "a custom talent that is hero-specific, upgradeable to
> legendary, and visible in the hero page." In-game these are **Skills**, not
> "talents" (no "Talent" string exists). This doc maps the system and gives a
> go/no-go for authoring a NET-NEW skill. Companion: `talents-pick.md` (the
> runtime pick/effect hook — a different, already-shipped layer).
> RE date 2026-06-15, image base 0x140000000, via Ghidra MCP.

## 🎯 Crash mechanism RE'd + correct fix = RUNTIME injection (2026-06-16, later)

The 28→29 herodef brick is now understood at the instruction level, and the
"hardened to NOT-FEASIBLE" verdict below is **superseded**: it IS feasible, but
NOT by editing the `.gen`.

- **Herodef deserialize = `FUN_14031e630`** — a strict **versioned, ordered**
  field reader: each field is gated by `FUN_1404fbea0(stream, …, 0x1768d0c9)`
  (the herodef type-version) compared against rising thresholds, and read into a
  fixed instance offset. It does NOT "read skills until a terminator"; it reads a
  fixed schema in order.
- The skill set is a **counted collection** (engine collections ARE counted —
  `FUN_140312860` reads a count / `"Vector.Length"`, caps at 1e6, then loops
  `FUN_1401c8720` per element). Herodef skill vector = instance **`+0x7d0`**.
  SkillProfileData (`oe::dt::SkillProfileData::vftable`, hash `0x186b12c9`, size
  `0xe8`, ctor `FUN_1401adc10`, container `+0x30`) wraps skills at herodef `+0x2b8`.
- **Why a spliced row crashes:** there is **no plain `u32==28` count anywhere in
  the `.gen` before the rows** (scanned all heroes) — the count lives behind a
  polymorphic header / nested object, position-variable. A byte-spliced 29th node
  therefore desyncs every *subsequent* versioned field read → load crash. So the
  data-edit path (`clone_skill`) is structurally fragile and stays disabled.

**Correct fix = the item-pool pattern, applied to skills.** Don't edit the
serialized herodef. After a herodef deserializes, have the **loader grow the
runtime skill vector at `herodef+0x7d0`** and append a cloned SkillController
(descriptor `FUN_1402f8d70`, hash `0x15f639fc`, size `0x2a8`), bumping the
in-memory count — exactly how `hook_items.cpp` grows the magical-object pool
(`g_vec_grow`). The talent/Skill menu enumerates that runtime vector, so the new
skill shows WITHOUT touching the crash-prone deserialiser. This is the in-progress
"talent shows in each hero's menu" feature.

### Loader hook SHIPPED (compile-checked; playtest pending)

`src/loader/src/hook_skills.cpp` (`install_skill_hooks`, wired in `dllmain`)
detours the herodef deserialiser and, after the original runs, inspects the
runtime skill vector at `herodef+0x7d0` (`{void* data; u32 count; u32 cap;}`,
element stride `0x38`). Resolved by pattern (`FUN_14031e630` added to
`data/function_patterns.json` — masked, verified unique = 1 match @ `0x14031e630`).

- **Default = READ-ONLY**: logs `[skill-hook] herodef=.. skillvec data=.. count=..
  cap=..` per loaded herodef → confirms the `+0x7d0` offset + that `count==28`.
- **Inject gated** behind `RSMM_ENABLE_SKILL_INJECT=1` and self-guarded (acts only
  if count∈[1,200] AND `cap>count`, i.e. spare slot, no realloc) so a wrong offset
  is inert. It clones the last element into the spare slot + bumps count = a
  PROOF-OF-PATH duplicate skill (refcount of embedded refs not yet adjusted —
  expect a visible dup in the menu, not yet a distinct custom skill).

Playtest: launch options `WINEDLLOVERRIDES="winhttp=n,b" %command%` → read the
`[skill-hook]` log lines to confirm count/cap; if `cap>28`, add
`RSMM_ENABLE_SKILL_INJECT=1` → the hero's Skill menu should show 29. Then iterate:
grow when no spare cap, fix refcounts, point the new element at a custom skill.

## ⚙️ Ghidra MCP wall BYPASSED + net-new verdict hardened (2026-06-16)

The "static decompile path is walled" claim below is **obsolete for tooling**:
the MCP bridge can't create functions, but `analyzeHeadless` on a *copy* of the
project can. See memory [[ghidra-headless-bypass]] + `/tmp/rsmm_ghidra_scripts/`
(`DefineAndDecompile.java`, `FindScalar.java`). Decompiled the previously-undefined
registrars:

| class | registrar | type-hash | descriptor size | field/desc cb |
|-------|-----------|-----------|-----------------|---------------|
| `oCDtEntityCpntSkillController` | `FUN_1402f8d70` | `0x15f639fc` | `0x2a8` | (0) |
| `SkillProfileDataSettings` | `FUN_140194510` | `0x186adbdf` | `0xd0` | `FUN_14031b550` |
| `oCDtHeroDefinition` | `FUN_140194ff0` | `0x1768d0c9` | `0x908` | `FUN_14031d5b0` |

`*Settings` callbacks (`FUN_14031b550`/`FUN_14031d5b0`) only set the display
description + file-glob + a flag — NOT the field list. Herodef ctor `FUN_14031d610`
(desc `+0x80` thunk) has no fixed 28-element member, so the skill set is a
**dynamic** collection, not a baked array.

**Net-new verdict — HARDENED to NOT-FEASIBLE as a data mod.** New empirical proof
beyond the single 28→29 brick: **all 12 heroes carry EXACTLY 28 `Skill Controller`
rows** (Beowulf/Red/Carmilla/Juliet/Melusine/Aladdin/Sun_Wukong/Piper/Snow_Queen/
Geppetto/Romeo/Merlin — names are hero-specific, count is invariant). The rows are
a flat run of class-4 nodes bounded by an `END` (@~0x47x) and the following class-5
`Text` node; there is **no skill-count u32 in the `.gen`** before the run (scanned
±0x120 across heroes — the only nearby fixed bytes are an unrelated 21-entry run of
`0x11` dwords, NOT a per-skill count). So the "read exactly 28" count comes from the
**class reflection schema in code**, not the file — a 29th row desyncs the
property-driven deserialiser → hero fails to load. Adding a real skill row therefore
needs an **engine/loader patch to the hero class schema**, not a cooked-asset edit.
`mode="clone"` stays disabled. For an additive (non-replacing) custom talent, the
correct layer is the **level-up CARD pool** (`talents-pick.md`), not the herodef.

## ⚠️ clone-insert CORRUPTS the herodef — DISABLED (proven 2026-06-15)

Splicing a raw skill row into the herodef (`clone_skill`, `kind="skill"
mode="clone"`) makes the WHOLE HERO fail to load — Aladdin vanished from the
hero-selection menu after a 28→29 clone. **Proven TWICE, GUID-independent:** it
bricks with a reminted GUID AND with the source GUID kept, so identity is NOT the
cause. No skill count/size field exists in the herodef header (the `28` "hits"
were unaligned bytes of a `0x100`-strided index table), yet the deserialiser
still rejects the extra row — it enforces a count/length living in the registrar
region Ghidra leaves unanalysed. `clone_skill`'s parser round-trips (reads 29)
but the game does not accept it. `mode="clone"` now hard-errors; net-new skills
are not feasible by row insertion until that deserialiser format is RE'd. Use
`mode="relabel"`.

## VISIBLE custom talent — SHIPPED & APPLIED (2026-06-15)

The reliable way to show a custom talent in-game is to **relabel an existing
skill** via its text bank — confirmed working end-to-end on a live install.
A skill's display name/desc come from `Text/Hero_<Hero>_Common~GAM.xls.LocalText`
keys `Skill_<Suffix>_Name`/`_Desc` (suffix = controller name, spaces→`_`).
`rsmm.engine.text_patches.override_bank_values` rewrites those VALUES in every
language sibling (count-neutral; base keys untouched). The `kind="skill"`
builder's default `mode="relabel"` emits that override. PROVEN: applied
`source="Attack Dive"` → `name="Lightning Dash"` on Aladdin; the install's EN
sibling now reads "Lightning Dash" — shows on his level-up cards + Skill Menu.
Do NOT rename the herodef controller key for display — the game derives the text
key from it, so a rename breaks the lookup.

Also fixed a pre-existing apply bug: `emit_content_blocks` built the
`ContentRegistry` without the manifest's `experimental` flag, so EVERY
non-confirmed content kind (enemy/skill/…) was silently skipped at apply even
when opted in. Now `Mod.experimental` is parsed and passed through.

## STATUS — engine + SDK kind SHIPPED (2026-06-15)

`rsmm.engine.skill_clone` (`repoint_skill` in-place / `clone_skill` net-new) +
the declarative `[[content]] kind="skill"` builder (`rsmm.sdk.kinds.skills`) are
implemented and tested (`tests/test_skill_clone.py`, 7 pass incl. a real-herodef
round-trip: Aladdin 28→29 rows, other rows byte-identical). Rated **`guess`** —
requires `experimental=true`. The emit logs the new skill's identity GUID; bind
behaviour with `R.talent.on_pick("<lo>:<hi>", …)`. Example:
`docs/ExampleMods/ExampleCustomSkill`. **OPEN: in-game hero-page/level-up load is
unproven** (skill-vector count repr unknown — see "Asset-diff results").

## TL;DR verdict (updated after asset-diff)

- **Reskin an existing skill = satisfies all three requirements TODAY.** A
  vanilla skill the hero already owns is hero-specific, already has its
  legendary upgrade tier, and already renders in the hero page. Repoint its
  effect/values with the shipped `talent-value-editing` + `talent-logic-rewire`
  paths.
- **Net-new skill = TRACTABLE via row-cloning** (downgraded from "HIGH/blocked").
  The skill list lives in the **herodef** `.gen` as a flat sequence of
  self-contained `BEGIN id=4 … END` rows (~0xb0 bytes each, one per skill).
  Cloning a row + repointing its two 16-byte GUID handles + renaming its lstring
  is exactly the machinery `rsmm.engine.entity_edit` already has
  (`swap_refs(size=16)`, `replace_lstring`). NOT walled like the static decompile
  path. Remaining unknowns are normal authoring details (collection count repr,
  upgrade→base linkage), not reverse-engineering walls.

## Asset-diff results (herodef `.gen` skill rows) — the authoring target

File: `Definitions/Heroes/<Hero>.herodef.ot.DtHeroDefinition.gen` (NOT the hero
entity-settings `.gen` — corrected). The `.gen` is a marker-delimited node tree:
`1111bbaa`=BEGIN (+`<u32 class id>`), `2222bbaa`=END, length-prefixed ascii
strings, raw fields. Aladdin: 316 balanced BEGIN/END pairs, **28 skill rows**.

One skill row (`BEGIN id=0x4 … END`, e.g. "Attack Dive" @0x477, size 0xad):

```text
1111bbaa 04 00                      row node (class 4)
  <u32 len><"Skill Controller Attack Dive">   skill key (lstring)
  <16-byte GUID #1>                 skill IDENTITY handle
  1111bbaa 07 .. nested 0a/0b/0c    flag/param sub-nodes (ints, a "M" tag, 0/1 u32s)
  <16-byte GUID #2>                 REF handle (-> effect/def entity)
  00 * 9
2222bbaa                            row end
```

All 28 rows share this shape (sizes 0xa9–0xb8). The 4 **upgrade/legendary**
variants are just extra rows named `Skill Controller Ultimate <N> Upgrade <1|2>`
(slightly larger, 0xb2–0xb6). Unlock levels are a separate run of
`Book_Page_Skill_Unlock_Lvl` entries (×22).

### Open authoring details (step-2, not walls)
- **Collection count:** no `u32 == 28` header before the rows — the set is
  node-delimited (count derived by iterating to the parent END), so inserting a
  row may need only structural insertion, not a counter bump. Confirm against the
  parent `SkillProfileDataSettings` node (@0xa7).
- **Upgrade→base linkage:** a base skill's identity GUID appears only once (its
  own slot) — upgrade rows do NOT embed the base GUID, so the link is by **name
  convention** (`"<base> Upgrade <n>"`) or a separate table. Confirm before
  authoring a custom legendary tier.
- **GUID #2 target:** confirm whether it points to the effect-component entity
  (the thing to repoint for custom behavior) vs a UI/text descriptor.

## System map (what each piece is)

| Piece | Identity | Role |
|-------|----------|------|
| Skill pool (per hero) | `oCSkillProfileData(Settings)` "Hero skill profile data" | the hero's skill set |
| Where it lives | **inline in `EntitySettings/Heroes/Hero_<X>/Hero_<X>.entity.ot.EntitySettingsResource.gen`** | the `.gen` embeds skill rows; names are Text keys `Skill_*_Name`/`_Desc` |
| Runtime owner | `oCDtEntityCpntSkillController` (+Settings +PersistentData) | owns/upgrades the hero's live skills; ~10 slots (`hero.skill.0..9`, FUN_140394a40) |
| Hero-page UI | `SkillUiViewerEntityCpnt` / `oCDtEntityCpntSkillUiControllerSettings` ("Dt Skill Ui Viewer"), `Menu::SkillMenu`, asset `EntitySettings/GameUis/SkillsUi/Skill_Menu` | enumerates + renders the controller's skills |
| Tiers / legendary | rarities Common/Rare/Epic/Legendary/Ultimate = UI frames `HUD_Skill_Frame_01..05`; `skill_tier`, `skill_rarity` | legendary is a rarity tier |
| Upgrade events | `UPGRADE_RANDOM_SKILL`, `UPGRADE_LOWER_SKILL`, `UPGRADE_SPECIFIC_SKILL`, `UPGRADE_LOWER_SKILL_TO_LEGENDARY`, `ADD_ALL_SKILLS`, `ADD_RANDOM_ULTI_SKILL`, `RESET_SKILLS` | drive tier promotion |

## Concrete offsets found (runtime skill object)

From the `skill_selected` analytics emitter `FUN_1401f6bd0`:

- select-context: `+0x00` = **tier** (float, logged as int), `+0x10` = ptr to the SKILL object
- SKILL object: `+0x20` = **name** StringDesc, `+0x38` = **rarity** StringDesc

(Same `+0x20` name-StringDesc convention as `oCGameNamedEvent`; see `events-bus.md`.)

## How the three requirements are actually satisfied

1. **Hero-specific** — the skill row lives in *that hero's* entity `.gen`, and the
   SkillController is on the hero entity. A skill is hero-specific by construction.
2. **Upgradeable→legendary** — a skill carries a rarity/tier; the
   `UPGRADE_*_SKILL` path promotes it (legendary = top tier, frame 04). A net-new
   skill must define its tier and the normal→legendary pairing the same way a
   vanilla row does.
3. **Hero-page visible** — `SkillUiViewer` enumerates the controller's skill set
   (sourced from the hero entity rows). Anything that is a real row in that set
   renders automatically; anything that is NOT (e.g. the Phase-1 Lua effect hook)
   will never appear.

→ All three are properties of being a **real skill row in the hero entity**.
The Phase-1 `R.talent.*` runtime hook is none of these — it is an effect layer,
useful only bolted onto a real skill.

## The wall (why net-new can't be finished via MCP static analysis)

Every `Skill*` class registrar / factory / ctor (e.g. the
`oCDtEntityCpntSkillController` and `oCSkillProfileDataSettings` reflection
descriptors) is referenced from **code regions Ghidra left undefined** (the
class-name string xrefs land at addresses inside no defined function, e.g. the
`oCDtEntityCpntSkillController` name ref at `0x1402f8e69`). The MCP bridge has no
"create function / analyze region" capability, so the deserializer that defines
the exact per-skill **row layout** (effect-component subgraph + tier link +
icon/text refs + collection count header) cannot be decompiled here. This is the
same wall hit on the pick-event registrar in `talents-pick.md`.

## Hero-specific talent CODE (runtime effect scoping)

Most skills are hero-specific, so custom talent *code* must scope to one hero.
Two mechanisms (both in `src/loader/lib/rsmm.lua`):

1. **`hero=` gate** — `R.talent.define{ hero="Juliet", ... }` (or
   `R.talent.for_hero("Juliet")`) fires the effect only when that hero is active,
   via `R.hero.is`. `R.hero` infers the hero from its **exclusive ability events**
   (`_HERO_SIGNATURES`); the hero entity has no herodef/type field at runtime
   (loader RE: carrier vtable `0x140f2b930`, ctor `FUN_14038e320`), so this is
   signature-based. Limitation: only heroes with a seeded signature resolve
   (currently SnowQueen). Seed others via `R.hero.catalog()`.
2. **Hero-exclusive card binding (signature-free)** — a `pickable` talent bound
   to a skill-card GUID is hero-specific automatically: that GUID lives in exactly
   one hero's herodef (the `<16-byte GUID #1>` of a skill row above), so only that
   hero can ever arm it. This needs the pick-identity offset confirmed
   (`talents-pick.md`) but no `R.hero` signature.

→ For a net-new authored skill, the talent is hero-specific *by construction*
(the row lives in one hero's herodef); the runtime effect should additionally
carry `hero=` or bind its own card GUID so the CODE can't leak to another hero.

## Recommended path (ladder, cheapest first)

1. **Reskin a vanilla skill (ship now).** Pick a low-value skill the target hero
   owns; repoint its values (`rsmm.engine.talent_values`) and/or its effect graph
   (`rsmm.engine.entity_edit.swap_refs`, [[talent-logic-rewire]]); retext via the
   `Skill_*_Name/_Desc` Text keys + reicon via `Ui/HUD/HUD_Skill_Frame_*`. Result:
   hero-specific, upgradeable, hero-page-visible — a real custom-feeling talent.
2. **Map the row layout by asset-diffing (next).** Dump a hero's skill rows from
   the entity `.gen`, identify row boundaries/count header, then CLONE one row and
   repoint its Text/effect/tier refs (GUID handles, per [[talent-logic-rewire]]).
   Cross-reference the runtime offsets above. This is the real net-new path; do it
   as throwaway discovery, then graduate into an SDK kind (`mods-ship-data-not-code`).
3. **Optional: bolt Phase-1 Lua effect** onto the skill for behavior the data
   graph can't express (`R.talent.on_pick` / `pickable`, see `talents-pick.md`).

## Open questions for step 2
- Exact skill-row stride + the collection count header in the hero `.gen`.
- The normal↔legendary row pairing representation (two rows? one row + tier field?).
- Whether the SkillController auto-enumerates all rows or filters by a flag.

---

## 2026-06-17 — Runtime injection PROVEN mechanically; blocked on grid layout

Full runtime path executed end-to-end and **does not crash**, but the new talent
is **not visible** in the hero details/Book page. Root cause is the UI layout, not
the data.

### What works (loader `hook_skills.cpp`, gated `RSMM_ENABLE_SKILL_HOOK`/`_INJECT`)
- Detour of herodef deserialize `FUN_14031e630` (added unique pattern to
  `data/function_patterns.json`); fires per herodef at boot, all 12 heroes.
- **Talent vector = herodef `+0x8d8`** `{void* data; u32 count; u32 cap;}`,
  **pointer array** (stride 8), `count==cap==28` on every hero (exact-fit). Count
  lives IN the vector (confirmed: deser fills it via `FUN_14020d700(stream,
  herodef+0x8d8)`, which `_malloc_base(n*8)` then per-elem `vtable+0xa8`).
- Elements are **`oe::dt::SkillProfileDataSettings*`** (vftable static
  `0x140efd018`, ctor `FUN_1400c9210`, dtor `FUN_1400c9290`, **size 0xd0**).
- Inject = realloc the array to 29, deep-clone an element (malloc 0xd0 + memcpy),
  remint its two 16-byte GUIDs, repoint vector data/count/cap. Leaked on purpose
  (engine owns original; herodef persists for session). Clean on all 12 heroes.

### SkillProfileDataSettings (0xd0) field map (runtime byte-diff)
- `+0x00/+0x08` vtables.
- **`+0x10` 16-byte GUID** = identity (engine dedups on it — remint to avoid
  collapse, same lesson as item custom-clone grant collision).
- `+0x30` `{ptr,u32,u32}` = own sub-vector of effect descriptors (count 29–43,
  i.e. `+0x38==+0x3c`). NOT a position.
- **`+0x40` 16-byte GUID** = secondary/skill ref.
- `+0xc0/+0xc4` = 0/1 flag (correlates with `+0xb8` ptr set) — likely
  upgrade/legendary or "has-extra-data". Not tier.
- **`+0xc8` = ABILITY pointer** (shared by all talents in one ability column;
  e.g. Aladdin t00==t03==`…65a00`, t08==t09==t10==`…67800`). The grid groups
  columns by this.

### The wall
The TALENTS grid (hero Book page) is laid out by **(ability `+0xc8`, tier I/II/III)**
into a **packed tree with no spare cells**. There is **no plain (tier,slot) field**
in the 0xd0 object — tier is derived elsewhere (the `+0xc8` ability node or the
`+0x30` descriptor sub-vector / prerequisite links). A clone that copies a real
talent reuses its ability+tier → renders ON TOP of the original cell → invisible.
Growing the vector to 29 has no effect because the grid does not enumerate by
vector length; it places each known talent into its computed cell.

### Remaining unknowns to make a net-new VISIBLE talent
1. Where TIER (1/2/3) is stored/derived per talent.
2. How the grid builder enumerates talents and assigns cells (find the Book/
   details-tab UI function; it reads herodef talents + ability nodes).
3. Whether a free cell can exist (likely must extend a tier row or add an ability).

### Practical recommendation unchanged
Net-new visible talent is a hard UI-layout problem. **Reskin/relabel an existing
talent row** (step 1 above) remains the shippable path for a custom-feeling,
hero-page-visible talent today.

### 2026-06-17 (cont.) — SPDS carries NO grid coordinates
Probed all 28 talents with the details page OPEN (grid built):
- `+0x68 == -1` (0xffffffff) on every talent — constant, not tier.
- `+0xc8` is a **string/asset-path pointer** (ASCII when deref'd: `Loop.fbx`,
  `…\Merlin`, `Character`, `…\Piper\`, `pDefeat.`), NOT an ability backref. The
  earlier "shared ability ptr" reading was coincidence across a different boot.
- `+0xc0`/`+0xb8` = a 0/1 flag + optional ptr (upgrade/legendary-ish), not position.

So the talent's grid cell (tier I/II/III + ability column) is **not stored in the
0xd0 object**. Placement comes from EXTERNAL authored layout data (candidates: the
per-talent `+0x30` descriptor sub-vector, prerequisite/branch edges, or a dedicated
herodef layout table). The Book grid is a *designed* layout, not auto-packed from
the +0x8d8 vector — which is why growing that vector is inert for the UI.

**Net-new visible talent = multi-structure RE project** (locate the authored layout
table + the Book grid-builder UI fn + how cells are assigned/whether a free cell can
exist). Beyond incremental loader probing; needs the headless-decompile bypass on
the UI region. Shippable alternative remains reskin/relabel of an existing talent.

### 2026-06-17 (cont. 2) — grid layout is in the SkillUiViewer, NOT the talent
Dumped every plausible position field across all 28 talents with the Book page open:
- `+0xac == 1` on all 28 (constant, not tier).
- `+0x40` GUID is **unique per talent** (no clustering) → per-talent skill ref, not
  an ability/column key.
- `+0xa4/a8/b0/b4 == 0`, `+0xc0` = 0/1 flag. No (tier,column) anywhere in the 0xd0.

So the talent's grid CELL is not stored in the SkillProfileDataSettings object. The
**cell→talent mapping is authored in the `SkillUiViewerEntityCpnt` UI component**
(RTTI strings: `SkillUiViewerEntityCpnt(Settings)`, `oCDtEntityCpntSkillUiControllerSettings`
@140f28628/140f35e98; type-alias helper FUN_14043b560). The Book grid reads that
layout (talent GUID -> cell), which is why growing herodef+0x8d8 to 29 added no
cell — the injected talent has no layout entry.

**Net-new VISIBLE talent = TWO injections:** (1) the talent row in herodef+0x8d8
(PROVEN, no crash) AND (2) a cell entry in the SkillUiViewer runtime layout pointing
at the new talent's GUID (UNKNOWN — needs headless decompile of the SkillUiViewer
settings deserialize + its runtime cell list, then a second loader injection). The
grid has FREE cells (Tier I/III not full) so a placed cell can render. Substantial
multi-step effort; MCP leaves the UI region unanalyzed (use the headless bypass).
Loader `hook_skills.cpp` already does injection #1 behind RSMM_ENABLE_SKILL_INJECT.

### 2026-06-17 (cont. 3) — headless RE of SkillUiViewer started
Headless pipeline rebuilt + PROVEN reproducible:
- Project copy: `cp -r ghidra_project/Ravenswatch.{gpr,rep} /tmp/rsmm_hl/` (724M; the
  live MCP project is locked). Program path inside project = `/Ravenswatch2/Ravenswatch.exe`.
- Script `/tmp/rsmm_ghidra_scripts/DefineAndDecompile.java` (creates a function at each
  seed addr + decompiles it and its 1-level callees).
- Run: `analyzeHeadless /tmp/rsmm_hl Ravenswatch/Ravenswatch2 -process Ravenswatch.exe
  -noanalysis -scriptPath /tmp/rsmm_ghidra_scripts -postScript DefineAndDecompile.java <addrs>`

Found: `FUN_140365801` / `FUN_1403659b9` = **SkillUiViewer class registrars** (type
hashes **0x15f63a0f**, **0x15f63a1f** — same family as SkillController 0x15f639fc).
They register reflection fields via `FUN_14050b390(table, nameHash, callback)` and set
a deserialize thunk `unaff_RBX[0x10] = &LAB_1401b9240`. The instance grows a global
linked list at DAT_141470ed0/DAT_141470e38 (+0x68 count, +0x70 tail).

CAVEAT: seed addresses landed mid-function (decompile shows `unaff_RBX`); the real
registrar starts are earlier — re-seed at the function entry (scan back to the
`mov [rsp+8],rbx; push...` prologue) and re-run to get the full field list.

NEXT (resumable): (1) get full registrar field list -> find the field that is the
cell layout / talent-GUID list; (2) RE the deserialize thunk LAB_1401b9240 to see how
the authored layout maps cells->talent GUIDs; (3) find the runtime layout struct on
the SkillUiViewer component instance; (4) loader-inject a cell referencing the
injected talent's GUID into a FREE (column,tier) cell. This is a multi-session
reflection-RE effort. Injection #1 (talent row) already works (hook_skills.cpp).

### 2026-06-17 (cont. 4) — SkillUiViewer settings has NO cell list; columns = ability category
True registrar `FUN_1403656f0` (re-seeded past 0xCC padding). It builds the
SkillUiViewerEntityCpntSettings descriptor: instance **size 0x388**, ctor
**FUN_14043b240**, field-setup thunk @LAB_140368a00->FUN_14043b240, deserialize
@FUN_1401b9240 (vtable jumptable thunk). Type hash 0x15f63a0f.

The settings ctor (FUN_14043b240) initialises: `TipsUiDisplaySettings` (+0x30) and
several `oCEntityCpntPicker` / `oe::EntityCpntMethodPicker` sub-objects (+0x1f, +0x27,
+0x41, +0x44, +0x4d, +0x50, +0x59, +0x5c, +0x65, +0x68). Those are PICKERS = refs to
WHICH skill-controller/methods the viewer drives — **not** a per-talent cell list. So
the grid cell positions are NOT authored in this component's settings.

KEY INSIGHT (data-side): talent text keys carry the ability category in the prefix —
`Skill_Attack_*`, `Skill_Power_*`, `Skill_Special_*`, `Skill_Defense_*`,
`Skill_Ultimate_*`, `Skill_Passive_*`, `Skill_Dash_*`, `Skill_Trait_*`. The Book grid
**COLUMN = ability category**, **ROW = upgrade tier (I/II/III)**, both COMPUTED at
build time from the skill's category + tier — not stored as (x,y) coords anywhere.
This explains every negative probe (no position field in SPDS; growing +0x8d8 inert;
settings has no cell list).

CONCLUSION: net-new visible cell needs the BUILD method (find the SkillController/
SkillUiViewer runtime build that groups skills by category+tier and emits cell
widgets), then either (a) give the injected talent a category+tier that maps to a
FREE cell and confirm the builder enumerates the runtime skill set (not a baked
list), or (b) runtime-hook the builder to emit an extra cell. Both = more headless on
the build method (not yet located). Substantial; resumable from here.

### 2026-06-17 (cont. 5) — abilities do NOT reference talents; placement is computed-only
Probed the 7 ability objects (herodef+0x8e8, INLINE array, stride 0x240) for any
qword pointing at one of the 28 talent SPDS pointers (+0x8d8): **zero hits on all 7**.
So abilities do not own/reference their talents. Every storage hypothesis is now
exhausted (talent obj: no tier/column; abilities: no talent refs; SkillUiViewer
settings: pickers only, no cell list). The +0xc8 asset-path on each SPDS is written
LAZILY by the build method when the Book page opens.

DEFINITIVE: the talent grid cell is **computed at build time** (column from the
skill's ability CATEGORY — `Skill_Attack_*`/`Power`/`Special`/`Defense`/`Ultimate`
name prefix — row from tier), not stored in any injectable structure. So no runtime
data injection can place a net-new cell. The ONLY remaining path is to find + hook
the Book grid BUILD method itself (reads herodef+0x8d8 talents, derives category+
tier, emits cell widgets) and make it emit an extra cell for the injected talent —
pure headless RE of the build fn (not yet located; search for readers of
herodef+0x8d8/+0x8e8 in the UI region). Genuinely a dedicated effort.

Loader stability note: AdditivePickableTalent's NEW magical-object item crashed boot
(item-hook queued 2, faulted) — disable it or fix the cloned entity before shipping.
Reskin (AladdinLightningDash) + text-bank merge are stable and live.

### 2026-06-17 (cont. 6) — build-method hunt; candidates + dead-ends
Headless FindOffsetReaders.java: 12 funcs reference BOTH herodef+0x8d8 and +0x8e8.
Inspected the strongest:
- FUN_1403207b0 / FUN_140320540 — iterate both arrays calling FUN_140696440/370 on
  each elem+8 (herodef-internal copy/serialize/hash, NOT UI).
- FUN_1401d9b70 — has "Rare Skill Chance Modifier" string (skill stat, not grid).
- FUN_14031e630 = the deserializer (known).
The Book grid BUILD does NOT reference herodef+0x8d8 directly — it reads the runtime
skill set through the skill controller, one layer removed. So the build method is not
in this candidate set; trace from the SkillController component's update/refresh.
Pipeline tools (resumable): /tmp/rsmm_ghidra_scripts/{DefineAndDecompile,FindOffsetReaders}.java
on the project copy. Net-new grid cell = genuinely multi-layer, dedicated effort.

### 2026-06-17 (FINAL) — grid placement is identity-derived; NO injection point
Probed all 28 talents' pointer fields (+0x50/+0x60/+0x70/+0x78/+0x90): ALL share the
same static pointers (vtables/shared resources). Only +0xb8 varies (upgrade-data ptr,
set only for upgradeable talents, correlates with +0xc0 flag). NO per-talent ability/
column/tier field anywhere.

CONCLUSIVE MODEL: the Book grid column = the skill's CATEGORY (Attack/Power/Special/
Defense/Ultimate/...), derived at build time from the skill's NAME, which resolves via
GUID -> global registry (DAT_1414364e8, register=FUN_140320540 / unregister=FUN_1403207b0)
-> name -> category prefix -> column; row = tier. There is NO single editable field
that places a talent in a cell. A runtime clone inherits its source identity and lands
on the source's cell (overlap). A visible net-new cell would require forging a COMPLETE
new identity (new GUID + registry registration + a name whose category/tier maps to a
currently-FREE cell) AND confirming the build's category-parse — i.e. essentially
authoring a real new skill end-to-end, the same wall as the .gen clone-insert (which
bricks the hero via the versioned deserializer count).

VERDICT: net-new talent in the hero detail grid is NOT achievable by data/runtime
injection. Shippable custom-talent paths remain: (1) RESKIN existing talent (live,
proven — AladdinLightningDash), (2) ADDITIVE pickable card via the magical-object pool
(needs the item-crash fix). The grid wall is architectural, not a missing datum.
