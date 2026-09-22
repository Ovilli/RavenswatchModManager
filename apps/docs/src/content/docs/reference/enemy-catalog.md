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
| **Share** | How often the camp roll picks it: its spawn weight over the biome's total. |
| **Tags** | Definition flags that more than one enemy carries. |

`data/enemy_catalog.json` carries three more attributes the tables leave out:
collision radius and mesh scale, which describe how big the model is rather
than how it fights, and resistance, which is 0 for every enemy that authors it
except the four crabs, which are 1.

Biome tables list the enemies you meet most first; the others are sorted
heaviest first. `n/a` means the enemy authors the value but its fight does
not use it — the note under that table says what happens instead. A dash
means the enemy does not author that
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

15 enemies, 2 bosses.

| Enemy | Rank | Tribe | HP | Stagger | Share | Tags |
|---|---|---|---|---|---|---|
| Lumbering Treant | Elite | Treants | — | 125 | 20% | `Melee`, `Wave` |
| Undead Hog Captain | Elite | Undead Hogs | 150 | 100 | 13% | `DarkHills`, `Melee`, `Wave` |
| White Lady Masked | Elite | White Ladies | — | — | 10% | `Melee`, `Wave` |
| Festering Ghoul | Elite | Marsh Ghouls | 100 | — | 8% | `Melee`, `Wave` |
| Enchanted Scarecrow | Elite | Scarecrows | — | — | 8% | — |
| Clawed Treant | Standard | Treants | — | — | 7% | `Melee`, `Wave` |
| Root Treant | Standard | Treants | — | — | 7% | `Range`, `Wave` |
| Day Scarecrow | Standard | Scarecrows | — | — | 5% | — |
| Night Scarecrow | Standard | Scarecrows | — | — | 5% | — |
| White Lady Lantern | Standard | White Ladies | — | — | 4% | `Range`, `Wave` |
| White Lady Screaming | Standard | White Ladies | — | — | 4% | `Melee`, `Wave` |
| Undead Hog Fisherman | Standard | Undead Hogs | 150 | 50 | 3% | `Melee`, `Wave` |
| Undead Hog Reaper | Standard | Undead Hogs | 150 | 50 | 3% | `Melee`, `Wave` |
| Devouring Ghoul | Standard | Marsh Ghouls | 60 | — | 2% | `DarkHills`, `Melee`, `Wave` |
| Sling Ghoul | Standard | Marsh Ghouls | — | — | 1% | `Range`, `Wave` |

Health inherited from `Undead_Hogs_Model`.

**Bosses fought here**

| Boss | HP | Stagger | Arena |
|---|---|---|---|
| Marsh Ghoul | 200 | 200 | `Ghoul_Underground_Boss_Den` |
| White Lady | 200 | 200 | `Boss_Shrine_White_Lady` |

### Storm Island

12 enemies, 3 bosses.

| Enemy | Rank | Tribe | HP | Stagger | Share | Tags |
|---|---|---|---|---|---|---|
| Coral Crab | Elite | Crabs | 70 | — | 21% | `Wave` |
| Phoenix Egg | Minion | Roc Birds | 100 | — | 14% | — |
| Phoenix Roc | Elite | Roc Birds | — | — | 14% | `Wave` |
| Gnoll Chieftain | Elite | Gnolls | 125 | — | 9% | `Wave` |
| Reef Crab | Standard | Crabs | 70 | 75 | 9% | `Melee`, `Wave` |
| Ifrit Jinn | Standard | Jinns | 120 | — | 7% | `Wave` |
| Storm Jinn | Standard | Jinns | 120 | — | 7% | `Wave` |
| Mud Crab | Standard | Crabs | 70 | 75 | 7% | `Range`, `Wave` |
| Gnoll Shielded | Standard | Gnolls | 125 | 50 | 4% | `Wave` |
| Gnoll Hunter | Standard | Gnolls | 125 | — | 4% | `Wave` |
| Roc Egg | Standard | Roc Birds | 100 | — | 2% | — |
| Rocling | Standard | Roc Birds | — | — | 2% | `Wave` |

Health inherited from `Crabs_Model`, `Gnoll_Model`.

**Bosses fought here**

| Boss | HP | Stagger | Arena |
|---|---|---|---|
| Roc Bird | 300 | 300 | `Roc_Quest_NPC_Sinbad_Model` |
| Jinn | 200 | 200 | `Boss_Shrine_Jinn` |
| Crab | 180 | 200 | `Underground_Crab_Mini_Boss_Den` |

