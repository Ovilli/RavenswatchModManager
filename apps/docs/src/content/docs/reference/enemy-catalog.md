---
title: Enemy encyclopedia
description: Every enemy the game ships — base health, stagger, size, tribe, biome and tags, mined from the cooked data.
---

:::note[Generated file]
Built by `tools/mine_enemy_catalog.py` from the cooked corpus and checked in as
`data/enemy_catalog.json`. Do not edit this page by hand — re-run the tool.
:::

**81 enemy definitions**, across 26 tribes.

## How to read this

Every number here is a **base value**. The run multiplies health by chapter and
party size before you ever swing at something, so a Standard Mud Crab is not 70
HP in chapter 3 — it is 70 scaled. Treat these as the relative numbers that say
a gnoll is roughly twice a crab, not as what the health bar holds.

| Column | What it is |
|---|---|
| **HP** | `Raw Max Health` — the base the HitPoint component starts from. |
| **Stagger** | `Stagger Max Points` — how much stagger it absorbs before breaking. |
| **Radius** | `Collision Radius` — physical size, and how easily it is hit. |
| **Scale** | `Character Mesh Scale` — visual scale of the model. |
| **Resist** | `Default Resistance` — baseline damage resistance. |
| **Tags** | Flags on the enemy definition. Camp and wave selectors filter on these. |

A dash means the enemy does not author that attribute and inherits it. Where a
value comes from an ancestor rather than the enemy's own entity, the ancestor is
named beneath the table — that is the file a mod would actually edit, and
editing it changes **every** enemy that inherits from it.

:::caution[A dash in the HP column is the shared default]
18 of these never author health and fall through to the `Character_Common`
default, which reads as **100**. The walk deliberately stops before
`Character_Common`: it *declares* these attributes rather than overriding them,
in a record whose payload sits under a different mark, so reading it as an
override produces junk. Everything shown in the table **is** mined from a real
override; everything dashed is inherited.
:::

## Bosses

| Enemy | Rank | Tribe | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|---|
| Crab | Boss | Crabs | 180 | 200 | 2 | 1.5 | 1 | — | `Boss`, `BossCrab` |
| Dullahan Arthur | Boss | Dullahan | 300 | 200 | 1.8 | — | 0 | — | `Boss`, `Dullahan_Arthur` |
| Faceless Nightmare | Boss | Faceless Nightmares | 350 | 200 | 3 | 1 | — | — | `ChapterBoss`, `FacelessNightmare` |
| Hand Nightmare | Boss | Hands Nightmares | 300 | 200 | 2.15 | 1.8 | 0 | — | `ChapterBoss`, `HandNightmare` |
| Jinn | Boss | Jinns | 200 | 200 | 1.25 | 1.3 | 0 | — | `Boss`, `Boss_Jinn` |
| Marsh Ghoul | Boss | Marsh Ghouls | 200 | 200 | 1.4 | 2.5 | 0 | — | `Boss_Marsh_Ghoul`, `Boss` |
| Roc Bird | Boss | Jinns | 300 | 300 | 2.75 | 1 | 0 | — | `Boss`, `Boss_Roc` |
| Tentacle Master | Boss | Tentacle Nightmares | 250 | 200 | 3 | 1.3 | 0 | — | `ChapterBoss`, `TentacleMaster` |
| White Lady | Boss | White Ladies | 200 | 200 | 1.2 | 1.6 | 0 | — | `Boss_White_Lady`, `Boss` |
| Witch Crone | Boss | Witches | 150 | 150 | 1 | 1.25 | 0 | — | `Boss`, `Boss_Witch_Crone` |
| Witch Stake | Boss | Witches | 150 | 150 | 1.1 | 1.45 | 0 | — | `Boss`, `Boss_Witch_Stake` |
| Witch Young | Boss | Witches | 150 | 150 | 0.9 | 1.25 | 0 | — | `Boss`, `Boss_Witch_Young` |
| Wolf | Boss | Wolves | 200 | 200 | 2.5 | 2.2 | 0 | — | `Boss`, `BossWolf` |

## By tribe

### (no tribe)

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Baba Yaga House | Minion | — | — | — | — | — | — | — |

### Baba Yaga

*Biome: Baba Yaga Map*

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Baba Yaga Boss | Minion | 1000 | — | 2 | 1.3 | — | — | `Baba_Yaga` |
| Baba Yaga Skull Dark | Minion | 125 | — | 0.7 | 0.85 | — | Baba Yaga Map | `Baba_Yaga_Skull` |
| Baba Yaga Skull Fire | Minion | 150 | — | 1 | 1.2 | — | Baba Yaga Map | `Baba_Yaga_Skull` |
| Baba Yaga Skull Poison | Minion | 125 | — | 0.8 | 0.95 | — | Baba Yaga Map | `Baba_Yaga_Skull` |

