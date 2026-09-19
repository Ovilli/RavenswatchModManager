---
title: First mod, by kind
description: A minimal, working manifest for every content kind — what it changes, how to prove it in game, and the one trap that bites first.
---

Fifteen content kinds ship with the SDK, and every one of them starts the same
way: a folder under `mods/`, a `manifest.toml`, `rsmm apply`. What changes per
kind is the handful of fields in the `[[content]]` block — and the way you
prove the change actually landed.

This page is one starting mod per kind. Each snippet is a **complete**
`manifest.toml`: copy it into `mods/<id>/manifest.toml`, adjust the ids, apply.

:::note[Before the first one]
Read [Your first mod](/getting-started/first-mod/) for the scaffold, and
[Content kinds & confidence](/reference/sdk-api/kinds/) for which kinds are
proven in-game. A kind rated below `confirmed` needs `experimental = true` in
`[mod]` — the snippets below already carry it where it is required.
:::

## The loop, every time

```sh
./rsmm new MyMod          # scaffold mods/MyMod/
./rsmm lint MyMod         # manifest, asset paths, confidence gate
./rsmm restore --all      # back to vanilla first — restore wipes the loader
./rsmm apply              # install this mod's files
./rsmm install-loader     # re-plant the loader (apply does not)
./rsmm run                # launch through Steam
```

`restore --all` before every `apply` is not superstition: it is how you avoid
testing a mod on top of the last one's leftovers, and it is the uninstall path
you should expect to work at the end.

---

## `item` — a new magical object

**What the player sees.** A brand-new item in the compendium that drops, is
offered by chests, and works.

```toml
[mod]
id          = "SwiftAttacks"
name        = "Swift Attacks"
version     = "0.1.0"
author      = "you"
description = "A faster cousin of the Ace card."

[[content]]
kind  = "item"
id    = "Swift_Attacks"      # SAME BYTE LENGTH as base (13) — see the trap
base  = "Damage_Attack"
name  = "Swift Attacks"
description = "Attack speed, and nothing else."
value_patches = [["Attack Speed Value", 0.15, 0.30]]
```

**Prove it.** Start a run, open the compendium — the item is listed. Then take
it from a chest and watch the value you patched.

**Trap.** The clone pipeline is length-preserving: `id` must match `base` in
byte length. Browse bases with `./rsmm items list`, and a base's editable
value labels with `./rsmm items show <base>` — a label marked `shadowed`
accepts the edit and changes nothing in game.

**Also does the opposite.** `mode = "ban"` with `items = [...]` removes vanilla
items from the catalog instead — the multiplayer-correct way to disable one.

---

## `talent` — retune a talent

**What the player sees.** The same talent card, different numbers.

```toml
[mod]
id          = "JulietBuff"
name        = "Juliet Talent Buff"
version     = "0.1.0"
author      = "you"
description = "Juliet's dash shield lasts longer."

[[content]]
kind = "talent"
id   = "dash_shield_duration"
hero = "Juliet"
file = "Hero_Juliet.entity"
value_patches = [
  { label = "Skill Dash Shield Duration", old = 6.0, new = 9.0 },
]
```

**Prove it.** Take the talent in a run and read the card: the number moves.

**Trap.** A label can exist in several of a hero's entity files, and some values
are *shadowed* by an override node — the writer handles both, but you have to
name the label exactly, and `old` must match the shipped number or the apply
stops. Find labels, their files and their numbers with
`./rsmm talents Juliet --grep shield`, and see the
[talent tutorial](/guides/talent-tutorial/) for the card-text placeholders.

---

## `mesh` — put your model in the game

**What the player sees.** A shipped prop, weapon or body wearing your geometry.

```toml
[mod]
id          = "ShrineBlock"
name        = "Runestone Block"
version     = "0.1.0"
author      = "you"
description = "Replaces a ruin block with a runestone."

[[content]]
kind   = "mesh"
id     = "shrine_over_ruin_block"
target = "Scenery\\DarkHills\\Wall_Ruins_Block_Small_A.fbx"
model  = "art/shrine.glb"
```

**Prove it.** Walk a chapter that places the target mesh. Your shape is there,
lit and textured, with no other change.

