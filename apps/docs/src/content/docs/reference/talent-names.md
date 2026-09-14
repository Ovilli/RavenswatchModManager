---
title: Talent name lookup
description: Every hero's talents, with the internal names you need to mod them.
---

The game shows a talent by its English name, like **Short Wick**. Inside the
game files the same talent has other names, like `Secondary Quick Bombs`. This
page connects the two, so you can go from the card you see in game to the name
a mod needs.

This is the companion page for the
[Talent modding tutorial](/guides/talent-tutorial/). Every hero section gives
you three things to copy:

| Column | What it is for |
|---|---|
| **Hero spelling** | Two spellings of the hero's name. `kind = "talent"` needs the first one and `kind = "skill"` needs the second. They differ only for Sun Wukong. |
| **Search word** | Goes into the helper script to find the talent's numbers. It usually also works as the talent name in the testing file that gives you the talent at the start of a run. |
| **Rename with** | Goes into `source = "..."` when you change the talent's name or description. |

A dash (—) under **Search word** means the helper cannot find that talent's
numbers by name.

:::note
The table was generated from the game's own English text on 2026-09-14. A game
update can add, remove or rename talents. If a name here stops working, the
helper script in the tutorial always reads the files you have now.

The two basic ultimates each hero starts with are not listed. Their names are
stored in more than one place and renaming them has not been tested. The
ultimate **upgrades** are listed.
:::

Jump to a hero:

