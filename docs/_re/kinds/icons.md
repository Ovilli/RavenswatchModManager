# Custom icons (UI textures under a mod's own name)

> RE session 2026-09-27. Static only: no new playtest. Every "proven" below cites
> an earlier in-game result.

## The "new texture name hangs the game" rule is disproven

`kinds/poi.py` (`MARKER_ICON`), `docs/_re/kinds/heroes.md` and the removed
`[marker] own_icon` option all state that a texture filed under a name the game
does not ship hangs level load (measured 2026-09-05). That measurement was never
isolated:

* it came from an uncommitted experiment (`mods/runestone-shrine/_parked/marker_own_icon`),
  so the code that produced it cannot be inspected;
* the same session found and fixed three other load-breaking faults in the same
  mod: the level self-length truncation (`ed9d302`), cache lines for resources
  that do not exist (`749e903`), and FX textures cached under the wrong root
  (`756341d`). Any one of them could have caused a load failure.

Two later in-game results contradict the rule directly:

| date | what drew | name | preloaded by |
|---|---|---|---|
| 2026-09-17 (`f673539`, poi CONFIRMED) | the shrine's minimap icon, additive route | `MiniMap\Icons\<tag>.png` + `High\<tag>.png` | the mod tile's own cache (`_decorate_host(in_place=False)` → `extra_deps`) |
| 2026-09-26 (Gretel) | 116 placeholder UI textures: ability/talent icons, HUD, book | `Heroes\Beowulf\Gretel_*.png`, … | the new herodef's cache + the family entity caches (`heros.py`, `art` lines) |

So a new UI texture name loads. What it needs is the same as any new resource:

1. **registration**: a 3-line `UsedRscList.ot` record cloned from a shipped
   sibling in the same folder (`apply_mods.synthesize_encoded` /
   `build_usedrsc_record`, automatic for any mod-added path);
2. **a string repoint** in whatever record names the icon;
3. **a `Ui|<path>|oCTexture` line in the cache that preloads that icon family**.
   Which cache that is depends on the family (next section).

## Which cache preloads which icon family

Scan of the 599 shipped `*.UsedRscCache.ot`:

| family | example | caches listing it |
|---|---|---|
| item icon | `Objects\UI_Object_GreenArmor.png` | **only** `LiveOps5.versiondef` (lists all 94) |
| ability / talent icon | `Heroes\Beowulf\Skill Dash Attack.png` | versiondef, `Beowulf.herodef`, `Avalon_LiveOps_Update5.mapdef` |
| hero portrait | `BookMenu\Heroes\UI_HeroPortrait_Piper_Active.png` | versiondef, `Piper.herodef` |
| minimap marker | `MiniMap\Icons\Map_Icons_Crow_Mark.png` (+ `High\`) | the tiledef cache of each of the 74 tiles that place a marker entity |

The two proven cases each wrote the cache of their family's owner: the herodef
for hero art, the tile for a marker.

## Engine side (static)

* `Resource_LookupByPath` (`0x14049b2a0`) is the path → cooked-file index
  lookup over the `UsedRscList` registry, not an "is it loaded" check. Its 11
  callers are resource-system internals and shader-block lookup
  (`FUN_140647ac0`: `ShaderBlocks` `.sb.ot`/`.px.ot`, `ShaderNodes` `.shnode`);
  no UI-specific path was found.
* `FUN_140492210` (just before `ResourceRef_Resolve`) maps a ref's
  {root, path} to its cooked name: root lookup (`FUN_14049cff0`), then
  `Resource_LookupByPath`; on a miss it builds `<root dir>` + path with
  `FUN_1404652c0` instead of failing. An unregistered path therefore still
  gets a file name, and fails later at load if that name has no file.
* `ResourceRef_Resolve` loads on demand, so an icon that is not preloaded may
  still resolve lazily. That is **not** proven for UI textures. The item
  compendium drops an item whose icon does not render (2026-06-02), so the
  preload line is treated as required.

## State per kind

| kind | custom PNG today | gap |
|---|---|---|
| `hero` | own names + herodef/entity cache lines | none (proven 2026-09-26) |
| `poi`, additive | own names + tile cache | none (proven 2026-09-17) |
| `poi`, in place (`replaces` a shipped prop) | repaints two shipped icons (`Map_Icons_Corpse`, `Minimap_IconHigh_Fountain2`) | two POI mods overwrite each other's art. Could use own names plus a line in each placing tile's cache, the way `extra_deps` already lists the repaint targets |
| `item` | own name `Objects\UI_Object_<id>.png`, registered | **fixed 2026-09-27**: `versiondef.sync_versiondef` now adds the icon's cache line (it only added the entity line before). Not yet playtested |
| `skill` | paints over the slot's shipped icon | changes that hero's icon everywhere. Own name needs the hero entity's icon string repointed plus a line in the herodef cache (and the versiondef cache, which lists hero icons too) |
| `talent` | no `icon` field at all | same route as `skill`: talent nodes in the hero entity carry their icon path |
| `melody` | override only | 12 dense indices and 12 icons, by design (`melodies.md`) |

## Playtest to close this out

1. An item mod with `icon = "icon.png"` (e.g. the item editor with a custom
   PNG): `rsmm restore --all && rsmm apply && rsmm install-loader`, start a
   run, and check (a) the item shows in the compendium, and (b) it drops with
   the custom icon. Pass → the item icon path is proven. The cache line is the
   only difference from the 2026-06-02 state.
2. If (1) passes, the in-place POI, `skill` and `talent` routes can move to own
   names by the same recipe, and the `MARKER_ICON` comment in `kinds/poi.py`
   plus heroes.md's portrait warning should be rewritten.