**Trap.** The override is **global**: every tile that places that mesh now shows
yours. And replacing a *character* needs the right `transform.skin` —
`"gltf"` when you rigged to the game's bone names, `"rigid"` when you did not.
The default (`"transfer"`) assumes your mesh occupies the same space as the one
it replaces, and shreds a differently-shaped body on the first animation frame.

---

## `poi` — a structure in a chapter

**What the player sees.** A shrine / cauldron / camp appearing on a map that
never had one.

A POI is a folder, and needs no `[[content]]` block at all. The mod's
`manifest.toml` is just the `[mod]` table; everything else lives beside the
model:

```
mods/MyShrine/
  manifest.toml
  pois/runestone_shrine/
      poi.toml
      model.glb
      albedo.png  normal.png  mra.png  icon.png
```

This is the shrine that was proven in game end to end: tile, mesh, minimap
marker and interaction.

```toml
# pois/runestone_shrine/poi.toml
base     = "Dark_Hills/6x6_Crystal_01"   # the tile it is generated as
chapters = ["Dark_Hills"]
kinds    = ["Crystal"]                   # which generator slots it may fill
copies   = 1

replaces      = "Objects_Common\\DreamCrystal_Medium.entity.ot"
entity_base   = "DarkHills\\SceneryObjects_DarkHills\\Wall_Ruins_Block_Small_A.entity.ot"
material_base = "Scenery\\DarkHills\\M_Walls_Ruins.mat.ot"
transform     = { fit = "rig", scale = 2.0 }
interactive   = true

[slots]
albedo = "Scenery\\DarkHills\\T_Walls_Ruins_ALB.tga"
mra    = "Scenery\\DarkHills\\T_Walls_Ruins_MRA.tga"
normal = "Scenery\\DarkHills\\T_Walls_Ruins_NRM.tga"

[marker]
icon          = "icon.png"
reveal_radius = 20000.0
```

**Prove it.** Run the chapter and look at the minimap: the icon draws, the prop
is interactable, and a mod can confirm its own placements from Lua
(`R.poi.placed`).

**Trap.** `kinds` must be slots that tiles of the base's size actually fill
— a 40×40 base can never fill a 6×6 `Fountain` slot, and the emit says so.
`weight` is a **tier**, not a spawn rate — raising it to make a POI
commoner is backwards. Use `copies`, which buys pool entries one for one.
Browse bases with `./rsmm poi list`.

---

## `enemy` — change what a camp spawns

**What the player sees.** Every Dark Hills camp full of treants, or a brand-new
creature among the usual ones.

```toml
[mod]
id           = "Treantfall"
name         = "Treantfall"
version      = "0.1.0"
author       = "you"
description  = "Dark Hills is a forest, and it has opinions."
experimental = true

[[content]]
kind   = "enemy"
id     = "treant_everywhere"
mode   = "override"          # rewrite a retail population in place
pools  = ["Dark_Hills"]
entity = "Enemies\\Treant\\Standard_Root_Treant.entity.ot"
```

**Prove it.** Load the chapter and fight the first camp: every creature in it
is a treant. List a biome's creatures with `./rsmm enemies pool Dark_Hills`.

**Trap.** `mode = "override"` is the proven half — it repoints what an existing
population *is*. `mode = "clone"` adds a NET-NEW definition, and that half has
not been seen spawning. Imported creatures can also bring projectiles and attack
zones the destination chapter never loads; see
[Custom enemies](/guides/custom-enemies/).

---

## `reward` — ban or retune what spawns at reward points

**What the player sees.** No more locked chests in Avalon, or fewer of them.

```toml
[mod]
id           = "NoLockedChests"
name         = "No Locked Chests"
version      = "0.1.0"
author       = "you"
description  = "Chests spawn unlocked."
experimental = true

[[content]]
kind = "reward"
id   = "avalon_rewards"
base = "Camp_Rewards_Avalon"
ban  = ["Chest_Locked"]
```

**Prove it.** Play the chapter and count what the reward points produce.

**Trap.** This bans reward *objects*, never talent or item *cards* — that lever
is the item catalog (`kind = "item"`, `mode = "ban"`). Each `ban` entry must
match something, deliberately: a typo fails the emit instead of silently doing
nothing.