[Aladdin](#aladdin) · [Beowulf](#beowulf) · [Carmilla](#carmilla) · [Geppetto](#geppetto) · [Juliet](#juliet) · [Melusine](#melusine) · [Merlin](#merlin) · [The Pied Piper](#the-pied-piper) · [Romeo](#romeo) · [Scarlet](#scarlet) · [The Snow Queen](#the-snow-queen) · [Sun Wukong](#sun-wukong)

## Aladdin

**Hero spelling:** `hero = "Aladdin"` for `kind = "talent"`, and `hero = "Aladdin"` for `kind = "skill"`.

| Talent in game | Ability | Search word | Rename with |
|---|---|---|---|
| Dive | Attack | `Attack Dive` | `Skill_Attack_Dive` |
| Dream Scimitars | Attack | `Attack Spawns DS` | `Skill_Attack_Spawns_DS` |
| Shard Blades | Attack | `Attack Wide` | `Skill_Attack_Wide` |
| Slide Attack | Attack | `Attack No Weapon` | `Skill_Attack_No_Weapon` |
| Spinning Strikes | Attack | `Attack Flurry` | `Skill_Attack_Flurry` |
| Cyclonic Appearance | Power | `Power Start AOE` | `Skill_Power_Start_AOE` |
| Enchanted Jinn | Power | `Power Energy` | `Skill_Power_Energy` |
| Jinn's Fury | Power | `Power Multi Hit` | `Skill_Power_Multi_Hit` |
| Jinn's Might | Power | `Power Quest` | `Skill_Power_Quest` |
| Swordjinn | Power | `Power Blades` | `Skill_Power_Blades` |
| Aerial Catch | Special | `Special Quest` | `Skill_Special_Quest` |
| Dancing Blades | Special | `Special Extra Spins` | `Skill_Special_Extra_Spins` |
| Healing Blades | Special | `Special Healing` | `Skill_Special_Healing` |
| Sand Vortex | Special | `Special Vacuum` | `Skill_Special_Vacuum` |
| Acrobatics | Defense | `Defense Energy` | `Skill_Defense_Energy` |
| Air Dash | Defense | `Defense Dash` | `Skill_Defense_Dash` |
| Tornado Jump | Defense | `Defense Tornado` | `Skill_Defense_Tornado` |
| Leaping Strike | Dash | `Dash Attack` | `Skill_Dash_Attack` |
| Jinniya's Gift | Trait | `Trait Extra Wish` | `Skill_Trait_Extra_Wish` |
| Wish of Omnipotence | Trait | `Trait Wish Omnipotence` | `Skill_Trait_Wish_Omnipotence` |
| Major Enchantment | Passive | `Passive Energy` | `Skill_Passive_Energy` |
| Master Thief | Passive | `Passive Extra MO` | `Skill_Passive_Extra_MO` |
| Dream Stride | Ultimate | `Ultimate 2 Carpet DS` | `Skill_Ultimate_2_Carpet_DS` |
| Infinite Wishes | Ultimate | `Ultimate 1 More Wish` | `Skill_Ultimate_1_More_Wish` |
| Quick Ride | Ultimate | `Ultimate 2 Carpet Dash` | `Skill_Ultimate_2_Carpet_Dash` |
| Wondrous Wishes | Ultimate | `Ultimate 1 Better Wish` | `Skill_Ultimate_1_Better_Wish` |

## Beowulf

**Hero spelling:** `hero = "Beowulf"` for `kind = "talent"`, and `hero = "Beowulf"` for `kind = "skill"`.

| Talent in game | Ability | Search word | Rename with |
|---|---|---|---|
| Blademaster | Attack | `Attack Speed` | `Skill_Attack_Speed` |
| Blazing Runes | Attack | `Attack Special Crit` | `Skill_Attack_Special_Crit` |
| Breath of Fire | Attack | `Attack Fire Cone` | `Skill_Attack_Fire_Cone` |
| Furious Blows | Attack | `Attack After Special` | `Skill_Attack_After_Special` |
| Heavy Strikes | Attack | `Attack Wide` | `Skill_Attack_Wide` |
| Retaliation | Attack | `Attack Flurry` | `Skill_Attack_Flurry` |
| Double Shock | Power | `Power Double` | `Skill_Power_Double` |
| Eruption | Power | `Power End AOE` | `Skill_Power_End_AOE` |
| Scorched Earth | Power | `Power Trail` | `Skill_Power_Trail` |
| Bladestorm | Special | `Special Loop` | `Skill_Special_Loop` |
| Fiery Seismo | Special | `Special Multi Shock` | `Skill_Special_Multi_Shock` |
| Secondary Tremor | Special | `Special Sends Power` | `Skill_Special_Sends_Power` |
| Rampart | Defense | `Defense Quest` | `Skill_Defense_Quest` |
| Runes of War | Defense | `Defense Damage Aura` | `Skill_Defense_Damage_Aura` |
| Shield Charge | Defense | `Defense Dash` | `Skill_Defense_Dash` |
| Sparkling Shield | Defense | `Defense Block Deals Damage` | `Skill_Defense_Block_Deals_Damage` |
| Fiery Slash | Dash | `Dash Attack` | `Skill_Dash_Attack` |
| Battle Cry | Trait | `Trait Battlecry` | `Skill_Trait_Battlecry` |
| Draconic Binds | Trait | `Trait Quest` | `Skill_Trait_Quest` |
| Fire Wings | Trait | `Trait AOE` | `Skill_Trait_AOE` |
| Explosive Fire | Passive | `Passive Ignite Explosion` | `Skill_Passive_Ignite_Explosion` |
| Furnace | Passive | `Passive Better Ignite` | `Skill_Passive_Better_Ignite` |
| Fireball | Ultimate | `Ultimate 2 Fireball Dash` | `Skill_Ultimate_2_Upgrade_Fireball_Dash` |
| Immolation | Ultimate | `Ultimate 1 Immolation` | `Skill_Ultimate_1_Upgrade_Immolation` |
| Sudden Growth | Ultimate | `Ultimate 1 Big Wyrm` | `Skill_Ultimate_1_Upgrade_Big_Wyrm` |
| Volcanic Rage | Ultimate | `Ultimate 2 Volcanic` | `Skill_Ultimate_2_Upgrade_Volcanic` |

## Carmilla

**Hero spelling:** `hero = "Carmilla"` for `kind = "talent"`, and `hero = "Carmilla"` for `kind = "skill"`.

| Talent in game | Ability | Search word | Rename with |
|---|---|---|---|
| Cruel Strike | Attack | `Attack Last Combo Move` | `Skill_Attack_Last_Combo_Move` |
| Onslaught | Attack | `Attack Special Rush` | `Skill_Attack_Special_Rush` |
| Razor Claws | Attack | `Attack Bleed` | `Skill_Attack_Bleed` |
| Blood Rage | Power | `Power Quest` | `Skill_Power_Quest` |
| Flesh Rip | Power | `Power Bleed Crit` | `Skill_Power_Bleed_Crit` |
| Furious Tempest | Power | `Power Maintained Damage` | `Skill_Power_Maintained_Damage` |
| Injection | Power | `Power Special Bomb` | `Skill_Power_Special_Bomb` |
| Wild Heart | Power | `Power Range` | `Skill_Power_Range` |
| Go for the Throat | Special | `Special Critical Distance` | `Skill_Special_Critical_Distance` |
| Life Essence | Special | `Special Quest` | `Skill_Special_Quest` |
| Victimization | Special | `Special Marked` | `Skill_Special_Marked` |
| Aggressive Flock | Defense | `Defense Projectile` | `Skill_Defense_Projectile` |
| Bat Master | Defense | `Defense Master` | `Skill_Defense_Master` |
| Dispersion | Defense | `Defense Aoe Bleed` | `Skill_Defense_Aoe_Bleed` |
| Puncture | Dash | `Dash Blood` | `Skill_Dash_Blood` |
| Seductive Provocation | Dash | `Dash Taunt` | `Skill_Dash_Taunt` |
| Angel and Demon | Trait | `Trait Heal Buff` | `Skill_Trait_Heal_Buff` |
| Gust | Trait | `Trait Push back` | `Skill_Trait_Push_Back` |
| Life Tap | Trait | `Trait Life Tap` | `Skill_Trait_Life_Tap` |
| Blood Reserve | Passive | `Passive Blood Reserve` | `Skill_Passive_Blood_Reserve` |
| Boiling Blood | Passive | `Passive Life Use Regen` | `Skill_Passive_Life_Use_Regen` |
| Sadism | Passive | `Passive Critical Bleed` | `Skill_Passive_Critical_Bleed` |
| Heartbreak | Ultimate | `Ultimate 1 Combo Pike` | `Skill_Ultimate_1_Combo_Pike` |
| Mass Punishment | Ultimate | `Ultimate 2 Add Zone Attack` | `Skill_Ultimate_2_Add_Zone_Attack` |
| Mistress of Pain | Ultimate | `Ultimate 2 Increase Max Attack` | `Skill_Ultimate_2_Increase_Max_Attack` |
| Torture of the Pale | Ultimate | `Ultimate 1 Return` | `Skill_Ultimate_1_Return` |

## Geppetto

**Hero spelling:** `hero = "Geppetto"` for `kind = "talent"`, and `hero = "Geppetto"` for `kind = "skill"`.

| Talent in game | Ability | Search word | Rename with |
|---|---|---|---|
| Family Meeting | Attack | `Attack Group Speed` | `Skill_Attack_Group_Speed` |
| Nailing Strike | Attack | `Attack Finisher` | `Skill_Attack_Finisher` |
| Oiled Mechanisms | Attack | `Attack Makes Dummies Attack` | `Skill_Attack_Makes_Dummies_Attack` |
| Flux Capacitor | Power | `Power Overcharge` | `Skill_Power_Overcharge` |
| Magnetic Hammer | Power | `Power Magnet` | `Skill_Power_Magnet` |
| Unstable Cores | Power | `Power Unstable` | `Skill_Power_Unstable` |
| Clockwork Medicine | Special | `Special Regeneration` | `Skill_Special_Regeneration` |
| Dummyball | Special | `Special Creates Dummy` | `Skill_Special_Creates_Dummy` |
| Vacuum Capsule | Special | `Special Pushback` | `Skill_Special_Pushback` |
| Forked Lightning | Defense | `Defense Lightning` | `Skill_Defense_Lightning` |
| Laser Lenses | Defense | `Defense Laser Eyes` | `Skill_Defense_Laser_Attack` |
| Lightning Rod Dummies | Defense | `Defense AOE` | `Skill_Defense_AOE` |
| Rocket Science | Dash | `Dash Deals Damage` | `Skill_Dash_Deals_Damage` |
| Explosive Builds | Trait | `Trait Blast Construction` | `Skill_Trait_Blast_Construction` |
| Fireworks | Trait | `Trait Missiles` | `Skill_Trait_Missiles` |
| Heart Ties | Trait | `Trait Max Health` | `Skill_Trait_Max_Health` |
| Large Family | Trait | `Trait Extra Charge` | `Skill_Trait_Extra_Charge` |
| Mourning Rage | Trait | `Trait Buff On Dummy Death` | `Skill_Trait_Buff_On_Dummy_Death` |
| Pogo-Hoppers | Trait | `Trait Attack Move` | `Skill_Trait_Attack_Move` |
| Sharp Noses | Trait | `Trait Nose Attack` | `Skill_Trait_Nose_Attack` |
| Twin Dummies | Trait | `Trait Twins` | `Skill_Trait_Twins` |
| Flash of Genius | Passive | `Passive Create Objects` | `Skill_Passive_Create_Object` |
| Bomb Reserve | Ultimate | `Ultimate 1 Bomber` | `Skill_Ultimate_1_Bomber` |
| High Voltage | Ultimate | `Ultimate 2 Overclock Hit` | `Skill_Ultimate_2_Overclock_Hit` |
| Hyperclock | Ultimate | `Ultimate 2 Overclock Ignite` | `Skill_Ultimate_2_Overclock_Ignite` |
| Master Puppet | Ultimate | `Ultimate 1 Big Meca Puppet` | `Skill_Ultimate_1_Big_Meca_Puppet` |

## Juliet

**Hero spelling:** `hero = "Juliet"` for `kind = "talent"`, and `hero = "Juliet"` for `kind = "skill"`.

:::caution
Juliet's talent names are stored differently from every other hero's. You can change a Juliet talent's **description** and numbers, but changing its **name** fails with `text key ... not in bank`.
:::

| Talent in game | Ability | Search word | Rename with |
|---|---|---|---|
| Hot Shots | Attack | `Attack Ignite` | `Skill_Attack_Ignite` |
| Knockout | Attack | `Attack Close Combat` | `Skill_Attack_Close_Combat` |
| Lucky Shot | Attack | `Attack Power` | `Skill_Attack_Power` |
| Swirling Rose | Attack | `Attack Rose AOE` | `Skill_Attack_Rose_AOE` |
| Volcanic Shots | Attack | `Attack Burst` | `Skill_Attack_Burst` |
| Double Tap | Power | `Power Double Shot` | `Skill_Power_Double_Shot` |
| Explosive Backstep | Power | `Power Attack Backstep` | `Skill_Power_Attack_Backstep` |
| Guns & Roses | Power | `Power Quest Explode` | `Skill_Power_Quest_Explode` |
| Longshot | Power | `Power More Range` | `Skill_Power_More_Range` |
| Shadow Round | Power | `Power Vulnerable` | `Skill_Power_Vulnerable` |
| Shrapnel | Power | `Power Cone Damage` | `Skill_Power_Cone_Damage` |
| Kiss the Groom | Special | `Special Quest Dream Shard` | `Skill_Special_Quest_Dream_Shard` |
| Love Sparks | Special | `Special Projectile` | `Skill_Special_Projectile` |
| Overflowing Passion | Special | `Special Heal` | `Skill_Special_Heal` |
| Blind Shots | Defense | `Defense More Shot` | `Skill_Defense_More_Shots` |
| Bullet Ballet | Defense | `Defense Ricochet` | `Skill_Defense_Ricochet` |
| Defensive Reload | Defense | `Defense Reload` | `Skill_Defense_Reload` |
| Comforting Presence | Dash | `Dash Shield` | `Skill_Dash_Shield` |
| Heartbeat | Trait | `Trait AOE` | `Skill_Trait_AOE` |
| Valiant Hearts | Trait | `Trait Buff` | `Skill_Trait_Buff` |
| Large Chambers | Passive | `Passive More Ammo` | `Skill_Passive_More_Ammo` |
| Wedding Gifts | Passive | `Passive Bonus Object` | `Skill_Passive_Bonus_Object` |
| Flashy Ending | Ultimate | `Ultimate 1 End AOE` | `Skill_Ultimate_1_End_AOE` |
| Passion Dance | Ultimate | `Ultimate 1 Heal` | `Skill_Ultimate_1_Heal` |
| Plague Flask | Ultimate | `Ultimate 2 Marked` | `Skill_Ultimate_2_Marked` |
| Unstable Concoction | Ultimate | `Ultimate 2 Dash AOE` | `Skill_Ultimate_2_Dash_AOE` |

## Melusine

**Hero spelling:** `hero = "Melusine"` for `kind = "talent"`, and `hero = "Melusine"` for `kind = "skill"`.

| Talent in game | Ability | Search word | Rename with |
|---|---|---|---|
| Deep Beat | Attack | `Attack Beat` | `Skill_Attack_Beat` |
| Protective Flow | Attack | `Attack Shield` | `Skill_Attack_Shield` |
| Submerging Attack | Attack | `Attack Amplifies` | `Skill_Attack_Amplifies` |
| Wisp Surge | Attack | `Attack Speed` | `Skill_Attack_Speed` |
| Aftershock | Power | `Power Core` | `Skill_Power_Water_Core` |
| Freezing Splash | Power | `Power Chill` | `Skill_Power_Chill` |
| Geyser | Power | `Power Geyser` | `Skill_Power_Geyser` |
| Backwash | Special | `Special Backwards` | `Skill_Special_Backwards` |
| Spring Water | Special | `Special Heal` | `Skill_Special_Heal` |
| Tidal Wave | Special | `Special Large Waves` | `Skill_Special_Large_Waves` |
| Waterlogging | Special | `Special Growth` | `Skill_Special_Growth` |
| Power Dive | Defense | `Defense Power` | `Skill_Defense_Power` |
| Razor Tail | Defense | `Defense Deals Damage` | `Skill_Defense_Deals_Damage` |
| Underwater Predation | Defense | `Defense Hold` | `Skill_Defense_Hold` |
| Water Bubble | Defense | `Defense Block` | `Skill_Defense_Block` |
| Water Communion | Defense | `Defense Improve Special` | `Skill_Defense_Improve_Special` |
| Bewitching Song | Trait | `Trait Weakens` | `Skill_Trait_Weakens` |
| Sea Dance | Trait | `Trait Teleport` | `Skill_Trait_Teleport` |
| Shimmering Scales | Trait | `Trait Armor` | `Skill_Trait_Armor` |
| Enduring Wisp | Passive | `Passive Auto Wisp` | `Skill_Passive_Auto_Wisp` |
| Final Burst | Passive | `Passive Detonation` | `Skill_Passive_Detonation` |
| Soothing Presence | Passive | `Passive Heal In Combat` | `Skill_Passive_Heal_In_Combat` |
| Crescendo | Ultimate | `Ultimate 2 Spawn More` | `Skill_Ultimate_2_Upgrade_Spawn_More` |
| Healing Blast | Ultimate | `Ultimate 1 Heal` | `Skill_Ultimate_1_Upgrade_Heal` |
| Overtone Singing | Ultimate | `Ultimate 2 Sing Stance Wisp` | `Skill_Ultimate_2_Upgrade_Sing_Stance_Wisp` |
| Vortex Bomb | Ultimate | `Ultimate 1 Vortex` | `Skill_Ultimate_1_Upgrade_Vortex` |

## Merlin

**Hero spelling:** `hero = "Merlin"` for `kind = "talent"`, and `hero = "Merlin"` for `kind = "skill"`.

| Talent in game | Ability | Search word | Rename with |
|---|---|---|---|
| Wild Magic | Attack | `Attack Bleed After Power` | `Skill_Attack_Bleed_After_Power` |
| Brambles Whirlwind | Power | `Power Power AOE` | `Skill_Power_Power_AOE` |
| Freezing Stones | Power | `Power Defense Chilled` | `Skill_Power_Defense_Chilled` |
| Natural Harmony | Power | `Power Heal` | `Skill_Power_Heal` |
| Shooting Stars | Power | `Power Special Vulnerable` | `Skill_Power_Special_Vulnerable` |
| Arcane Shield | Special | `Special Block` | `Skill_Special_Block` |
| Arcanic Rune | Special | `Special Gain Potency` | `Skill_Special_Gain_Potency` |
| Fire Barrage | Special | `Special Special Missiles` | `Skill_Special_Missiles` |
| Frost Arcane | Special | `Special Defense Attack AOE` | `Skill_Special_Defense_Attack_AOE` |
| Lightning Storm | Special | `Special Power Lightning` | `Skill_Special_Power_Lightning` |
| Holy Fire | Defense | `Defense Special Ignite` | `Skill_Defense_Special_Ignite` |
| Retaliation | Defense | `Defense Power Shield` | `Skill_Defense_Power_Shield` |
| Sacred Ground | Defense | `Defense Defense DMG Buff Zone` | `Skill_Defense_Defense_DMG_Buff_Zone` |
| Sacred Strike | Defense | `Defense Attack Finisher` | `Skill_Defense_Attack_Finisher` |
| Life Seed | Dash | `Dash Heal` | `Skill_Dash_Heal` |
| Celestial Wrath | Trait | `Trait Lightning` | `Skill_Trait_Lightning` |
| Grace of Heaven | Trait | `Trait Reduce Cooldown After Defense` | `Skill_Trait_Reduce_Cooldown_After_Defense` |
| Trinity | Trait | `Trait Quest Gain Charge` | `Skill_Trait_Quest_Gain_Charge` |
| Astrology | Passive | `Passive Gain Reroll High Talent` | `Skill_Passive_Gain_Reroll_High_Talent` |
| Elemental Affinity | Passive | `Passive Crit Chance On Status` | `Skill_Passive_Crit_Chance_On_Status` |
| Eternal Dream | Passive | `Passive Repeatable Quest Gain DS` | `Skill_Passive_Repeatable_Quest_Gain_DS` |
| Runic Might | Passive | `Passive Quest Crit Chance` | `Skill_Passive_Quest_Crit_Chance` |
| Corrupted Arts | Ultimate | — | `Skill_Ultimate_2_Dmg_Per_Cursed` |
| Dark Swiftness | Ultimate | `Ultimate 2 Dash` | `Skill_Ultimate_2_Dash` |
| Energy Stone | Ultimate | `Ultimate 1 AOE` | `Skill_Ultimate_1_AOE` |
| Megalithic Site | Ultimate | `Ultimate 1 Multi Stone` | `Skill_Ultimate_1_Multi_Stone` |

## The Pied Piper

**Hero spelling:** `hero = "Piper"` for `kind = "talent"`, and `hero = "Piper"` for `kind = "skill"`.

| Talent in game | Ability | Search word | Rename with |
|---|---|---|---|
| Ghost Notes | Attack | `Attack Ghost Notes` | `Skill_Attack_Ghost_Notes` |
| Low Notes | Attack | `Basic Big Shots` | `Skill_Attack_Big_Shots` |
| Sniper | Attack | `Basic Primary Long Shots` | `Skill_Attack_Power_Long_Shots` |
| Virtuoso | Attack | `Attack Move Speed` | `Skill_Attack_Move_Speed` |
| Extra Measure | Power | `Primary More Waves After Defense` | `Skill_Power_More_Waves_After_Defense` |
| Quintuplets | Power | `Primary Wide Spread` | `Skill_Power_Wide_Spread` |
| Spinning Solo | Power | `Primary Evasion` | `Skill_Power_Evasion` |
| Acoustic Pulses | Special | `Secondary DOT` | `Skill_Special_DOT` |
| Chorus | Special | `Special Sends Attacks` | `Skill_Special_Sends_Attacks` |
| Freezing Trap | Special | `Secondary Chill` | `Skill_Special_Chill` |
| Grand Finale | Special | `Secondary Explosive Zone` | `Skill_Special_Explosive_Zone` |
| Explosive Blast | Defense | `Defensive Deals Damage` | `Skill_Defense_Deals_Damage` |
| Invasive Blast | Defense | `Defense Spawn Pets` | `Skill_Defense_Spawn_Pets` |
| Perfect Harmony | Defense | `Defensive Heal On Hit` | `Skill_Defense_Heal_On_Hit` |
| Sforzando | Defense | `Special Implosive` | `Skill_Defense_Implosive` |
| Sound Barrier | Defense | `Defensive Armor Quest` | `Skill_Defense_Armor_Quest` |
| Music of the Spheres | Dash | `Dash Trap` | `Skill_Dash_Trap` |
| Explosive Rats | Trait | `Trait Explosive Pets` | `Skill_Trait_Explosive_Pets` |
| Giant Rats | Trait | `Trait Big Pets` | `Skill_Trait_Big_Pets` |
| Horde | Trait | `Trait More Controllable Pets` | `Skill_Trait_More_Controllable_Pets` |
| Leeching Charm | Trait | `Trait Pets Heal` | `Skill_Trait_Pets_Heal` |
| Stimulant Vibes | Trait | `Trait Pets Within Special` | `Skill_Trait_Pets_Within_Special` |
| Jig | Ultimate | `Ultimate 1 Dash` | `Skill_Ultimate_1_Upgrade_Dash` |
| Rain of Notes | Ultimate | `Ultimate 1 Notes Rain` | `Skill_Ultimate_1_Upgrade_Notes_Rain` |
| Rat King | Ultimate | `Ultimate 2 Rat King` | `Skill_Ultimate_2_Upgrade_Rat_King` |
| Vermin Massacre | Ultimate | `Ultimate 2 Explosion` | `Skill_Ultimate_2_Upgrade_Explosion` |

## Romeo

**Hero spelling:** `hero = "Romeo"` for `kind = "talent"`, and `hero = "Romeo"` for `kind = "skill"`.

| Talent in game | Ability | Search word | Rename with |
|---|---|---|---|
| Deadly Brambles | Attack | `Attack Rose Seed` | `Skill_Attack_Rose_Seed` |
| Kick | Attack | `Attack Kick` | `Skill_Attack_Kick` |
| Panache | Attack | `Attack Panache` | `Skill_Attack_Panache` |
| Relentless Assaults | Attack | `Attack Power Ripost` | `Skill_Attack_Power_Ripost` |
| Bursting Bloom | Power | `Power Burst` | `Skill_Power_Burst` |
| Healing Rose | Power | `Power Heal` | `Skill_Power_Heal` |
| Ice Rose | Power | `Power Chilled` | `Skill_Power_Chilled` |
| Swarm of Petals | Power | `Power Cone Attack` | `Skill_Power_Cone_Attack` |
| Thorny Rose | Power | `Power Trail` | `Skill_Power_Trail` |
| Burning Kiss | Special | `Special Ignite` | `Skill_Special_Ignite` |
| Kiss the Bride | Special | `Special Quest Dream Shard` | `Skill_Special_Quest_Dream_Shard` |
| Love Shield | Special | `Special Invulnerable` | `Skill_Special_Invulnerable` |
| Surge of bravery | Special | `Special Buff Attack` | `Skill_Special_Buff_Attack` |
| Floral Dodge | Defense | `Defense Power` | `Skill_Defense_Power` |
| Secret Weapon | Defense | `Defense Quest` | `Skill_Defense_Quest` |
| Selfless Defender | Defense | `Defense Shield` | `Skill_Defense_Shield` |
| Wind Spiral | Defense | `Defense AOE` | `Skill_Defense_AOE` |
| Broad Stroke | Dash | `Dash AOE Attack` | `Skill_Dash_AOE_Attack` |
| Flash of Steel | Dash | `Dash Attack Return` | `Skill_Dash_Attack_Return` |
| Love Thread | Trait | `Trait Beam` | `Skill_Trait_Beam` |
| Thorns Aura | Trait | `Trait AOE` | `Skill_Trait_AOE` |
| Fencing Reflex | Passive | `Attack Block` | `Skill_Passive_Attack_Block` |
| Burning Dance | Ultimate | `Ultimate 1 Ignite` | `Skill_Ultimate_1_Ignite` |
| Explosive Performance | Ultimate | `Ultimate 1 Projectile` | `Skill_Ultimate_1_Projectile` |
| Funeral Bouquet | Ultimate | `Ultimate 2 Attack Rose` | `Skill_Ultimate_2_Attack_Rose` |
| Tempestuous Roses | Ultimate | `Ultimate 2 Wide And AOE` | `Skill_Ultimate_2_Wide_And_AOE` |

## Scarlet

**Hero spelling:** `hero = "Red"` for `kind = "talent"`, and `hero = "Red"` for `kind = "skill"`.

| Talent in game | Ability | Search word | Rename with |
|---|---|---|---|
| Cleave | Attack | `Basic Cleave` | `Skill_Attack_Cleave` |
| Slash Flurry | Attack | `Attack Flurry` | `Skill_Attack_Flurry` |
| Wide Attacks | Attack | `Basic Wide Attacks` | `Skill_Attack_Wide_Attacks` |
| Devourer | Power | `Primary Wolf Quest` | `Skill_Power_Wolf_Quest` |
| Energy | Power | `Primary Extra Combo Points` | `Skill_Power_Extra_Combo_Points` |
| Evisceration | Power | `Primary Bleed` | `Skill_Power_Bleed` |
| Explosive Rush | Power | `Primary Triggers Special` | `Skill_Power_Triggers_Special` |
| Armor Break | Special | `Secondary Reduce Armour` | `Skill_Special_Reduce_Armor` |
| Distant Explosions | Special | `Secondary Can Hold` | `Skill_Special_Can_Hold` |
| Pulverize | Special | `Secondary Use Combo Points` | `Skill_Special_Use_Combo_Points` |
| Pyromania | Special | `Secondary Ignite` | `Skill_Special_Ignite` |
| Short Wick | Special | `Secondary Quick Bombs` | `Skill_Special_Quick_Bombs` |
| Aggressive Defense | Defense | `Defensive AOE On Trigger` | `Skill_Defense_AOE_On_Trigger` |
| Murderous Intent | Defense | `Defensive Combo` | `Skill_Defense_Combo` |
| On the Hunt | Defense | `Defensive Mark` | `Skill_Defense_Mark` |
| Shadow Strikes | Defense | `Defensive Human Quest` | `Skill_Defense_Human_Quest` |
| Double Strike | Dash | `Dash Attack` | `Skill_Dash_Attack` |
| Fan of Spikes | Dash | `Dash Projectiles` | `Skill_Dash_Projectiles` |
| Shapeshifter | Trait | `Trait Active` | `Skill_Trait_Active` |
| True Instincts | Trait | `Trait Better Forms` | `Skill_Trait_Better_Forms` |
| Adrenaline | Passive | `Passive Combo Use Bonus` | `Skill_Passive_Combo_Use_Bonus` |
| Savagery | Passive | `Passive Combo Chain` | `Skill_Passive_Combo_Chain` |
| Bone Cracker | Ultimate | `Ultimate 2 Explosif` | `Skill_Ultimate_2_Explosif` |
| Fiery Maw | Ultimate | `Ultimate 1 Fire` | `Skill_Ultimate_1_Fire` |
| Pack Leader | Ultimate | `Ultimate 2 Heal` | `Skill_Ultimate_2_Heal` |
| Reload | Ultimate | `Ultimate 1 Reload` | `Skill_Ultimate_1_Reload` |

## The Snow Queen

**Hero spelling:** `hero = "Snow_Queen"` for `kind = "talent"`, and `hero = "Snow_Queen"` for `kind = "skill"`.

| Talent in game | Ability | Search word | Rename with |
|---|---|---|---|
| Dual Lances | Attack | `Attack Dual` | `Skill_Attack_Dual` |
| Windy Lances | Attack | `Attack Seeking` | `Skill_Attack_Seeking` |
| Frost Surge | Power | `Power Hold` | `Skill_Power_Hold` |
| Hailstorm | Power | `Power Ice Waves` | `Skill_Power_Ice_Waves` |
| Shattering Blast | Power | `Power Shatter` | `Skill_Power_Shatter` |
| Snowball | Power | `Power Snowball` | `Skill_Power_Snowball` |
| Flurry of Shards | Special | `Special Extra Waves` | `Skill_Special_Extra_Waves` (description only) |
| Ice Cores | Special | `Special Icicles` | `Skill_Special_Icicles` |
| Ice Spray | Special | `Special Double` | `Skill_Special_Double` |
| Ice Clone | Defense | `Defense Clone` | `Skill_Defense_Clone` |
| Ice Shield | Defense | `Defense Shield` | `Skill_Defense_Shield` |
| Pirouette | Defense | `Defense Final` | `Skill_Defense_Final` |
| Strafe | Defense | `Defense Sends Attacks` | `Skill_Defense_Sends_Attacks` |
| Freezing Stars | Dash | `Dash Freeze Trap` | `Skill_Dash_Freeze_Trap` |
| Slide | Dash | `Dash Frost` | `Skill_Dash_Frost` |
| Lance Burst | Trait | `Trait Sends Attacks` | `Skill_Trait_Sends_Attacks` |
| Protective Crown | Trait | `Trait Shield` | `Skill_Trait_Shield` |
| Radiant Crown | Trait | `Trait Charge` | `Skill_Trait_Charge` |
| Rupture | Trait | `Trait Quest` | `Skill_Trait_Quest` |
| Cold Heart | Passive | `Passive Chilled Crit` | `Skill_Passive_Chilled_Crit` |
| Frost Queen | Passive | `Passive Better Frost` | `Skill_Passive_Better_Frost` |
| Frostbite | Passive | `Passive Damage To Chilled` | `Skill_Passive_Damage_To_Chilled` |
| Ice Beam | Ultimate | `Ultimate 1 Ice Beam` | `Skill_Ultimate_1_Upgrade_Ice_Beam` |
| Rending Storm | Ultimate | — | `Skill_Ultimate_2_Upgrade_Abillity_Blast` |
| Royal Ray | Ultimate | `Ultimate 1 Casts Trait` | `Skill_Ultimate_1_Upgrade_Casts_Trait` |
| Shattering Storm | Ultimate | `Ultimate 2 Shatter` | `Skill_Ultimate_2_Upgrade_Shatter` |

## Sun Wukong

**Hero spelling:** `hero = "SunWukong"` for `kind = "talent"`, and `hero = "Sun_Wukong"` for `kind = "skill"`.

| Talent in game | Ability | Search word | Rename with |
|---|---|---|---|
| Celestial Pillar | Attack | `Attack Finisher` | `Skill_Attack_Finisher` |
| Ch'i Outburst | Attack | `Attack Beam` | `Skill_Attack_Beam` |
| Stick Twirl | Attack | `Dash Attack` | `Skill_Attack_After_Dash` |
| Airbender | Power | `Power Extra Targets` | `Skill_Power_Extra_Targets` |
| Focused Strikes | Power | `Power Hold` | `Skill_Power_Hold` |
| Thundercloud | Power | `Power Lightning` | `Skill_Power_Lightning` |
| Mantra of Balance | Special | `Special Debuff` | `Skill_Special_Debuff` |
| Resonance | Special | `Special Triggers Stance` | `Skill_Special_Triggers_Stance` |
| Ringing Beads | Special | `Special Attack AOE` | `Skill_Special_Attack_AOE` |
| Sacred Seal | Special | `Special Explosion` | `Skill_Special_Explosion` |
| Ōm | Special | `Special Beads Increase` | `Skill_Special_Beads_Increase` |
| Divine Palm | Defense | `Defense Perfect` | `Skill_Defense_Perfect` |
| One-Inch Punch | Defense | `Defense Retaliate` | `Skill_Defense_Retaliate` |
| Stone Monkey | Defense | `Defense Quest` | `Skill_Defense_Quest` |
| Sprint | Dash | `Dash Sprint` | `Skill_Dash_Sprint` |
| Fiery Dragon | Trait | `Trait Fire` | `Skill_Trait_Fire` |
| Frost Tiger | Trait | `Trait Frost` | `Skill_Trait_Frost` |
| Mind Fortress | Trait | `Trait Longer Effects` | `Skill_Trait_Longer_Effects` |
| Supreme Polarity | Trait | `Trait Better Stances` | `Skill_Trait_Better_Stances` |
| Way of Awakening | Trait | `Trait Awakened` | `Skill_Trait_Awakened` |
| Fiery Golden Eyes | Passive | `Passive Reveal` | `Skill_Passive_Reveal` |
| Thirst for Immortality | Passive | `Passive Objects Quest` | `Skill_Passive_Objects_Quest` |
| Army of Monkeys | Ultimate | `Ultimate 1 More Monkeys` | `Skill_Ultimate_1_More_Monkeys` |
| Divine Beverage | Ultimate | `Ultimate 2 Omnipotence` | `Skill_Ultimate_2_Omnipotence` |
| Mantra of Replication | Ultimate | `Ultimate 1 Special Monkey` | `Skill_Ultimate_1_Special_Monkey` |
| Perfect Copy | Ultimate | `Ultimate 2 Perfect Copy` | `Skill_Ultimate_2_Perfect_Copy` |