Health inherited from `Baba_Yaga_Skull_Model`.

### Crabs

*Biome: Storm Island*

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Crab | Boss | 180 | 200 | 2 | 1.5 | 1 | — | `Boss`, `BossCrab` |
| Coral Crab | Elite | 70 | — | — | — | 1 | Storm Island | `Elite`, `CoralCrab`, `Wave` |
| Mud Crab | Standard | 70 | 75 | 1.3 | 0.85 | 1 | Storm Island | `Standard`, `MudCrab`, `Range`, `Wave` |
| Reef Crab | Standard | 70 | 75 | 1.4 | 0.9 | 1 | Storm Island | `Standard`, `ReefCrab`, `Melee`, `Wave` |

Health inherited from `Crabs_Model`.

### Dullahan

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Dullahan Arthur | Boss | 300 | 200 | 1.8 | — | 0 | — | `Boss`, `Dullahan_Arthur` |

### Faceless Nightmares

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Faceless Nightmare | Boss | 350 | 200 | 3 | 1 | — | — | `ChapterBoss`, `FacelessNightmare` |
| Cultist Summoner Summoned Eye | Minion | 100 | — | 0.5 | 1 | — | — | `Eye`, `Nightmare` |
| Faceless Eye | Minion | 100 | — | 0.5 | 1 | — | — | `Faceless_Eye` |

Health inherited from `Faceless_Nightmare_Eye`.

### Gargoyles

*Biome: Avalon*

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Gargoyle Blood | Elite | 125 | 100 | 1.2 | 1.1 | 0 | Avalon | `Elite`, `GargoyleBlood`, `Wave` |
| Gargoyle Bestial | Standard | 125 | 75 | 0.85 | 0.8 | — | Avalon | `Standard`, `GargoyleBestial`, `Wave` |
| Gargoyle Fire | Standard | 125 | 75 | 0.8 | 0.75 | — | Avalon | `Standard`, `GargoyleFire`, `Wave` |

Health inherited from `Gargoyles_Model`.

### Gnolls

*Biome: Storm Island*

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Gnoll Chieftain | Elite | 125 | — | 1.3 | 1 | 0 | Storm Island | `Elite`, `ChieftainGnoll`, `Wave` |
| Gnoll Hunter | Standard | 125 | — | 0.9 | 1 | — | Storm Island | `Standard`, `HunterGnoll`, `Wave` |
| Gnoll Shielded | Standard | 125 | 50 | 1 | 1 | — | Storm Island | `Standard`, `ShieldedGnoll`, `Wave` |

Health inherited from `Gnoll_Model`.

### Hands Nightmares

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Hand Nightmare | Boss | 300 | 200 | 2.15 | 1.8 | 0 | — | `ChapterBoss`, `HandNightmare` |

### Jinns

*Biome: Storm Island*

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Jinn | Boss | 200 | 200 | 1.25 | 1.3 | 0 | — | `Boss`, `Boss_Jinn` |
| Roc Bird | Boss | 300 | 300 | 2.75 | 1 | 0 | — | `Boss`, `Boss_Roc` |
| Evil Jinn | Elite | 120 | — | 1.25 | 1.3 | 0 | — | `Elite`, `EvilJinn`, `Wave` |
| Ifrit Jinn | Standard | 120 | — | 1 | 1.2 | — | Storm Island | `Standard`, `IfritJinn`, `Wave` |
| Storm Jinn | Standard | 120 | — | 1 | 1.15 | — | Storm Island | `Standard`, `StormJinn`, `Wave` |

### Knights

*Biome: Avalon*

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Knight Mage | Elite | 125 | 125 | 1.3 | 0.85 | 0 | Avalon | `Elite`, `KnightMage`, `Wave` |
| Knight Spear | Elite | 125 | 125 | 1.3 | 0.8 | 0 | Avalon | `Elite`, `KnightSpear`, `Wave` |
| Knight Sword | Elite | 125 | 125 | 1.5 | 0.85 | 0 | Avalon | `Elite`, `KnightSword`, `Wave` |
| Knight Skeleton | Minion | — | — | 0.7 | 1 | — | Avalon | `KnightSkeleton` |
| Mordred | Minion | 300 | 250 | 2 | 1.1 | 0 | — | `Mordred` |

Health inherited from `Knights_Model`.

### Marsh Ghouls

