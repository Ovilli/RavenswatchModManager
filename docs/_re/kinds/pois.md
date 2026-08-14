# POIs, structures & the tile system — `oCDtTileDefinition`

> Status: both codecs RE'd + shipped 2026-08-10 (`poi` kind, `rsmm poi`).
> Static verification is complete — 237/237 tiledefs and 3/3 tile-generated
> mapdefs round-trip byte-for-byte. **No in-game playtest yet.**

## A POI is a tile

There is no `PointOfInterest` class. Searching RTTI for it returns nothing —
which is the wall `projectiles.md` recorded when it went looking for a size
field. The thing players call a point of interest is a **tile**: one placeable
chunk of a generated map.

```
oCDtTileDefinition          *.tiledef.ot     237 shipped
oCDtMapDefinition           *.mapdef.ot        4 shipped
```

Shrines, cauldrons, teleporters, enemy camps, ruins, stairwells and plain
blockers are all the same class. The only thing separating "POI" from
"structural filler" is whether the record carries a minimap icon — 139 of 237
do (`Ui` category), 52 carry an `Editor` icon, 46 carry none.

## Three gates, not one

This is the part that matters, and it is why "add a POI to a chapter" is a
data edit rather than an engine problem:

| Gate | Where it lives | What it decides |
|---|---|---|
| **kind** | `Map_<Biome>_..._TileGeneration.level.ot` | which tile *kinds* each map slot accepts |
| **pool** | the chapter's `*.mapdef.ot` | which concrete tiledefs the map may draw from at all |
| **cache** | `<tile>.tiledef.UsedRscCache.ot` | what the tile is allowed to preload — see below |

The third gate went unnoticed for the whole first pass at this feature and cost
two playtests plus a crash; it is documented under
[Every tiledef needs a UsedRscCache](#every-tiledef-needs-a-usedrsccache).

The kind vocabulary is mostly **shared** — 42 kinds appear in all three
tile-generated maps (`Altar_Of_Heroes`, `Wishing_Well`, `Teleporter`,
`Leprechaun_Cauldron`, `Camp`, …), and only quest/boss kinds are chapter-local
(`JackQuest` Dark Hills, `Mordred` Avalon, `Roc_Quest` Storm Island). So kind
alone cannot be what keeps a Dark Hills shrine out of Avalon.

The **pool** is. It is an explicit list at the end of the mapdef body, and it is
per-map: Dark Hills 77 tiles, Avalon 96, Storm Island 64. Baba Yaga has no pool
at all — it is the scripted boss arena, not tile-generated.

**Cross-biome pooling is a vanilla pattern.** Dark Hills' own pool contains
`Tiles\Storm_Island\6x6_Dark_Hills_Refugee_01.tiledef.ot`. The engine does not
care which directory a tile is filed under, so adding a tile ref to another
chapter's pool is doing exactly what the shipped data already does.

## `oCDtTileDefinition` tail layout

The leaf codec exposes `entity_ref`; everything below was in `_tail_hex` and is
now typed by `src/rsmm/engine/tile_cook.py`.

```
BEGIN
  u32   prelude = 4              constant across all 237
  u32   kind_count
  lstr  kinds[kind_count]        join key to the map's slot vocabulary
END
u32   width                      footprint in tile units
u32   height
f32   weight                     mapgen pick weight
f32   ratio                      1.0 on 204/237
u32   child_count
child[child_count]               nested BEGIN..END composite-tile blocks
tresptr icon                     u8 resolved + lstr category + lstr path
bytes rest[40]                   editor tint RGBA + 6 unmined scalars
```

`tresptr` (u8 + two length-prefixed strings) is the same typed-resource-pointer
shape the leaf codec already uses for `entity_ref` — the `u8` is the
`_res` "resolved" flag hoisted to the top of the JSON doc.

### What is certain vs. inferred

**Certain.** `kinds` — the strings match the map's slot vocabulary exactly.
`width`/`height` — they equal the `NxN_` prefix on every tile whose filename has
one (`6x6_Teleporter_01` → 6×6, `40x40_Wood_House` → 40×40). `icon` — every
non-empty path resolves to a shipped texture. `entity_ref` — the prefab that
actually gets instantiated.

**Certain, and initially got wrong.** `weight` is a **tier** field, not a spawn
rate. Every tier-suffixed family in the corpus — cauldrons, grimoires and
wishing wells, across all three biomes — carries exactly `T1=0.0`,
`T2=0.333`, `T3=0.667`, with no exceptions:

| family | T1 | T2 | T3 |
|---|---|---|---|
| Cauldron | 0.0 | 0.33 | 0.66 |
| Grimoire | 0.0 | 0.333 | 0.667 |
| Wishing Well | 0.0 | 0.333 | 0.667 |

The first reading of this field was "mapgen pick weight; 0 = never rolled
alone", inferred from the fact that all 149 zero-weight tiles are structural.
That inference was backwards — T1 cauldrons carry weight 0.0 and obviously do
appear in game. Raising `weight` to make a POI commoner marks it as a
higher-tier variant instead, which if anything gates it behind run progression.

**How often a tile actually appears** is governed by pool share: a chapter fills
a slot from the pool entries whose kind matches, so a tile's odds are
`its entries / all entries of that kind`. Each biome ships exactly two
`Fountain` tiles, so one added entry is a third of fountain slots and eight is
about 80%. That is what the `poi` kind's `copies` field controls, and why it
emits N distinct tiledefs rather than repeating one ref — `add_to_pool`
de-duplicates, so a repeated ref would change nothing.

**Preserved, not understood.** The 40-byte `rest`. Its first four floats are an
RGBA that co-varies with the `Editor` icon category, so it reads as an editor
tint; the remaining six scalars (two of which take small integer values 0–4)
are unmined. All 40 bytes round-trip verbatim.

## `oCDtMapDefinition` tile pool

```
…                                 tribes, loading-screen entity, localized name
u32   tile_count
tile_count × { lstr category, lstr path }
```

The pool is the **last** field of the body, so `src/rsmm/engine/map_pool.py`
locates it by scanning for the one offset whose `u32` is followed by exactly
that many well-formed string pairs *ending at end-of-tail*. That anchor fails
closed: a game patch that appends a new trailing field makes the scan find
nothing rather than silently mis-parsing at a hardcoded offset.

Everything before the count is preserved verbatim, so the module never has to
model the tribe or loading-screen fields it does not touch.

## What the `poi` kind does

1. Clones a shipped tiledef, optionally retuning `weight` / `kinds` / `icon`.
2. Files the clone in the **donor's biome directory**. This is load-bearing:
   `apply_mods.synthesize_encoded` derives a new asset's encoded path by cloning
   an existing sibling's encoded prefix, so a fresh `Definitions/Tiles/<Mod>/`
   has nothing to anchor on and the tile is warn-and-skipped at apply. Verified
   both ways in `tests/test_poi.py`.
3. Emits an override of each target mapdef with the tile ref appended.

Multiple `poi` mods hitting one chapter are **merged**
(`apply_mods._merge_map_pool`, same shape as the text-bank merge): each mod
emits vanilla-plus-its-own-tiles, and without the union the last writer wins and
every other mod's POI is registered as an asset but never pooled — it loads,
is never placed, and nothing reports an error.

## What this does NOT do

**No net-new level.** A `poi` always starts from a shipped tile's level and
swaps objects inside it, so it inherits that tile's terrain, layout and
scatter. Authoring a level from scratch — terrain mesh, nav, spawn volumes —
is still the wall `maps-chapters.md` records as #9. What *is* now possible is
replacing the objects a tile places with the mod's own art (see the custom-art
section below), which covers "a structure the game does not have" without
needing "a map the game does not have".