---

## `shop` — change the Sandman's stock and prices

**What the player sees.** Different items in the in-run vendor, at your prices.

```toml
[mod]
id           = "CheapSandman"
name         = "Cheap Sandman"
version      = "0.1.0"
author       = "you"
description  = "Everything is half off."

[[content]]
kind        = "shop"
id          = "sandman"
price_scale = 0.5            # every Sandman item, half price
```

**Prove it.** Find the Sandman in a run and open the shop.

**Trap.** There is one Sandman, so a mod declares at most one `shop`. The seven
generators (`minor`, `medium`, `major`, the `*_duplicate` and `*_object`
variants) each decide count, quality and flag pool separately — changing one
does not move the others. A slot's `count` can go *down* but never above what
it ships with: the shop screen has a fixed number of widgets per slot.

---

## `tilegen` — a chapter's map-generation recipe

**What the player sees.** More camps, more wells, a differently-shaped map.

```toml
[mod]
id           = "BusyHills"
name         = "Busy Dark Hills"
version      = "0.1.0"
author       = "you"
description  = "More camps, more wishing wells."

[[content]]
kind    = "tilegen"
id      = "camps"
chapter = "DarkHills"
[content.kinds.Camp]
count = 8
[content.quotas]
Wishing_Well = 2
```

**Prove it.** Start a run in that chapter and count what generated.
`R.poi.on_generated` + `R.poi.placed` hand you every placed tile by name, so the
count can come from the spawner itself instead of the minimap. This exact
recipe generated 8 camps (vanilla 5) and 2 wells (vanilla 1) in game.

**Trap.** Edits are keyed by **name** and re-applied to the shipped recipe every
time, so a name the recipe no longer has fails the emit rather than landing on
whatever now sits at that index. `./rsmm map-editor` writes these blocks for you
from a 3D view of the chapter.

---

## `game_mode` — reorder the chapters of a run

**What the player sees.** A run that starts in Avalon.

```toml
[mod]
id           = "AvalonFirst"
name         = "Avalon First"
version      = "0.1.0"
author       = "you"
description  = "Chapter order: 2, 0, 1, 3."
experimental = true

[[content]]
kind     = "game_mode"
id       = "AvalonFirst"
base     = "All_Chapters"
chapters = [2, 0, 1, 3]
```

**Prove it.** Start a new run and read the chapter you land in.

**Trap.** A FIXED order is data-safe; per-run randomisation is not (it needs
engine RNG and multiplayer determinism). Chapter 0 may also be coupled to
first-run setup, so moving it is the fragile edit.

---

## `map` — make a chapter play a cloned map

**What the player sees.** A chapter that plays a mapdef of your own. Today it
looks like the base map: the clone reuses the base's terrain and still draws
its tiles from the base's pool.

```toml
[mod]
id           = "TwilightHills"
name         = "Twilight Hills"
version      = "0.1.0"
author       = "you"
description  = "Chapter 1 plays a Dark Hills clone."
experimental = true

[[content]]
kind    = "map"
id      = "Twilight_Hills"
base    = "Dark_Hills"   # Dark_Hills, Storm_Island, Avalon or Baba_Yaga
chapter = 0              # 0 Dark Hills, 1 Storm Island, 2 Avalon, 3 Baba Yaga
```

**Prove it.** `R.maps.chapters()` lists each chapter's map: the one you
repointed says `resref` and resolves to a mapdef that is not the vanilla one.

**Trap.** `chapter` overrides `All_Chapters` as a whole file, so it conflicts
with a `game_mode` edit in another mod (last writer wins). Tile generation
follows the base's tile-generation level back to the ORIGINAL mapdef, so pool
edits on the clone do nothing yet, and `tribe` has shown no visible effect.
To change what an existing chapter generates, `tilegen` and `poi` are the
proven tools.

---

## `skill` — relabel a talent

**What the player sees.** A talent with your name and description on the
level-up card and in the Skill Menu.

```toml
[mod]
id           = "DiveRename"
name         = "Dive, Renamed"
version      = "0.1.0"
author       = "you"
description  = "Attack Dive becomes Meteor."
experimental = true

[[content]]
kind        = "skill"
id          = "meteor"
hero        = "Aladdin"
source      = "Attack Dive"
name        = "Meteor"
description = "Come down harder."
```