### Avalon

13 enemies, 4 bosses.

| Enemy | Rank | Tribe | HP | Stagger | Share | Tags |
|---|---|---|---|---|---|---|
| Knight Mage | Elite | Knights | 125 | 125 | 14% | `Wave` |
| Knight Spear | Elite | Knights | 125 | 125 | 14% | `Wave` |
| Knight Sword | Elite | Knights | 125 | 125 | 14% | `Wave` |
| Witch Stake (Elite) | Elite | Witches | — | — | 14% | `Wave` |
| Gargoyle Blood | Elite | Gargoyles | 125 | 100 | 11% | `Wave` |
| Wolf Alpha | Elite | Wolves | 100 | — | 11% | `Wave` |
| Witch Young (Standard) | Standard | Witches | — | — | 5% | `Wave` |
| Gargoyle Bestial | Standard | Gargoyles | 125 | 75 | 4% | `Wave` |
| Witch Crone (Standard) | Standard | Witches | — | — | 4% | `Wave` |
| Gargoyle Fire | Standard | Gargoyles | 125 | 75 | 3% | `Wave` |
| Wolf Dire | Standard | Wolves | 100 | — | 3% | `Wave` |
| Wolf Timber | Standard | Wolves | 100 | — | 3% | `Wave` |
| Knight Skeleton | Minion | Knights | — | — | 2% | — |

Health inherited from `Gargoyles_Model`, `Knights_Model`, `Wolves_Model`.

**Bosses fought here**

| Boss | HP | Stagger | Arena |
|---|---|---|---|
| Wolf | 200 | 200 | `Underground_Wolf_Boss_Den` |
| Witch Crone (Boss) | 150 | 150 | `Boss_Shrine_Witch` |
| Witch Stake (Boss) | 150 | 150 | `Boss_Shrine_Witch` |
| Witch Young (Boss) | 150 | 150 | `Boss_Shrine_Witch` |

### Baba Yaga's realm

6 enemies, 1 boss.

| Enemy | Rank | Tribe | HP | Stagger | Share | Tags |
|---|---|---|---|---|---|---|
| Baba Yaga Skull Fire | Minion | Baba Yaga | 150 | — | 31% | `Baba_Yaga_Skull` |
| Baba Yaga Skull Dark | Minion | Baba Yaga | 125 | — | 31% | `Baba_Yaga_Skull` |
| Baba Yaga Skull Poison | Minion | Baba Yaga | 125 | — | 31% | `Baba_Yaga_Skull` |
| Stalker Nightmare | Elite | Stalker Nightmares | 125 | 125 | 5% | `Wave` |
| Nightmare Small Stalker | Standard | Stalker Nightmares | — | — | <1% | — |
| Baba Yaga Tentacle Summon | Minion | Tentacle Nightmares | 100 | 75 | <1% | `Nightmare`, `Melee`, `Tentacle` |

Health inherited from `Baba_Yaga_Skull_Model`.

**Bosses fought here**

| Boss | HP | Stagger | Arena |
|---|---|---|---|
| Baba Yaga | 1000 | — | `Baba_Yaga_House_Graphic_Model` |

### Any biome

10 enemies.

| Enemy | Rank | Tribe | HP | Stagger | Share | Tags |
|---|---|---|---|---|---|---|
| Tentacle Nightmare | Elite | Tentacle Nightmares | 125 | 125 | 25% | `Nightmare`, `Melee`, `Tentacle`, `Wave` |
| Spider Nightmare Elite | Elite | Spider Nightmares | 125 | — | 20% | `Nightmare`, `Wave` |
| Cultist Summoner | Elite | Nightmare Cultists | 125 | — | 12% | `Nightmare`, `Wave` |
| Thief Assassin | Elite | Thieves | 125 | — | 12% | `Melee`, `Wave` |
| Cultist Fanatic | Standard | Nightmare Cultists | 125 | — | 8% | `Nightmare`, `Melee`, `Wave` |
| Thief Brigand | Standard | Thieves | 125 | — | 8% | `Melee`, `Wave` |
| Cultist Priest | Standard | Nightmare Cultists | 125 | — | 6% | `Nightmare`, `Range`, `Wave` |
| Thief Marksman | Standard | Thieves | 125 | — | 5% | `Range`, `Wave` |
| Spider Nightmare Spitter | Minion | Spider Nightmares | 125 | — | 2% | `Nightmare`, `Range`, `Spider` |
| Spider Nightmare Biter | Minion | Spider Nightmares | 45 | — | 2% | `Nightmare`, `Melee`, `Spider` |

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

