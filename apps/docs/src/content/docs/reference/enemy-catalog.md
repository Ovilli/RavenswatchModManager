---
title: Enemy encyclopedia
description: Where every enemy in the game spawns, with the base health and stagger it ships with, mined from the cooked data.
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

## How to read the tables

| Column | What it is |
|---|---|
| **HP** | `Raw Max Health` — the base the HitPoint component starts from. |
| **Stagger** | `Stagger Max Points` — stagger absorbed before it breaks. |
| **Tags** | Definition flags that more than one enemy carries. |

`data/enemy_catalog.json` carries three more attributes the tables leave out:
collision radius and mesh scale, which describe how big the model is rather
than how it fights, and resistance, which is 0 for every enemy that authors it
except the four crabs, which are 1.

Tables are sorted heaviest first. A dash means the enemy does not author that
attribute and inherits it. Where health comes from an ancestor rather than the
enemy's own entity, the ancestor is named under the table — that is the file a
mod would edit, and editing it changes **every** enemy that inherits from it.

:::caution[A dash is not zero]
18 enemies never author health and inherit the `Character_Common`
default, which reads as **100**. Everything with a number overrides it
somewhere in its ancestry.
:::

## Where you meet them

Grouped by the biome spawn pool that streams the entity — an enemy whose
entity is not in a biome's pool is simply not there to instantiate, whatever
its tribe says. See [Enemies](/reverse-engineering/enemies/) for the two gates.

### Dark Hills

15 enemies.

| Enemy | Rank | Tribe | HP | Stagger | Tags |
|---|---|---|---|---|---|
| Undead Hog Captain | Elite | Undead Hogs | 150 | 100 | `DarkHills`, `Melee`, `Wave` |
| Undead Hog Fisherman | Standard | Undead Hogs | 150 | 50 | `Melee`, `Wave` |
| Undead Hog Reaper | Standard | Undead Hogs | 150 | 50 | `Melee`, `Wave` |
| Festering Ghoul | Elite | Marsh Ghouls | 100 | — | `Melee`, `Wave` |
| Devouring Ghoul | Standard | Marsh Ghouls | 60 | — | `DarkHills`, `Melee`, `Wave` |
| Enchanted Scarecrow | Elite | Scarecrows | — | — | — |
| Lumbering Treant | Elite | Treants | — | 125 | `Melee`, `Wave` |
| White Lady Masked | Elite | White Ladies | — | — | `Melee`, `Wave` |
| Clawed Treant | Standard | Treants | — | — | `Melee`, `Wave` |
| Day Scarecrow | Standard | Scarecrows | — | — | — |
| Night Scarecrow | Standard | Scarecrows | — | — | — |
| Root Treant | Standard | Treants | — | — | `Range`, `Wave` |
| Sling Ghoul | Standard | Marsh Ghouls | — | — | `Range`, `Wave` |
| White Lady Lantern | Standard | White Ladies | — | — | `Range`, `Wave` |
| White Lady Screaming | Standard | White Ladies | — | — | `Melee`, `Wave` |

Health inherited from `Undead_Hogs_Model`.

### Storm Island

12 enemies.

| Enemy | Rank | Tribe | HP | Stagger | Tags |
|---|---|---|---|---|---|
| Gnoll Chieftain | Elite | Gnolls | 125 | — | `Wave` |
| Gnoll Hunter | Standard | Gnolls | 125 | — | `Wave` |
| Gnoll Shielded | Standard | Gnolls | 125 | 50 | `Wave` |
| Ifrit Jinn | Standard | Jinns | 120 | — | `Wave` |
| Storm Jinn | Standard | Jinns | 120 | — | `Wave` |
| Roc Egg | Standard | Roc Birds | 100 | — | — |
| Phoenix Egg | Minion | Roc Birds | 100 | — | — |
| Coral Crab | Elite | Crabs | 70 | — | `Wave` |
| Mud Crab | Standard | Crabs | 70 | 75 | `Range`, `Wave` |
| Reef Crab | Standard | Crabs | 70 | 75 | `Melee`, `Wave` |
| Phoenix Roc | Elite | Roc Birds | — | — | `Wave` |
| Rocling | Standard | Roc Birds | — | — | `Wave` |

Health inherited from `Crabs_Model`, `Gnoll_Model`.

### Avalon

13 enemies.

