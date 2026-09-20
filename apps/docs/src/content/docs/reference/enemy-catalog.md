---
title: Enemy encyclopedia
description: Every enemy the game ships — base health, stagger, size, tribe, biome and tags, mined from the cooked data.
---

:::note[Generated file]
Built by `tools/mine_enemy_catalog.py` from the cooked corpus and checked in as
`data/enemy_catalog.json`. Do not edit this page by hand — re-run the tool.
:::

**81 enemy definitions** — 14 bosses and 67 others, across 26 tribes and 5 spawn pools.

## At a glance

| Rank | Count | What it means |
|---|---|---|
| Boss | 14 | Chapter bosses and the arena bosses. |
| Elite | 23 | The tougher variant a camp can roll. |
| Standard | 29 | The ordinary camp and wave population. |
| Minion | 15 | Summons, eggs and adds — spawned by something else. |

### The health ladder

Base health only — see the caveat below. This is the whole roster sorted into
tiers, which is the quickest way to see what is actually dangerous:

| HP | Enemies |
|---|---|
| **1000** | Baba Yaga |
| **350** | Faceless Nightmare |
| **300** | Dullahan Arthur, Hand Nightmare, Mordred, Ogre Cyclop, Roc Bird |
| **275** | Stingy Jack |
| **250** | Ogre Wood, Tentacle Master |
| **200** | Jinn, Marsh Ghoul, White Lady, Wolf |
| **180** | Crab |
| **150** | Baba Yaga Skull Fire, Tentacle Summon, Undead Hog Captain, Undead Hog Fisherman, Undead Hog Reaper, Witch Crone (Boss), Witch Stake (Boss), Witch Young (Boss) |
| **125** | Baba Yaga Skull Dark, Baba Yaga Skull Poison, Cultist Fanatic, Cultist Priest, Cultist Summoner, Gargoyle Bestial, Gargoyle Blood, Gargoyle Fire, Gnoll Chieftain, Gnoll Hunter, Gnoll Shielded, Knight Mage, Knight Spear, Knight Sword, Snake Nightmare, Spider Nightmare Elite, Spider Nightmare Spitter, Stalker Nightmare, Tentacle Nightmare, Thief Assassin, Thief Brigand, Thief Marksman |
| **120** | Evil Jinn, Ifrit Jinn, Storm Jinn |
| **100** | Baba Yaga Tentacle Summon, Cultist Summoner Summoned Eye, Faceless Eye, Festering Ghoul, Phoenix Egg, Roc Egg, Wolf Alpha, Wolf Dire, Wolf Timber |
| **80** | Cultist Summoner Summoned Tentacle |
| **70** | Coral Crab, Mud Crab, Reef Crab |
| **60** | Devouring Ghoul |
| **45** | Spider Nightmare Biter |
| *default* | Baba Yaga House, Clawed Treant, Day Scarecrow, Enchanted Scarecrow, Knight Skeleton, Lumbering Treant, Night Scarecrow, Nightmare Small Stalker, Phoenix Roc, Rocling, Root Treant, Sling Ghoul, White Lady Lantern, White Lady Masked, White Lady Screaming, Witch Crone (Standard), Witch Stake (Elite), Witch Young (Standard) |

## How to read the tables

| Column | What it is |
|---|---|
| **HP** | `Raw Max Health` — the base the HitPoint component starts from. |
| **Stagger** | `Stagger Max Points` — stagger absorbed before it breaks. |
| **Radius** | `Collision Radius` — physical size, and how easily it is hit. |
| **Scale** | `Character Mesh Scale` — visual scale of the model. |
| **Resist** | `Default Resistance` — baseline damage resistance. |
| **Tags** | Definition flags that more than one enemy carries. |

Tables are sorted heaviest first. A dash means the enemy does not author that
attribute and inherits it. Where health comes from an ancestor rather than the
enemy's own entity, the ancestor is named under the table — that is the file a
mod would edit, and editing it changes **every** enemy that inherits from it.