## Chapter and quest bosses

Bosses the data does not tie to a biome: the chapter bosses, and Dullahan,
whose quest is not filed under one. Every other boss — including quest bosses
like the Roc, whose quest lives on Storm Island — is listed under the biome
it is fought in, above.

| Boss | HP | Stagger | Arena |
|---|---|---|---|
| Faceless Nightmare | 350 | 200 | — |
| Dullahan Arthur | 300 | 200 | — |
| Hand Nightmare | 300 | 200 | — |
| Tentacle Master | 250 | n/a | — |

**Tentacle Master** is not staggered by stagger damage: he is staggered once all of his tentacles are destroyed. His entity still authors 200 stagger points, which the fight does not use.

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

## How enemies get tougher

Every number above is a base value. During a run the game scales it from one
setup in the data, `Common_Settings/Group_Scaling`: a two-level switch that picks
a multiplier by the **current chapter**, then by the **game difficulty**.

**Health multiplier** — chapter down, difficulty across, lowest to highest:

| Chapter | Difficulty 1 | Difficulty 2 | Difficulty 3 | Difficulty 4 |
|---|---|---|---|---|
| 1 | ×1 | ×1 | ×1 | ×1 |
| 2 | ×2 | ×2.2 | ×2.4 | ×2.5 |
| 3 | ×4 | ×4.5 | ×5 | ×5.2 |
| 4 | ×4.2 | ×4.7 | ×5.2 | ×5.4 |

**Damage multiplier** — chapter down, difficulty across, lowest to highest:

| Chapter | Difficulty 1 | Difficulty 2 | Difficulty 3 | Difficulty 4 |
|---|---|---|---|---|
| 1 | ×0.8 | ×0.9 | ×1 | ×1 |
| 2 | ×1.7 | ×1.9 | ×2 | ×2.1 |
| 3 | ×2.7 | ×3 | ×3.2 | ×3.4 |
| 4 | ×2.8 | ×3.1 | ×3.3 | ×3.5 |

A standard run plays three chapters; the data defines a fourth row as well.

**Stagger** scales by chapter only, and carries a per-player value chosen by
chapter. The value is named per player; the exact formula that applies it to
the party is in the game's code.

| Chapter | Stagger multiplier | Per player (common) | Per player (elite) |
|---|---|---|---|
| 1 | ×1 | +0.3 | +0.6 |
| 2 | ×1.2 | +0.4 | +0.7 |
| 3 | ×1.5 | +0.5 | +0.8 |
| 4 | ×1.75 | — | +0.9 |

`Group_Scaling` has no per-player **health** term: health scales by chapter and
difficulty only. Every per-player value in it is a stagger value.

### Corrupted (tainted) enemies

Defined on `Enemy_Model`, which every enemy inherits, so it applies to any
enemy that can be tainted: **+50%** health, **+75%** damage, **+25%** stagger, **10%** larger.

### Bosses scale on their own curve

Enemies are split into scaling groups, each with its own level curve up to
level 20. The groups share their other rates and differ in these
coefficients, highest for bosses:

| Group | Coefficient 1 | Coefficient 2 |
|---|---|---|
| Boss | 1.1 | 1.5 |
| Elite | 0.6 | 0.8 |
| Common | 0.3 | 0.5 |

What each coefficient controls is not labelled in the data. Which group an
enemy scales in is not in the data either — no file references any group —
so the game's code assigns it, most likely by rank.

### Nightmare tumors

Each tumor publishes a boss-health reduction ratio of **0.2**
(`Tumor_Reduce_Boss_Health_Ratio`), set by the tumor's own entity. The name
says destroying tumors weakens the boss; the rule that applies it is in the
game's code.

### Per-chapter enemy variants

There are none. No enemy definition carries a chapter, act or tier marker, and
the nightmare family a run meets everywhere — cultists, spiders, tentacles,
thieves — is one flat set of definitions reused in every biome. A late cultist
is the same definition as an early one; the chapter multiplier above is what
makes it hit harder.

## Changing these numbers

Health is not on the enemy definition — it is an entity-value override on the
`oCEntitySettings` the definition points at, so a mod that edits the `enemydef`
changes tags and spawn weights and nothing else. See
[Enemies](/reverse-engineering/enemies/) for the definition layout,
[Anatomy of an entity](/reverse-engineering/entity-anatomy/) for why the number
lives where it does, and [Custom enemies](/guides/custom-enemies/) for the
authoring path.