| Enemy | Rank | Tribe | HP | Stagger | Tags |
|---|---|---|---|---|---|
| Gargoyle Blood | Elite | Gargoyles | 125 | 100 | `Wave` |
| Knight Mage | Elite | Knights | 125 | 125 | `Wave` |
| Knight Spear | Elite | Knights | 125 | 125 | `Wave` |
| Knight Sword | Elite | Knights | 125 | 125 | `Wave` |
| Gargoyle Bestial | Standard | Gargoyles | 125 | 75 | `Wave` |
| Gargoyle Fire | Standard | Gargoyles | 125 | 75 | `Wave` |
| Wolf Alpha | Elite | Wolves | 100 | — | `Wave` |
| Wolf Dire | Standard | Wolves | 100 | — | `Wave` |
| Wolf Timber | Standard | Wolves | 100 | — | `Wave` |
| Witch Stake (Elite) | Elite | Witches | — | — | `Wave` |
| Witch Crone (Standard) | Standard | Witches | — | — | `Wave` |
| Witch Young (Standard) | Standard | Witches | — | — | `Wave` |
| Knight Skeleton | Minion | Knights | — | — | — |

Health inherited from `Gargoyles_Model`, `Knights_Model`, `Wolves_Model`.

### Baba Yaga's realm

6 enemies.

| Enemy | Rank | Tribe | HP | Stagger | Tags |
|---|---|---|---|---|---|
| Baba Yaga Skull Fire | Minion | Baba Yaga | 150 | — | `Baba_Yaga_Skull` |
| Stalker Nightmare | Elite | Stalker Nightmares | 125 | 125 | `Wave` |
| Baba Yaga Skull Dark | Minion | Baba Yaga | 125 | — | `Baba_Yaga_Skull` |
| Baba Yaga Skull Poison | Minion | Baba Yaga | 125 | — | `Baba_Yaga_Skull` |
| Baba Yaga Tentacle Summon | Minion | Tentacle Nightmares | 100 | 75 | `Nightmare`, `Melee`, `Tentacle` |
| Nightmare Small Stalker | Standard | Stalker Nightmares | — | — | — |

Health inherited from `Baba_Yaga_Skull_Model`.

### Any biome

10 enemies.

| Enemy | Rank | Tribe | HP | Stagger | Tags |
|---|---|---|---|---|---|
| Cultist Summoner | Elite | Nightmare Cultists | 125 | — | `Nightmare`, `Wave` |
| Spider Nightmare Elite | Elite | Spider Nightmares | 125 | — | `Nightmare`, `Wave` |
| Tentacle Nightmare | Elite | Tentacle Nightmares | 125 | 125 | `Nightmare`, `Melee`, `Tentacle`, `Wave` |
| Thief Assassin | Elite | Thieves | 125 | — | `Melee`, `Wave` |
| Cultist Fanatic | Standard | Nightmare Cultists | 125 | — | `Nightmare`, `Melee`, `Wave` |
| Cultist Priest | Standard | Nightmare Cultists | 125 | — | `Nightmare`, `Range`, `Wave` |
| Thief Brigand | Standard | Thieves | 125 | — | `Melee`, `Wave` |
| Thief Marksman | Standard | Thieves | 125 | — | `Range`, `Wave` |
| Spider Nightmare Spitter | Minion | Spider Nightmares | 125 | — | `Nightmare`, `Range`, `Spider` |
| Spider Nightmare Biter | Minion | Spider Nightmares | 45 | — | `Nightmare`, `Melee`, `Spider` |

Health inherited from `Cultists_Model`, `Spider_Nightmare_Model`, `Tentacle_Nightmares_Model`, `Thieves_Model`.

### Summoned and unpooled

Not in any biome pool: adds that something else spawns, plus named enemies
placed by a specific encounter rather than by the camp generator.

| Enemy | Rank | Tribe | HP | Stagger | Tags |
|---|---|---|---|---|---|
| Mordred | Minion | Knights | 300 | 250 | — |
| Ogre Cyclop | Minion | Ogres | 300 | 300 | — |
| Stingy Jack | Elite | Stingy Jack | 275 | 200 | — |
| Ogre Wood | Minion | Ogres | 250 | 250 | — |
| Tentacle Summon | Elite | Tentacle Nightmares | 150 | 75 | `Nightmare`, `Melee`, `Tentacle` |
| Snake Nightmare | Elite | Snake Nightmares | 125 | 100 | `Nightmare`, `Wave` |
| Evil Jinn | Elite | Jinns | 120 | — | `Wave` |
| Cultist Summoner Summoned Eye | Minion | Faceless Nightmares | 100 | — | `Nightmare` |
| Faceless Eye | Minion | Faceless Nightmares | 100 | — | — |
| Cultist Summoner Summoned Tentacle | Minion | Tentacle Nightmares | 80 | 75 | `Nightmare`, `Tentacle` |
| Baba Yaga House | Minion | — | — | — | — |

Health inherited from `Faceless_Nightmare_Eye`, `Snake_Nightmare_Model`.

## Bosses