**Prove it.** Open the hero's Skill Menu — the new text is there.

**Trap.** The default `mode = "relabel"` is the safe, count-neutral half: it
edits text only. `mode = "clone"` adds a NET-NEW herodef row, and the game
loading an added row is unproven — a hero's talent count is effectively fixed.

---

## `modifier` — a custom run mutator

**What the player sees.** A new toggle on the challenge screen — in theory.

```toml
[mod]
id           = "DoubleXp"
name         = "Double XP"
version      = "0.1.0"
author       = "you"
description  = "A relabelled MoreExperience."
experimental = true

[[content]]
kind        = "modifier"
id          = "DoubleXp"
base        = "MoreExperience"
name        = "Double XP"
description = "Twice the experience, twice the regret."
```

**Prove it.** Open the challenge screen and look for the row.

**Trap.** The def cooks and loads; a NET-NEW modifier *appearing in the UI* is
the unproven part — the slot count looks pre-sized to the vanilla set. A
modifier's effect is hardcoded C++ keyed by an entity-value id, so a clone
reuses an existing behaviour; new behaviour is layered in Lua via `R.modifier`.

---

## `melody` — retune one of the Piper's melodies

**What the player sees.** A lost melody that grants a different effect.

```toml
[mod]
id           = "HealierHeal"
name         = "Healier Heal"
version      = "0.1.0"
author       = "you"
description  = "Fully Heal reveals the map instead."
experimental = true

[[content]]
kind   = "melody"
id     = "fully_heal"
base   = "Fully_Heal"
effect = "Reveal_Map"        # must be another retail melody's stem
```

**Prove it.** Play the Piper, collect that melody, use it.

**Trap.** There are exactly twelve melodies and twelve icons, indexed by a dense
enum — so there is no thirteenth. This kind edits the twelve that exist and
refuses to pretend otherwise.

---

## `boss` — stage a boss chain

**What the player sees.** Nothing yet: this kind writes a per-piece manifest,
not cooked bytes.

```toml
[mod]
id           = "ShadowKing"
name         = "Shadow King"
version      = "0.1.0"
author       = "you"
description  = "Staged boss pieces."
experimental = true

[[content]]
kind      = "boss"
id        = "ShadowKing"
base      = "Gnoll_Shielded"
arena     = "Dark_Hills"
hp        = 12000
music_cue = "Boss_Theme_A"
```

**Prove it.** Inspect `mods/<id>/assets/_pending_bosses/ShadowKing/` — four
files mirroring the four parts of the chain (enemy def, timer component,
settings record, spawn trigger).

**Trap.** The picker/HP/arena offsets are an educated guess. Treat this as a
place to record intent until the RE lands, not as content to ship.

---

## `hero` — stage a new playable hero

**What the player sees.** Nothing yet — the hardest kind in the SDK.

```toml
[mod]
id           = "Kintaro"
name         = "Kintaro"
version      = "0.1.0"
author       = "you"
description  = "Staged hero manifest."
experimental = true

[[content]]
kind      = "hero"
id        = "Kintaro"
base      = "Juliet"
name      = "Kintaro"
abilities = [
  { name = "Oni Cleave", description = "A wide axe swing." },
  { name = "Bear Rush",  description = "Charge through the line." },
]
```

**Prove it.** `mods/<id>/assets/_pending_heros/Kintaro/` gets `hero.json`,
`skillprofile.json` and `i18n.json`.

**Trap.** `oCDtHeroDefinition` has no registered class UID and is created by its
parent record's deserializer, so a new hero needs the library singleton and a
roster detour that do not exist yet. **Reskinning an existing hero works
today** — that is `mesh` plus a texture override, both proven.

---

## Where to go next

- [Content kinds & confidence](/reference/sdk-api/kinds/) — the generated rating
  table, and the only place a rating is written down for readers.
- [Authoring mods](/guides/modding/) — the full manifest surface, patches,
  merges, load order.
- [Conventions & best practices](/reference/conventions/) — naming, pre-flight
  checklist, surviving game updates.
- [Example mods](/guides/examples/) — complete mods that ship in the repo.