**No new interactables.** A custom prop is scenery: the donor entity supplies
its component set, and a plain scenery donor has no interaction, loot table or
gameplay hook. Cloning a *functional* donor (a fountain, a cauldron) keeps that
donor's behaviour, but authoring new behaviour is a different problem — see
[Interaction](#interaction-the-engine-already-has-a-system) below, which is
where that problem is now being worked.

**Runtime spawning is still blocked.** This is data-level placement at map
generation, which sidesteps `spawn-system.md`'s unresolved instantiator
entirely — but it also means a POI cannot be added to a run already in progress.

## Next steps

1. **Playtest.** Add one high-weight POI to a chapter and confirm it generates.
   The watch-point is whether a mod-added pool entry is picked at all; if it is
   not, the next suspect is a per-tile flag consumed by `oCCustomFlagFilter` /
   `oCDtTileFlagConstraint` in the TileGeneration level that the tiledef itself
   does not carry.
2. Mine the TileGeneration level's slot table so `kinds` can be validated
   against the *actual* slot vocabulary instead of the pool-derived proxy
   `poi.chapter_kinds()` uses today (the proxy is conservative — every kind in
   it belongs to a tile the map already draws — but it is not the real gate).
3. Mine the 6 unknown scalars in `rest[40]`; two look like counts (values 0–4).
4. Type the composite-child blocks so multi-tile structures (stairwell +
   corridors) can be assembled rather than only cloned whole.

## Custom art: the full reference chain (shipped 2026-08-10)

Cloning a shipped prefab is only half the feature. The other half is putting a
mod's **own** mesh and textures in a generated map, and the thing that makes it
tractable is that every hop between the pool and the pixels is a reference *by
string path* — no GUIDs, no indices:

```
mapdef pool ─► tiledef ─► tile prefab entity ─► tile level ─► prop entity
                                                                  │
                                              ┌───────────────────┴────┐
                                              ▼                        ▼
                                          geometry                material ─► textures
```

So a mod can splice itself in at any hop by cloning the vanilla asset and
rewriting the one string that points at the next. `src/rsmm/engine/prop_cook.py`
does exactly that, and the `poi` kind's `prop` block drives it declaratively.

### Two rewrite mechanisms, because the assets differ

| Asset | Refs exposed as | Rewritten via |
|---|---|---|
| material (`oCMaterial`), tile level (`oCGameStream`) | typed `asset_refs` list | `cooked_schemas.asset_refs`, edited as data |
| prop entity, tile prefab (`oCEntitySettingsResource`) | inline in an untyped payload | `entity_strings.replace_strings` |

`replace_strings` rewrites a length-prefixed string in place *including to a
different length*, which is safe because entity deserializers read strictly
sequentially — no absolute offsets into a payload.

### Reference form vs. cooked path

The engine names art by its **source** path and loads the cooked sibling:
a material asks for `Scenery\DarkHills\T_Foo.tga`, the loader opens
`3D\Scenery\DarkHills\T_Foo.tga.Texture.dxt`. `prop_cook.art_cooked_path`
derives that, but `3D/` is a convention rather than a rule — `Textures\Black.png`
cooks under `samples/`, and shader refs (`*.px.ot`) resolve through `shaders/`.
It is the right tool for checking a mod ships its own art and the wrong one for
resolving an arbitrary vanilla ref; use `asset_map.json` for those.

### Custom geometry: where the graft template comes from

Cooking a mesh means grafting it onto a *template* cooked oCGeometry.
`cook_cache` can do this at apply time, but it looks for the template **at the
destination path** — which works for an override and not for a brand-new asset,
because a new asset has no destination file.

The fix is that the manifest already names a donor prop, and that donor has a
mesh. `poi._donor_geometry` uses it, so a mod ships a plain `.glb` and needs to
know nothing about templates. Two sources are accepted, in order: a real
`.Geometry.gen` if the corpus has one, else the `extras.rsmm.cooked_b64` blob
embedded in the `rsmm uncook` GLB that `extract_uncooked.py` actually mirrors
(the mirror stores geometry as GLB, so this is the normal path). The donor
contributes vertex layout and material-slot count only; positions, normals and
UVs are all replaced.

### A POI is a folder

The manifest form got long enough to be its own problem — a custom prop needs
five engine paths plus a texture-slot map, and nobody can write that from
memory. `poi.discover()` reads `mods/<id>/pois/<name>/` instead:

```
pois/runestone_shrine/
    poi.toml        chapters + any overrides
    model.glb       the mesh
    albedo.png      matched to the preset's texture slots by filename
    mra.png
    normal.png
```

`PRESETS` bundles the donors (which tile, which object to replace, which prop
and material to inherit from, and the role→slot map) behind one name, so the
common case states only `chapters`. Discovery emits exactly the dict a
hand-written `[[content]]` block would, so the explicit form still works and a
declared block wins on id collision — the convention is a shorthand, not a
second code path. Unknown keys in `poi.toml` raise rather than being ignored,
since a silently-dropped setting is one the author believes is in effect.

### Minimap icons

A tiledef's icon is a `tresptr` to UI art, and UI cooks under the **`Ui/`** root
rather than `3D/` — `MiniMap\Icons\X.png` loads from
`Ui/MiniMap/Icons/X.png.Texture.dxt`. That is a second namespace, so
`prop_cook.ui_cooked_path` exists alongside `art_cooked_path`.

Drop `icon.png` in a POI folder and it becomes the icon; it beats an
`icon = "<vanilla ref>"` in `poi.toml`, since shipping a file is the more
specific intent. Custom icons are filed into `MiniMap\Icons` for the usual
sibling reason — a fresh directory has nothing for `synthesize_encoded` or
`build_usedrsc_record` to clone from.

House style, measured off the 60 shipped icons: **48x48** (42 of them),
transparent background, a thick dark outline fully enclosing the shape, flat
saturated fill with a little vertical shading, and a rim light on the top-left
edge. Matching it matters more than the drawing — an icon in a different style
reads as a bug rather than as content. `tools/make_shrine_assets.py::build_icon`
draws one by rasterising a material-id mask (supersampled, so diagonals are not
jagged) and then *growing that finished mask* for the outline; stroking each
shape separately instead leaves seams where they meet.

One trap worth keeping: the outline ring grows `r` px outward from every filled
pixel, so two shapes closer than `2*r` fuse. The shrine's crystal is supposed to
float, and at `r=2` it needed >4px of clear space to still read that way.

### Source art stays source art

A mod ships `.glb` and `.png` under `mods/<id>/art/` — outside `assets/`, so
`Mod.files()` never sweeps them into the game install as uncooked overrides.
`rsmm apply` cooks them, names the results, and generates the material, prop
entity, level, prefab, tiledef and pool patches around them. Editing the `.glb`
and re-applying propagates the change; the author's file is never converted in
place or replaced. `tests/test_poi.py` covers the whole path, asserting the
cooked geometry carries the mod's vertex count and not the donor's.

### A cloned level needs its own GUID — this is why nothing appeared

The first playtest placed **zero** POIs, with 8 pool copies, everything cooked,
registered, planted and resolving. The cause was invisible to every static
check:

A tile **level** carries a 16-byte identity GUID in its literal stream (the
`oCGameLevelIdentifierRFI` serialises it before the display name; it sits at
offset 0 of `_literals[1]`). **All 228 shipped tile levels have a distinct
one.** A clone that keeps its donor's collides with it in the level registry,
and the tile simply never gets placed — no log line, no crash, no failed
lookup. `clone_tile_level` now re-stamps it, derived deterministically from the
new resource path (map generation is seeded run state, so a random GUID would
desync multiplayer and break reproducible builds).

Two neighbouring fields look identical and must be left alone — uniqueness
across the corpus is the only thing that separates them:

| field | distinct values | verdict |
|---|---|---|
| level GUID (`_literals[1]` +0) | 228 / 228 | identity — re-stamp |
| prefab entity GUID-shaped field | 168 / 226, one value shared by 37 tiles | type tag — leave |
| level display name (after the GUID) | three levels all say `6x6_Healing_01` | not identity — leave |

The general lesson for this whole chain: **a clone is not only its references.**
Rewriting every string path produced an asset that resolved perfectly and still
did nothing.

### Every tiledef needs a UsedRscCache

After the level GUID was fixed the shrine *still* never appeared, and the game
then crashed at boot. Both had one cause.

Every cooked tiledef ships a sibling **`<name>.tiledef.UsedRscCache.ot`** — a
plain-text preload manifest, one resource per line,
`<Root>|<Decoded\Path>|<oCClass>`:

```
EntitySettings|DarkHills\SceneryObjects_DarkHills\Wall_Ruins_Block_Small_A.entity.ot|oCEntitySettingsResource
3D|Scenery\DarkHills\Wall_Ruins_Block_Small_A.fbx|oCGeometry
Ot|DarkHills\Tiles\40x40_DarkHills_Starting_Tile_Update3.level.ot|oCGameStream
```

It is the tile's full transitive dependency closure — the Dark Hills start tile
lists 784 resources. **237 of 237 shipped tiledefs have one. No exceptions.**

The engine finds it **by convention, not through `UsedRscList.ot`** — none of
the 575 shipped caches has a manifest record. `sub_140311110` concatenates the
literal `.UsedRscCache.ot` (a 17-byte copy at `0x14031165b`, incl. NUL) onto the
resource name and then runs the same `\` → `!` filename collapse every cooked
path gets. Because they are absent from `UsedRscList.ot` they are also absent
from `asset_map.json`, so `extract_uncooked.py` mirrored **zero** of them until
`cache_pairs()` was added — the identical blind spot the FMOD sound banks have.

**It applies at two levels, and missing either one hides the POI.** The mapdef
has a cache of its own that lists its pool's tiledefs **one for one** — Dark
Hills: 77 pool entries, 77 `|oCDtTileDefinition` lines. A tile appended to the
pool but absent from the map's cache is never loaded, so it is never placed.
Fixing only the per-tile caches left the shrine invisible for one more
playtest; the assertion worth keeping is `pool ⊆ map cache`, which
`tests/test_poi.py` now checks per chapter.

Three ways to get it wrong, all three hit in-game on 2026-08-10:

* **No cache** (a new tiledef) — the engine has nothing to preload, so the tile
  is registered, never placed, and reports nothing. This, not the pool, is why
  a POI added to a mapdef pool never showed up.
* **Pool extended, map cache not** — the chapter loads its 77 cached tiledefs
  and simply never sees the 78th, however correct the pool entry is.
* **Stale cache** (`replace_base` edits a shipped tile in place) — the tiledef
  now reaches assets its cache never listed. The missing resource leaves a
  **null** in the preloaded pointer vector, and the teardown loop at
  `0x140476f60` destroys every element of that vector *without a null check*:

  ```
  0x140476f6a:  mov  eax, [rcx + 0x88]        ; count
  0x140476f90:  mov  rcx, [rbx + 0x80]        ; array base
  0x140476f97:  mov  rcx, [rcx + rdi]         ; element  <- NULL
  0x140476f9b:  call 0x1401273b0              ; destroy(obj)
  0x1401273b6:  mov  rax, [rcx]               ; ACCESS VIOLATION, rcx = 0
  ```

  Crash chain `0x14074677f → 0x140482d90 → 0x140476f60 → 0x1401273b0`, reading
  address 0, nowhere near the actual mistake.

⚠ `data/symbols.json` names `0x1401273b0` `NamedEvent_Delete`. It has **358
callers** — it is the generic `destroy(obj)` thunk (`call vtbl[1]`, then tail
`jmp vtbl[2]` with `edx=1`, the scalar deleting destructor). Do not read that
name as evidence the crash involves named events.

`rsmm.engine.rsc_cache` builds these. The generated cache is the donor tile's
**plus** a line per emitted asset — deliberately append-only: a surplus line
costs a wasted preload of a real shipped file, a missing one crashes the game,
and proving a line is safe to drop would need the whole reference graph.

### Rare kinds are not broken kinds

A POI competes only against pool entries declaring the **same kind**, so its
share is `copies / (copies + vanilla entries of that kind)`. Dark Hills has
2 `Fountain` entries but 7 `Blocker`, 15 `Camp` and 15 `Special`. Six copies of
a `Fountain` tile win 75% of Fountain slots and are still barely seen, because
the chapter only lays down one or two Fountain slots. That is a *frequency*
problem masquerading as a *correctness* problem, and it wasted a playtest —
`poi.kind_pool_counts()` now reports the share at emit and warns below three
vanilla entries.

### Traps worth keeping

* **Repoint every LOD.** A scenery donor references its mesh once per LOD. Miss
  one and the prop silently pops back to the donor's shape at distance.
* **A tile level names itself twice** — the full `…\X.level.ot` resource path
  and a bare `…\X` identifier. Both must move or the clone collides with the
  original in the level registry.
* **Validate that replacements fired.** A material texture key or an object ref
  that matched nothing leaves the clone pointing at the donor's art, which
  in-game reads as "my texture didn't apply" and is miserable to trace. Both
  clone helpers raise instead.
* **A kind has a footprint, not just a name.** Every shipped `Wishing_Well` is
  40x40, so a 6x6 tile declaring that kind can never fill one of its slots — it
  reads as a free way to compete for more slots and is dead weight.
  `poi.kind_footprints()` gates this.
* **New assets need a same-kind sibling** in the same decoded directory, twice
  over: `synthesize_encoded` clones an encoded prefix from one, and
  `build_usedrsc_record` clones a 3-line manifest record from one. Filing
  custom art in an existing vanilla directory satisfies both; a fresh
  `Definitions/Tiles/<Mod>/` satisfies neither and is warn-and-skipped.
* **A `*.UsedRscCache.ot` must NOT get a UsedRscList record.** It is loaded by
  convention; registering it appends a 3-line group cloned from a sibling that
  isn't in the manifest either. `plan_apply` skips them explicitly.
* **Never let apply back up its own output.** A second apply over a mod-added
  file used to record the *previous build's* bytes as "the vanilla original",
  so `restore` resurrected a generated file instead of deleting it. `apply_one`
  now checks the state's `orig_sha256` first, and warns loudly when an existing
  install already carries a poisoned entry.

### Worked example

`mods/runestone-shrine` — an obelisk with procedurally painted granite, carved
runes and a floating crystal, in all three chapters. Ships 4 authored files
(mesh + 3 maps); `apply` derives the other 8. Chain walked end to end, all 12
assets resolve, 9 register cleanly. **Not yet playtested.**

## Interaction: the engine already has a system

> Status: located 2026-08-14, statically. Nothing in this section has been
> observed at runtime yet — `mods/poi-interact-probe` is the instrument.

The first question for "make a POI do something" was whether the game has an
interaction system worth integrating with or whether one has to be built. It
has one, and it is more complete than anything a mod could reimplement.

### The four classes

| Class | Role |
|---|---|
| `oCDtEntityCpntInteractionSettings` | authored, per entity — the design data |
| `oCDtEntityCpntInteraction` | the runtime component (30-slot vftable @ `0x140f26cd0`) |
| `oCDtEntityCpntInteractionNetworkData` | its replicated half, and the only one in the serializable class registry (uid `0x181ffce3`, 0xd0 bytes) |
| `oCDtNamedEventInteraction` | the event object (vftable RVA `0xf21130`), payload words at +0x38 and +0x50 |

**122 shipped entity defs carry interaction settings** — every chest, both
fountains, the wishing well, the Altar of Heroes and its payment slot, the
Leprechaun cauldron, both teleporter families, the grimoire, the astrolab, the
hourglass, ruins, drop bags, the key lock and key keeper, Baba Yaga's eye, the
thieves' magic mirror. Grep is enough to find them:
`grep -rli interaction data/uncooked/EntitySettings`.

### It is a state machine authored in the entity, not code

`EntitySettings/Interactive_Common/Interactive_Object_Model.entity.ot` is the
base every interactive object inherits, and its GPN node names read as the
design doc for the whole feature:

```
State Interaction Available          State Interactive Hero Detected
State Interaction In Progress        State Interaction Locked In Combat
Event Initialize Interaction         Event Current Hero Interact
Event Interaction Success            Event Interaction Available At Start
Can Interact Master Condition        Max Player Interact Tester
Start On Input Held Condition        Show Interaction For Everyone Condition
Interaction In Combat Tester         Interaction Is Locked Custom Condition
Interaction Available After Interaction Success Tester
Input Game Ui / Input Icon           oCUICircularGaugeDesc
```

So hold-to-interact, the button prompt, the filling ring, the "not during
combat" lock, the multiplayer "how many heroes may use this" gate and the
one-shot-vs-repeatable rule are all **already implemented and already
authored**. A mod that wrote its own proximity test and its own prompt would be
reproducing that badly and would not match the game's look.

### The bus protocol

Seven names in `gameplay_event_catalog`, category `world`:

```
INTERACTION_REQUEST ─► INTERACTION_VALIDATE ─┬─► INTERACTION_SUCCESS
                                             ├─► INTERACTION_REJECT
                                             ├─► INTERACTION_FAILED
                                             └─► INTERACTION_CANCELED
LOCAL_INTERACTION_SUCCESS   the local peer's own copy
```

That is a host-authoritative request/validate/commit shape, which matches the
netcode ([MULTIPLAYER.md](../MULTIPLAYER.md)): a client *asks*, the host
decides. A mod must therefore treat `REQUEST` as an intent that may not be
granted and hang real effects off `SUCCESS` / `LOCAL_INTERACTION_SUCCESS`.
All four of `REQUEST`/`VALIDATE`/`SUCCESS`/`LOCAL_INTERACTION_SUCCESS` were
captured live in the 2026-06-12 bus session, and `INTERACTION_VALIDATE` is one
of the reliably **hero-anchored** dispatchers the SDK already uses to locate
the local hero.

Downstream outcome events exist per object family — `OPEN_CHEST`,
`USE_HEAL_FOUNTAIN`, `USE_BLOOD_FOUNTAIN`, `WISHING_WELL_FILLED`,
`ALTAR_OF_HEROES_PAID`, `TELEPORT_SUBMAP_ENTER` — so an outcome is observable
even where the interaction payload is not yet understood.

### What is NOT known

**Which object was interacted with.** `oCDtNamedEventInteraction`'s payload was
mined by vftable, which recovers offsets and widths but never meaning, so
`+0x38` and `+0x50` are two anonymous words. Until they are pinned, a mod can
know that *an* interaction succeeded but not that *its own* POI was the target
— which is the difference between a real API and a curiosity.

`R.interact` (in `src/loader/lib/rsmm.lua`) publishes them verbatim as `a` and
`b` alongside the dispatcher, and `R.interact.identify(ptr)` walks a pointer's
fields for a resource path (the engine names everything by string path, so if
the target is reachable at all it is nameable). `mods/poi-interact-probe`
drives both and prints the harvest for the first few interactions of a session.
One playtest — open a chest, drink a fountain — decides the API shape:

* a path under `a`/`b` ⇒ key mod behaviour on the target path directly
* a path under `disp` only ⇒ the dispatcher *is* the object; key on that
* no path anywhere ⇒ identification needs the component
  (`Entity_FindComponentByType`), not a string walk

### The two integration routes, and which to prefer

1. **Data — inherit a working interaction.** Because custom art is
   [in-place only](#custom-art-the-full-reference-chain-shipped-2026-08-10), a
   POI is a re-skin of a shipped prop; choosing an *interactive* prop as the
   donor means the mod's structure is interactive with zero engine work, with
   the vanilla prompt, gauge, combat lock and multiplayer gating. The cost is
   the usual in-place cost: every instance of that donor changes, and the
   behaviour is the donor's (a re-skinned chest gives chest loot).
2. **Runtime — react on the bus.** Subscribe to `SUCCESS`, identify the
   target, and run mod-authored effects through the SDK levers that already
   exist and are proven in-game: `R.give` (items), `R.stat` / `R.combat`
   (trade HP for damage), `R.xp`, `R.modifier`, `R.emit` (ask the engine for an
   effect it already implements, as `lucky-chests` does).

Route 1 supplies the *interaction*; route 2 supplies the *outcome*. Together
they cover the trading / utility / cosmetic cases without inventing a second
interaction system. Authoring a genuinely new `oCDtEntityCpntInteractionSettings`
— a new prompt on a prop that has none — is a third route and is not attempted:
it means writing GPN graph nodes into an entity payload that is still `_pre_hex`
to the codec, on top of the in-place-only constraint.

## Picking a donor: measure the run, do not reason about the corpus

> 2026-08-14. The obelisk renders in-game on `Pebbles_4x4`. Getting there cost
> four playtests, and none of them were lost to the cook — they were lost to
> two wrong beliefs about which props are eligible and which are on screen.

### The composite gate was rejecting most of the scenery corpus

`_assert_prop_is_not_composite` counted every child `EntitySettings` reference.
But nearly every scenery prop in the game carries
`Common_Settings\Environment_Perf_Profile_Tester`, an entity with **no geometry
at all**. Counting references therefore rejected `Pebbles_*`, `Wall_Ruins_*`,
`Skull`, `RibCage` and most of their neighbours, and left a survivor set of
oddities — which is where the "only 14 props in the whole corpus qualify" line
came from, and why donor choice kept landing on strange props.

A child only disqualifies a donor if its own entity references a mesh; a child
that cannot be resolved still counts as drawing, so the guard fails closed. The
real failure it exists for — `Blood_Fountain`, eight children *with* meshes —
is still refused.

Effect on the eligible population, Dark Hills pool only, requiring one mesh, no
other entity using that mesh, placement by exactly one tile, tilt <= 10 deg and
unit scale:

| | eligible donors |
|---|---|
| old gate | 11 |
| fixed gate | **42** |

Good ones, with `Camp` reach (the most common POI-ish kind): `Menhir_Big_A` and
five sibling menhirs in `64x64_Dark_Hills_Menhir_Cultist_Camp` (a stone circle,
all exclusive, tilt 0), `Tombstone_Big_A_Scrap_A/B`, `Hamlet_House`,
`Stone_Table`, `Cage_Small`, `Cliff_Chunk_A`.

### A donor can be eligible and still never be on screen

`Carpet_4x4` passes every static test and sits at (-9.74, 2.05, -9.64) in the
start tile — **0.36 units from `NPC_Sandman`**. It is the rug under the Sandman,
who does not spawn every run. A conditional donor makes a mod that appears
sometimes, which is indistinguishable from a mod that does not work.

Placement records are decodable and worth decoding before choosing. Anchor on
the `EntitySettings` root string in `*.level.ot.GameStream.gen`; the 42 bytes
before it are 3 floats position, 4 floats quaternion, 3 floats scale, `u16`
flag. Measure the tilt of the rotated local **+Y**, not the quaternion angle —
the latter includes harmless yaw.

### Watching what the engine actually opens

`scratchpad/watch_io.py` drives inotify through `ctypes` (there is no
`strace`/`inotifywait` here) over the cooked directories and prints every open
with the filename **decoded** through the cipher. One Dark Hills load is ~2200
distinct opens, ~950 of them geometry. atime is no substitute: `relatime` only
bumps atime when it is older than mtime, and `apply` leaves atime newer.

**⚠ The trace is blind to your own overrides.** The loader's `hook_CreateFileW`
calls `Loader::lookup_override(leaf)` and, on a hit, opens the mod's copy under
`<game>/mods/<id>/assets/` instead — so an overridden file is *never* opened at
its cooked path while the loader runs. Two consecutive traces showed exactly
the file we had replaced as "never opened" and everything else present, which
reads as "the prop is not in the scene" and is wrong. Watch the redirect target
as well as the cooked directory, or the instrument will confirm whatever you
already believe.

### What an in-place override does and does not change

Confirmed in-game on the pebbles donor: the mesh is replaced, and **nothing
else is**. The player walks through the obelisk, because collision is a
separate `oCCollisionMesh` that still belongs to the donor, and the surface
keeps the donor's material (`M_Rock_Pebbles`) unless the def ships textures.
Pick a donor whose collision and material you can live with, or ship those too.

`allow_shared_art` is global by construction: `Pebbles_4x4` is placed by 15 tile
levels, so every pebble pile in the chapter became an obelisk. That is the right
setting for a diagnostic and the wrong one for content.

## Minimap icons come from the ENTITY, not the tile

> Confirmed in-game 2026-08-14, after two null results that both looked like
> "the override did not apply".

A tiledef carries an `icon` `tresptr`, 139 of 237 shipped tiles set one to a
`Ui` path, and **none of that reaches the minimap**. Repointing the Dark Hills
teleporter tiledef's icon — a tile that is in every run and whose icon is
unmissable — changed nothing on the map. So the field is editor/authoring
metadata, not the runtime source.

What draws the minimap is an entity component:

```
oCDtEntityCpntMinimapMarker            runtime
oCDtEntityCpntMinimapMarkerSettings    authored, in EntitySettings
oCDtEntityCpntMinimapMarkerUiController
oCDtEntityCpntMinimap / …Settings / …UiController   the view itself
```

Exactly **12 shipped entities** carry marker settings, and each names *two*
icon textures — the normal one and a zoomed `High\` variant:

| entity | map icon | high-zoom icon | mesh |
|---|---|---|---|
| `Objects_Common\Teleporter_Model` | `Map_Icons_Crow_Mark` | `Minimap_IconHigh_TP` | `Teleporter_Crow_Nest` |
| `Objects\Reward_Spawner_Interactive_Model` | `Map_Icons_Common_Chest` | `Minimap_IconHigh_Chest` | — |
| `Objects\Map_Boss_Spawner\Map_Boss_Spawner_Model` | `Map_Icons_FinalBoss` | `Minimap_IconHigh_Boss` | `Boss_Tile_Ground_Rim` |
| `DarkHills\Jack\Collectible_Bean` | `Map_Icons_Bean` | `Minimap_Icons_High_Bean` | `Bean_Bag` |

plus `Key_Keeper_Key`, `Teleporter_Map_Boss`, `Minimap_Ping`,
`Minimap_Warning_Ping`, `Minimap_Marker_Reveal_Model`, `Orchard_Minimap_Marker`,
`Stairs_Location_Minimap_Marker`, `Reserve_MiniMap_Location_Model`.

**The consequence for POIs is structural.** An icon belongs to the entity
standing in the tile, and an in-place override cannot add a component — so a
POI can carry a map icon only if its donor is already one of those 12. Those
donors are teleporters, chest spawners, boss spawners and quest collectibles,
i.e. **objects that are also interactive**. The icon constraint and the
interactivity question have the same answer.

### In-place texture overrides work, and the format need not match

Writing the mod's icon over
`Ui\MiniMap\Icons\Map_Icons_Crow_Mark.png.Texture.dxt` changed every
teleporter's map icon in-game. Two things fall out of that:

* the texture cook is sound end to end — which retroactively explains the first
  checker-albedo diagnostic, whose prop simply was not on screen;
* the engine accepted **RGBA8** (fmt 0, 48x48, payload 9216) in a slot the game
  shipped as **BC3** (fmt 5, payload 2304). The SDK has no DXT compressor and
  does not need one. Format enum lives right after the dimensions in the cooked
  header: `0 = RGBA8, 4 = BC1, 5 = BC3` (and shipped textures store the base
  level only — the field that looks like a mip count is the format).

UI art cooks under the `Ui/` root, not `3D/` — `PC.ui_cooked_path`.

## Additive POIs: the wall is the LEVEL, not the name

> Measured 2026-08-14, with `RESTAMP_ENTITY_GUIDS = True` — the retest that had
> been armed and unplayed since 2026-08-13.

`mods/additive-poi-test` shipped both layers at once and the IO trace told them
apart by filename:

| layer | what it introduces | result |
|---|---|---|
| `plain_clone` | a new **tiledef** name only (donor prefab, donor level, donor props) | **works** — all 4 opened by the game, pooled, cached, no crash, twice |
| `custom_clone` | new tiledef **+ prefab + level + prop entity** | **crashes at level build** |

Disabling only `custom_clone` and relaunching produced a clean run, which is
the attribution: the tiledef half is innocent.

The crash is the documented null-resource signature —
`EXCEPTION_ACCESS_VIOLATION` read @ 0 at `0x1401273b6`, reached through
`0x140746784 → 0x140482dbe → 0x140476fa0`. Register state differed from the
2026-08-10 crashes (`rsi=3, rdi=0x80` vs `rsi=0xb, rdi=0x4e0`), so it is a
different element of the same preloaded pointer vector, destroyed without a
null check.

So the rule recorded earlier — "a level cannot reference an asset the mod
introduces" — was too broad in one direction and too narrow in another. What
holds is:

* **mod-owned tiledefs are fine**, including their `UsedRscCache`, their
  mapdef pool entry and the map cache line that goes with it;
* **mod-owned levels are not**, nor are the entities a level references.

### The combination that gives a mod its own POI

Both halves that DO work compose:

```
mod-owned tiledef  ──points at──▶  a SHIPPED level
                                      │ places
                                      ▼
                            a prop exclusive to that tile
                                      │ art overridden in place
                                      ▼
                                 the mod's mesh
```

The tile is the mod's (poolable, weightable, `copies`-able, so its frequency is
a design choice rather than luck); the structure is the mod's; and no mod-owned
level exists for the engine to null. This is the shape a `poi` should take
today.

What it still cannot have is a **minimap icon**, and the reason is structural
rather than incidental: icons come from `oCDtEntityCpntMinimapMarkerSettings`
on an entity, an in-place override cannot add a component, and owning an entity
is precisely what `custom_clone` proved impossible.

### The one experiment still worth running

`custom_clone` changed four things at once. A middle layer — new tiledef +
prefab + level, placing **only shipped entities** — separates "a mod's level"
from "a level referencing a mod's entity". If a mod-owned level that places
nothing new loads, then levels are fine and only entity names are cursed, which
would make custom prop placement (rather than in-place re-skinning) reachable.