| Enemy | Tribe | HP | Stagger |
|---|---|---|---|
| Baba Yaga | Baba Yaga | 1000 | — |
| Faceless Nightmare | Faceless Nightmares | 350 | 200 |
| Dullahan Arthur | Dullahan | 300 | 200 |
| Hand Nightmare | Hands Nightmares | 300 | 200 |
| Roc Bird | Jinns | 300 | 300 |
| Tentacle Master | Tentacle Nightmares | 250 | 200 |
| Jinn | Jinns | 200 | 200 |
| Marsh Ghoul | Marsh Ghouls | 200 | 200 |
| White Lady | White Ladies | 200 | 200 |
| Wolf | Wolves | 200 | 200 |
| Crab | Crabs | 180 | 200 |
| Witch Crone (Boss) | Witches | 150 | 150 |
| Witch Stake (Boss) | Witches | 150 | 150 |
| Witch Young (Boss) | Witches | 150 | 150 |

## Tribes at a glance

A tribe groups enemies for camp generation, and it is usually also where the
shared stats live — every gnoll is 125 HP because `Gnoll_Model` says so.

| Tribe | Biome | Members | HP | Health authored by |
|---|---|---|---|---|
| (no tribe) | — | 1 | — | *own entity* |
| Baba Yaga | Baba Yaga's realm | 4 | 125–1000 | `Baba_Yaga_Skull_Model` |
| Crabs | Storm Island | 4 | 70–180 | `Crabs_Model` |
| Dullahan | — | 1 | 300 | *own entity* |
| Faceless Nightmares | — | 3 | 100–350 | `Faceless_Nightmare_Eye` |
| Gargoyles | Avalon | 3 | 125 | `Gargoyles_Model` |
| Gnolls | Storm Island | 3 | 125 | `Gnoll_Model` |
| Hands Nightmares | — | 1 | 300 | *own entity* |
| Jinns | Storm Island | 5 | 120–300 | *own entity* |
| Knights | Avalon | 5 | 125–300 | `Knights_Model` |
| Marsh Ghouls | Dark Hills | 4 | 60–200 | *own entity* |
| Nightmare Cultists | Any biome | 3 | 125 | `Cultists_Model` |
| Ogres | — | 2 | 250–300 | *own entity* |
| Roc Birds | Storm Island | 4 | 100 | *own entity* |
| Scarecrows | Dark Hills | 3 | — | *own entity* |
| Snake Nightmares | — | 1 | 125 | `Snake_Nightmare_Model` |
| Spider Nightmares | Any biome | 3 | 45–125 | `Spider_Nightmare_Model` |
| Stalker Nightmares | Baba Yaga's realm | 2 | 125 | *own entity* |
| Stingy Jack | — | 1 | 275 | *own entity* |
| Tentacle Nightmares | Baba Yaga's realm, Any biome | 5 | 80–250 | `Tentacle_Nightmares_Model` |
| Thieves | Any biome | 3 | 125 | `Thieves_Model` |
| Treants | Dark Hills | 3 | — | *own entity* |
| Undead Hogs | Dark Hills | 3 | 150 | `Undead_Hogs_Model` |
| White Ladies | Dark Hills | 4 | 200 | *own entity* |
| Witches | Avalon | 6 | 150 | *own entity* |
| Wolves | Avalon | 4 | 100–200 | `Wolves_Model` |

## What these numbers do not tell you

Three things players reasonably expect here are not in the shipped data, and
the page would rather say so than invent them.

**Corruption / tainted enemies.** The corruption modifier (`AllEnemiesTainted`,
which is the one wearing the corruption icon) scales enemies through
`NGP_Tainted_Enemies_Modifier`, and every `NGP_*` value ships as **0.0** — they
are New Game Plus knobs the run sets at load time, not constants in the data.
There is no corrupted number to mine, so none is shown.

**Chapter and party-size scaling.** `Chapter_Scaling_Enemies_Max_Health_Factor`
and its damage twin both ship at **1.0**, and the corpus holds no party-size
factor at all. An earlier version of this page claimed the run multiplies
health by chapter and party size; that was wrong, and the data does not
support any specific multiplier.

**Per-chapter enemy variants.** There are none. No enemy definition carries a
chapter, act or tier marker, and the nightmare family a run meets everywhere —
cultists, spiders, tentacles, thieves — is one flat set of definitions at 125
HP reused in every biome. A cultist in the last chapter is the same definition
as a cultist in the first; what changes around it is the biome pool it is
rolled from, not the enemy.

## Changing these numbers

Health is not on the enemy definition — it is an entity-value override on the
`oCEntitySettings` the definition points at, so a mod that edits the `enemydef`
changes tags and spawn weights and nothing else. See
[Enemies](/reverse-engineering/enemies/) for the definition layout,
[Anatomy of an entity](/reverse-engineering/entity-anatomy/) for why the number
lives where it does, and [Custom enemies](/guides/custom-enemies/) for the
authoring path.