*Biome: Dark Hills*

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Marsh Ghoul | Boss | 200 | 200 | 1.4 | 2.5 | 0 | — | `Boss_Marsh_Ghoul`, `Boss` |
| Festering Ghoul | Elite | 100 | — | 1 | 1.8 | 0 | Dark Hills | `Melee`, `Elite`, `FesteringGhoul`, `Wave` |
| Devouring Ghoul | Standard | 60 | — | 0.8 | 1.3 | — | Dark Hills | `DarkHills`, `Melee`, `Standard`, `DevouringGhoul`, `Wave` |
| Sling Ghoul | Standard | — | — | 0.8 | — | — | Dark Hills | `Range`, `Standard`, `SlingGhoul`, `Wave` |

### Nightmare Cultists

*Biome: Common*

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Cultist Summoner | Elite | 125 | — | 1 | 1.15 | 0 | Common | `Nightmare`, `Cultist_Summoner`, `KeyKeeper`, `Wave` |
| Cultist Fanatic | Standard | 125 | — | 0.8 | — | — | Common | `Nightmare`, `Melee`, `Standard`, `CultistFanatic`, `Wave` |
| Cultist Priest | Standard | 125 | — | 0.8 | — | — | Common | `Nightmare`, `Range`, `Standard`, `CultistPriest`, `Wave` |

Health inherited from `Cultists_Model`.

### Ogres

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Ogre Cyclop | Minion | 300 | 300 | 2 | 1 | 0 | — | `Cyclop` |
| Ogre Wood | Minion | 250 | 250 | 2 | 1 | 0 | — | `Ogre` |

### Roc Birds

*Biome: Storm Island*

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Phoenix Roc | Elite | — | — | 1.5 | 1.3 | 0 | Storm Island | `PhoenixRoc`, `Elite`, `Wave` |
| Roc Egg | Standard | 100 | — | 1 | — | — | Storm Island | `RocEgg`, `Standard` |
| Rocling | Standard | — | — | — | — | — | Storm Island | `Rocling`, `Standard`, `Wave` |
| Phoenix Egg | Minion | 100 | — | 1 | — | — | Storm Island | `PhoenixEgg` |

### Scarecrows

*Biome: Dark Hills*

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Enchanted Scarecrow | Elite | — | — | 1 | 1.3 | — | Dark Hills | `EnchantedScarecrow`, `Elite` |
| Day Scarecrow | Standard | — | — | 1 | — | — | Dark Hills | `DayScarecrow`, `Standard` |
| Night Scarecrow | Standard | — | — | 1 | — | — | Dark Hills | `NightScarecrow`, `Standard` |

### Snake Nightmares

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Snake Nightmare | Elite | 125 | 100 | 1.35 | — | 0 | — | `Nightmare`, `Elite`, `Snake`, `Wave` |

Health inherited from `Snake_Nightmare_Model`.

### Spider Nightmares

*Biome: Common*

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Spider Nightmare Elite | Elite | 125 | — | — | — | — | Common | `Nightmare`, `Elite`, `EliteSpider`, `Wave` |
| Spider Nightmare Biter | Minion | 45 | — | — | 0.6 | — | Common | `Nightmare`, `Melee`, `Spider`, `BiterSpider` |
| Spider Nightmare Spitter | Minion | 125 | — | — | — | — | Common | `Nightmare`, `Range`, `Spider`, `SpitterSpider` |

Health inherited from `Spider_Nightmare_Model`.

### Stalker Nightmares

*Biome: Baba Yaga Map*

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Stalker Nightmare | Elite | 125 | 125 | 1.5 | 1.1 | 0 | Baba Yaga Map | `Stalker`, `Elite`, `Wave` |
| Nightmare Small Stalker | Standard | — | — | 1.15 | 0.75 | — | Baba Yaga Map | `SmallStalker`, `Standard` |

### Stingy Jack

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Stingy Jack | Elite | 275 | 200 | 0.8 | 1 | 0 | — | `StingyJack`, `Elite` |

### Tentacle Nightmares

*Biome: Baba Yaga Map, Common*

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Tentacle Master | Boss | 250 | 200 | 3 | 1.3 | 0 | — | `ChapterBoss`, `TentacleMaster` |
| Tentacle Nightmare | Elite | 125 | 125 | 2 | 0.7 | 0 | Common | `Nightmare`, `Melee`, `Elite`, `Tentacle`, `Wave`, `Poulpe` |
| Tentacle Summon | Elite | 150 | 75 | 1 | 1 | — | — | `Nightmare`, `Melee`, `Elite`, `Tentacle` |
| Baba Yaga Tentacle Summon | Minion | 100 | 75 | 1 | 1 | 0 | Baba Yaga Map | `Nightmare`, `Melee`, `Tentacle` |
| Cultist Summoner Summoned Tentacle | Minion | 80 | 75 | 1 | 0.8 | 0 | — | `Nightmare`, `Tentacle` |