Tags naming the enemy itself are omitted (75 of them occur exactly once,
because they are just the enemy's own name), as is the rank, which is a column.

:::caution[These are base values, and a dash is the shared default]
The run multiplies health by chapter and party size before you ever swing at
something, so a 70 HP crab is not 70 HP in chapter 3. Read these as relative:
a gnoll is roughly twice a crab.

18 enemies never author health and fall through to the
`Character_Common` default, which reads as **100**. The mining deliberately
stops before `Character_Common`: it *declares* these attributes rather than
overriding them, in a record whose payload sits under a different mark, so
reading it as an override produces junk. Everything in the tables **is** mined
from a real override; everything dashed is inherited.
:::

## Bosses

| Enemy | Rank | Tribe | HP | Stagger | Radius | Scale | Resist | Tags |
|---|---|---|---|---|---|---|---|---|
| Baba Yaga | Boss | Baba Yaga | 1000 | — | 2 | 1.3 | — | — |
| Faceless Nightmare | Boss | Faceless Nightmares | 350 | 200 | 3 | 1 | — | — |
| Dullahan Arthur | Boss | Dullahan | 300 | 200 | 1.8 | — | 0 | — |
| Hand Nightmare | Boss | Hands Nightmares | 300 | 200 | 2.15 | 1.8 | 0 | — |
| Roc Bird | Boss | Jinns | 300 | 300 | 2.75 | 1 | 0 | — |
| Tentacle Master | Boss | Tentacle Nightmares | 250 | 200 | 3 | 1.3 | 0 | — |
| Jinn | Boss | Jinns | 200 | 200 | 1.25 | 1.3 | 0 | — |
| Marsh Ghoul | Boss | Marsh Ghouls | 200 | 200 | 1.4 | 2.5 | 0 | — |
| White Lady | Boss | White Ladies | 200 | 200 | 1.2 | 1.6 | 0 | — |
| Wolf | Boss | Wolves | 200 | 200 | 2.5 | 2.2 | 0 | — |
| Crab | Boss | Crabs | 180 | 200 | 2 | 1.5 | 1 | — |
| Witch Crone (Boss) | Boss | Witches | 150 | 150 | 1 | 1.25 | 0 | — |
| Witch Stake (Boss) | Boss | Witches | 150 | 150 | 1.1 | 1.45 | 0 | — |
| Witch Young (Boss) | Boss | Witches | 150 | 150 | 0.9 | 1.25 | 0 | — |

## Where you meet them

Grouped by the biome spawn pool that streams the entity — an enemy whose
entity is not in a biome's pool is simply not there to instantiate, whatever
its tribe says. See [Enemies](/reverse-engineering/enemies/) for the two gates.

### Dark Hills

15 enemies.

| Enemy | Rank | Tribe | HP | Stagger | Radius | Scale | Resist | Tags |
|---|---|---|---|---|---|---|---|---|
| Undead Hog Captain | Elite | Undead Hogs | 150 | 100 | 1.3 | 1 | 0 | `DarkHills`, `Melee`, `Wave` |
| Undead Hog Fisherman | Standard | Undead Hogs | 150 | 50 | 1 | — | — | `Melee`, `Wave` |
| Undead Hog Reaper | Standard | Undead Hogs | 150 | 50 | — | — | — | `Melee`, `Wave` |
| Festering Ghoul | Elite | Marsh Ghouls | 100 | — | 1 | 1.8 | 0 | `Melee`, `Wave` |
| Devouring Ghoul | Standard | Marsh Ghouls | 60 | — | 0.8 | 1.3 | — | `DarkHills`, `Melee`, `Wave` |
| Enchanted Scarecrow | Elite | Scarecrows | — | — | 1 | 1.3 | — | — |
| Lumbering Treant | Elite | Treants | — | 125 | 1.8 | 1.7 | 0 | `Melee`, `Wave` |
| White Lady Masked | Elite | White Ladies | — | — | 1 | 1.3 | 0 | `Melee`, `Wave` |
| Clawed Treant | Standard | Treants | — | — | 1 | — | — | `Melee`, `Wave` |
| Day Scarecrow | Standard | Scarecrows | — | — | 1 | — | — | — |
| Night Scarecrow | Standard | Scarecrows | — | — | 1 | — | — | — |
| Root Treant | Standard | Treants | — | — | 1 | — | — | `Range`, `Wave` |
| Sling Ghoul | Standard | Marsh Ghouls | — | — | 0.8 | — | — | `Range`, `Wave` |
| White Lady Lantern | Standard | White Ladies | — | — | 0.8 | 1.05 | — | `Range`, `Wave` |
| White Lady Screaming | Standard | White Ladies | — | — | 0.8 | — | — | `Melee`, `Wave` |

Health inherited from `Undead_Hogs_Model`.

### Storm Island

12 enemies.

| Enemy | Rank | Tribe | HP | Stagger | Radius | Scale | Resist | Tags |
|---|---|---|---|---|---|---|---|---|
| Gnoll Chieftain | Elite | Gnolls | 125 | — | 1.3 | 1 | 0 | `Wave` |
| Gnoll Hunter | Standard | Gnolls | 125 | — | 0.9 | 1 | — | `Wave` |
| Gnoll Shielded | Standard | Gnolls | 125 | 50 | 1 | 1 | — | `Wave` |
| Ifrit Jinn | Standard | Jinns | 120 | — | 1 | 1.2 | — | `Wave` |
| Storm Jinn | Standard | Jinns | 120 | — | 1 | 1.15 | — | `Wave` |
| Roc Egg | Standard | Roc Birds | 100 | — | 1 | — | — | — |
| Phoenix Egg | Minion | Roc Birds | 100 | — | 1 | — | — | — |
| Coral Crab | Elite | Crabs | 70 | — | — | — | 1 | `Wave` |
| Mud Crab | Standard | Crabs | 70 | 75 | 1.3 | 0.85 | 1 | `Range`, `Wave` |
| Reef Crab | Standard | Crabs | 70 | 75 | 1.4 | 0.9 | 1 | `Melee`, `Wave` |
| Phoenix Roc | Elite | Roc Birds | — | — | 1.5 | 1.3 | 0 | `Wave` |
| Rocling | Standard | Roc Birds | — | — | — | — | — | `Wave` |

Health inherited from `Crabs_Model`, `Gnoll_Model`.

### Avalon

13 enemies.

| Enemy | Rank | Tribe | HP | Stagger | Radius | Scale | Resist | Tags |
|---|---|---|---|---|---|---|---|---|
| Gargoyle Blood | Elite | Gargoyles | 125 | 100 | 1.2 | 1.1 | 0 | `Wave` |
| Knight Mage | Elite | Knights | 125 | 125 | 1.3 | 0.85 | 0 | `Wave` |
| Knight Spear | Elite | Knights | 125 | 125 | 1.3 | 0.8 | 0 | `Wave` |
| Knight Sword | Elite | Knights | 125 | 125 | 1.5 | 0.85 | 0 | `Wave` |
| Gargoyle Bestial | Standard | Gargoyles | 125 | 75 | 0.85 | 0.8 | — | `Wave` |
| Gargoyle Fire | Standard | Gargoyles | 125 | 75 | 0.8 | 0.75 | — | `Wave` |
| Wolf Alpha | Elite | Wolves | 100 | — | 1.9 | 1.5 | 0 | `Wave` |
| Wolf Dire | Standard | Wolves | 100 | — | 1.45 | 1.1 | — | `Wave` |
| Wolf Timber | Standard | Wolves | 100 | — | 1.3 | 1 | — | `Wave` |
| Witch Stake (Elite) | Elite | Witches | — | — | 1 | 1.1 | 0 | `Wave` |
| Witch Crone (Standard) | Standard | Witches | — | — | 0.75 | 1.05 | — | `Wave` |
| Witch Young (Standard) | Standard | Witches | — | — | 0.8 | 1 | — | `Wave` |
| Knight Skeleton | Minion | Knights | — | — | 0.7 | 1 | — | — |

Health inherited from `Gargoyles_Model`, `Knights_Model`, `Wolves_Model`.

### Baba Yaga's realm

6 enemies.

| Enemy | Rank | Tribe | HP | Stagger | Radius | Scale | Resist | Tags |
|---|---|---|---|---|---|---|---|---|
| Baba Yaga Skull Fire | Minion | Baba Yaga | 150 | — | 1 | 1.2 | — | `Baba_Yaga_Skull` |
| Stalker Nightmare | Elite | Stalker Nightmares | 125 | 125 | 1.5 | 1.1 | 0 | `Wave` |
| Baba Yaga Skull Dark | Minion | Baba Yaga | 125 | — | 0.7 | 0.85 | — | `Baba_Yaga_Skull` |
| Baba Yaga Skull Poison | Minion | Baba Yaga | 125 | — | 0.8 | 0.95 | — | `Baba_Yaga_Skull` |
| Baba Yaga Tentacle Summon | Minion | Tentacle Nightmares | 100 | 75 | 1 | 1 | 0 | `Nightmare`, `Melee`, `Tentacle` |
| Nightmare Small Stalker | Standard | Stalker Nightmares | — | — | 1.15 | 0.75 | — | — |

Health inherited from `Baba_Yaga_Skull_Model`.

### Any biome

10 enemies.

| Enemy | Rank | Tribe | HP | Stagger | Radius | Scale | Resist | Tags |
|---|---|---|---|---|---|---|---|---|
| Cultist Summoner | Elite | Nightmare Cultists | 125 | — | 1 | 1.15 | 0 | `Nightmare`, `Wave` |
| Spider Nightmare Elite | Elite | Spider Nightmares | 125 | — | — | — | — | `Nightmare`, `Wave` |
| Tentacle Nightmare | Elite | Tentacle Nightmares | 125 | 125 | 2 | 0.7 | 0 | `Nightmare`, `Melee`, `Tentacle`, `Wave` |
| Thief Assassin | Elite | Thieves | 125 | — | 1 | 1.1 | 0 | `Melee`, `Wave` |
| Cultist Fanatic | Standard | Nightmare Cultists | 125 | — | 0.8 | — | — | `Nightmare`, `Melee`, `Wave` |
| Cultist Priest | Standard | Nightmare Cultists | 125 | — | 0.8 | — | — | `Nightmare`, `Range`, `Wave` |
| Thief Brigand | Standard | Thieves | 125 | — | 0.8 | 1.15 | — | `Melee`, `Wave` |
| Thief Marksman | Standard | Thieves | 125 | — | 0.8 | 1 | — | `Range`, `Wave` |
| Spider Nightmare Spitter | Minion | Spider Nightmares | 125 | — | — | — | — | `Nightmare`, `Range`, `Spider` |
| Spider Nightmare Biter | Minion | Spider Nightmares | 45 | — | — | 0.6 | — | `Nightmare`, `Melee`, `Spider` |

Health inherited from `Cultists_Model`, `Spider_Nightmare_Model`, `Tentacle_Nightmares_Model`, `Thieves_Model`.

### Summoned and unpooled

Not in any biome pool: adds that something else spawns, plus named enemies
placed by a specific encounter rather than by the camp generator.

| Enemy | Rank | Tribe | HP | Stagger | Radius | Scale | Resist | Tags |
|---|---|---|---|---|---|---|---|---|
| Mordred | Minion | Knights | 300 | 250 | 2 | 1.1 | 0 | — |
| Ogre Cyclop | Minion | Ogres | 300 | 300 | 2 | 1 | 0 | — |
| Stingy Jack | Elite | Stingy Jack | 275 | 200 | 0.8 | 1 | 0 | — |
| Ogre Wood | Minion | Ogres | 250 | 250 | 2 | 1 | 0 | — |
| Tentacle Summon | Elite | Tentacle Nightmares | 150 | 75 | 1 | 1 | — | `Nightmare`, `Melee`, `Tentacle` |
| Snake Nightmare | Elite | Snake Nightmares | 125 | 100 | 1.35 | — | 0 | `Nightmare`, `Wave` |
| Evil Jinn | Elite | Jinns | 120 | — | 1.25 | 1.3 | 0 | `Wave` |
| Cultist Summoner Summoned Eye | Minion | Faceless Nightmares | 100 | — | 0.5 | 1 | — | `Nightmare` |
| Faceless Eye | Minion | Faceless Nightmares | 100 | — | 0.5 | 1 | — | — |
| Cultist Summoner Summoned Tentacle | Minion | Tentacle Nightmares | 80 | 75 | 1 | 0.8 | 0 | `Nightmare`, `Tentacle` |
| Baba Yaga House | Minion | — | — | — | — | — | — | — |

Health inherited from `Faceless_Nightmare_Eye`, `Snake_Nightmare_Model`.

## Tribes at a glance

A tribe groups enemies for camp generation, and it is usually also where the
shared stats live — every gnoll is 125 HP because `Gnoll_Model` says so.

| Tribe | Biome | Members | HP | Health authored by |
|---|---|---|---|---|
| (no tribe) | — | 1 | — | *own entity* |
| Baba Yaga | Baba Yaga Map | 4 | 125–1000 | `Baba_Yaga_Skull_Model` |
| Crabs | Storm Island | 4 | 70–180 | `Crabs_Model` |
| Dullahan | — | 1 | 300 | *own entity* |
| Faceless Nightmares | — | 3 | 100–350 | `Faceless_Nightmare_Eye` |
| Gargoyles | Avalon | 3 | 125 | `Gargoyles_Model` |
| Gnolls | Storm Island | 3 | 125 | `Gnoll_Model` |
| Hands Nightmares | — | 1 | 300 | *own entity* |
| Jinns | Storm Island | 5 | 120–300 | *own entity* |
| Knights | Avalon | 5 | 125–300 | `Knights_Model` |
| Marsh Ghouls | Dark Hills | 4 | 60–200 | *own entity* |
| Nightmare Cultists | Common | 3 | 125 | `Cultists_Model` |
| Ogres | — | 2 | 250–300 | *own entity* |
| Roc Birds | Storm Island | 4 | 100 | *own entity* |
| Scarecrows | Dark Hills | 3 | — | *own entity* |
| Snake Nightmares | — | 1 | 125 | `Snake_Nightmare_Model` |
| Spider Nightmares | Common | 3 | 45–125 | `Spider_Nightmare_Model` |
| Stalker Nightmares | Baba Yaga Map | 2 | 125 | *own entity* |
| Stingy Jack | — | 1 | 275 | *own entity* |
| Tentacle Nightmares | Baba Yaga Map, Common | 5 | 80–250 | `Tentacle_Nightmares_Model` |
| Thieves | Common | 3 | 125 | `Thieves_Model` |
| Treants | Dark Hills | 3 | — | *own entity* |
| Undead Hogs | Dark Hills | 3 | 150 | `Undead_Hogs_Model` |
| White Ladies | Dark Hills | 4 | 200 | *own entity* |
| Witches | Avalon | 6 | 150 | *own entity* |
| Wolves | Avalon | 4 | 100–200 | `Wolves_Model` |

## Changing these numbers

Health is not on the enemy definition — it is an entity-value override on the
`oCEntitySettings` the definition points at, so a mod that edits the `enemydef`
changes tags and spawn weights and nothing else. See
[Enemies](/reverse-engineering/enemies/) for the definition layout,
[Anatomy of an entity](/reverse-engineering/entity-anatomy/) for why the number
lives where it does, and [Custom enemies](/guides/custom-enemies/) for the
authoring path.
