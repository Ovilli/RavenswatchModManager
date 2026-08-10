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

## Two gates, not one

This is the part that matters, and it is why "add a POI to a chapter" is a
data edit rather than an engine problem:

| Gate | Where it lives | What it decides |
|---|---|---|
| **kind** | `Map_<Biome>_..._TileGeneration.level.ot` | which tile *kinds* each map slot accepts |
| **pool** | the chapter's `*.mapdef.ot` | which concrete tiledefs the map may draw from at all |

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
donor's behaviour, but authoring new behaviour is a different problem and is
not attempted here.

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

### Worked example

`mods/runestone-shrine` — an obelisk with procedurally painted granite, carved
runes and a floating crystal, in all three chapters. Ships 4 authored files
(mesh + 3 maps); `apply` derives the other 8. Chain walked end to end, all 12
assets resolve, 9 register cleanly. **Not yet playtested.**