Health inherited from `Tentacle_Nightmares_Model`.

### Thieves

*Biome: Common*

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Thief Assassin | Elite | 125 | — | 1 | 1.1 | 0 | Common | `Elite`, `ThiefAssassin`, `Melee`, `Wave` |
| Thief Brigand | Standard | 125 | — | 0.8 | 1.15 | — | Common | `Standard`, `ThiefBrigand`, `Melee`, `Wave` |
| Thief Marksman | Standard | 125 | — | 0.8 | 1 | — | Common | `Standard`, `ThiefMarksman`, `Range`, `Wave` |

Health inherited from `Thieves_Model`.

### Treants

*Biome: Dark Hills*

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Lumbering Treant | Elite | — | 125 | 1.8 | 1.7 | 0 | Dark Hills | `Melee`, `Elite`, `LumberingTreant`, `Wave` |
| Clawed Treant | Standard | — | — | 1 | — | — | Dark Hills | `Melee`, `Standard`, `ClawedTreant`, `Wave` |
| Root Treant | Standard | — | — | 1 | — | — | Dark Hills | `Range`, `Standard`, `RootTreant`, `Wave` |

### Undead Hogs

*Biome: Dark Hills*

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Undead Hog Captain | Elite | 150 | 100 | 1.3 | 1 | 0 | Dark Hills | `DarkHills`, `Melee`, `Elite`, `HogCaptain`, `Wave` |
| Undead Hog Fisherman | Standard | 150 | 50 | 1 | — | — | Dark Hills | `Melee`, `Standard`, `HogFisherman`, `Wave` |
| Undead Hog Reaper | Standard | 150 | 50 | — | — | — | Dark Hills | `Melee`, `Standard`, `HogReaper`, `Wave` |

Health inherited from `Undead_Hogs_Model`.

### White Ladies

*Biome: Dark Hills*

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| White Lady | Boss | 200 | 200 | 1.2 | 1.6 | 0 | — | `Boss_White_Lady`, `Boss` |
| White Lady Masked | Elite | — | — | 1 | 1.3 | 0 | Dark Hills | `Melee`, `Elite`, `WhiteLadyMasked`, `Wave` |
| White Lady Lantern | Standard | — | — | 0.8 | 1.05 | — | Dark Hills | `Range`, `Standard`, `WhiteLadyLantern`, `Wave` |
| White Lady Screaming | Standard | — | — | 0.8 | — | — | Dark Hills | `Melee`, `Standard`, `WhiteLadyScreaming`, `Wave` |

### Witches

*Biome: Avalon*

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Witch Crone | Boss | 150 | 150 | 1 | 1.25 | 0 | — | `Boss`, `Boss_Witch_Crone` |
| Witch Stake | Boss | 150 | 150 | 1.1 | 1.45 | 0 | — | `Boss`, `Boss_Witch_Stake` |
| Witch Young | Boss | 150 | 150 | 0.9 | 1.25 | 0 | — | `Boss`, `Boss_Witch_Young` |
| Witch Stake | Elite | — | — | 1 | 1.1 | 0 | Avalon | `Standard`, `WitchStake`, `Wave` |
| Witch Crone | Standard | — | — | 0.75 | 1.05 | — | Avalon | `Standard`, `WitchCrone`, `Wave` |
| Witch Young | Standard | — | — | 0.8 | 1 | — | Avalon | `Standard`, `WitchYoung`, `Wave` |

### Wolves

*Biome: Avalon*

| Enemy | Rank | HP | Stagger | Radius | Scale | Resist | Biome | Tags |
|---|---|---|---|---|---|---|---|---|
| Wolf | Boss | 200 | 200 | 2.5 | 2.2 | 0 | — | `Boss`, `BossWolf` |
| Wolf Alpha | Elite | 100 | — | 1.9 | 1.5 | 0 | Avalon | `Elite`, `WolvesAlpha`, `Wave` |
| Wolf Dire | Standard | 100 | — | 1.45 | 1.1 | — | Avalon | `Standard`, `WolfDire`, `Wave` |
| Wolf Timber | Standard | 100 | — | 1.3 | 1 | — | Avalon | `Standard`, `WolfTimber`, `Wave` |

Health inherited from `Wolves_Model`.

## Changing these numbers

Health is not on the enemy definition — it is an entity-value override on the
`oCEntitySettings` the definition points at, so a mod that edits the `enemydef`
changes tags and spawn weights and nothing else. See
[Enemies](/reverse-engineering/enemies/) for the definition layout,
[Anatomy of an entity](/reverse-engineering/entity-anatomy/) for why the number
lives where it does, and [Custom enemies](/guides/custom-enemies/) for the
authoring path.
