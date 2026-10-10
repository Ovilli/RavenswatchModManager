---
title: Lua gameplay API
description: The R.* calls a Lua mod uses to change a run — rerolls, cooldowns, shards, keys, levels, items, talents, melodies, controls and chapter flow.
---

These are the `R.*` calls that change the game during a run. Each one sends the
game's **own** event to the hero (or, for chapter flow, to the world), the same
event an item, a talent or a pickup would send, so the game's own rules and
bonuses apply to it.

Every call returns `true` when the event was sent and `false` when it was
refused. A refusal is always logged with the reason, so `rsmm log` tells you
why.

## Before you call anything

- **Call from the main thread.** Wrap engine-changing calls in
  `R.schedule.next_main(function() ... end)`. An event callback such as
  `R.on("gameplay:ABILITY_EXIT", ...)` runs inside the game's own dispatch;
  schedule from it rather than calling directly.
- **The hero must act once.** Hero calls go to the hero's event dispatcher,
  which the SDK learns from the hero's first attack or ability. Until then they
  refuse with "no hero dispatcher yet".
- **Some calls need hero capture.** Calls marked *needs hero capture* read the
  hero to check the game will not crash. Declare it in the manifest:

  ```toml
  [mod]
  loader_flags = ["RSMM_ENABLE_HERO_CAPTURE"]
  ```

- **These are gameplay mods.** Online, a mod that uses any of these counts as a
  gameplay mod (see [Online play](/guides/modding/#online-play-client-only-and-gameplay-mods)).

A typical shape:

```lua
local R = require "rsmm"

R.on("gameplay:ABILITY_EXIT", function()
    R.schedule.next_main(function()
        R.ability.reset_cooldown()          -- every ability ready again
    end)
end)
```

**Status** below means: *proven* — seen working in game; *sent* — the event
reaches the game without error, but its visible effect is not yet confirmed.

## Offer rerolls — `R.reroll`

| Call | Does | Status |
|---|---|---|
| `R.reroll.add(n)` | `n` more rerolls on offer screens (1–32767) | proven |
| `R.reroll.get()` | rerolls the hero has, or `nil` (*needs hero capture*) | proven |

## Cooldowns and charges — `R.ability`

Slots: `"basic"`, `"primary"`, `"secondary"`, `"defensive"`, `"trait"`,
`"ultimate"`, `"dash"` (`R.ability.slots`).

| Call | Does | Status |
|---|---|---|
| `R.ability.reset_cooldown(slot)` | that ability off cooldown; no slot = every ability | proven |
| `R.ability.reduce_cooldown(seconds, slot)` | shorten a cooldown; no slot = every ability | sent |
| `R.ability.add_charge(slot, n)` | `n` extra charges (default 1) — only abilities that have charges | sent |
| `R.ability.remove_charge(slot)` | one charge less | sent |

```lua
R.ability.reset_cooldown("ultimate")
R.ability.reduce_cooldown(2.5)         -- every ability, 2.5 s sooner
```

## Shards, keys and other ingredients

| Call | Does | Status |
|---|---|---|
| `R.shards.gain(n)` | dream shards **as a pickup** — the hero's shard-gain bonuses apply | proven |
| `R.ingredient.add(name, n)` | `n` of an ingredient (default 1, up to 32767) | proven (`"Key"`, `"Note"`) |
| `R.ingredient.remove(name, n)` | take some away | sent |
| `R.ingredient.names()` | the ingredients loaded this session | proven |

Ingredients are `Bean`, `Key`, `Note`, `Stone`, `Straw` and `Wood`; names are
case-insensitive. `Key` opens locked chests; `Note` completes melodies.

`R.shards.add(n)` (no bonuses, exact amount) still exists alongside `gain`.

## Level and XP — `R.xp`

The level is **party-wide** — the game keeps one level for the whole party.
These need `R.stat.enable_writes()` first and *hero capture*.

| Call | Does | Status |
|---|---|---|
| `R.xp.grant(amount)` | give XP; levels up through the game's own curve | proven |
| `R.xp.set_level(n)` | jump to level `n` (raise only, up to the max) — fires the game's level-up | proven |
| `R.xp.set_xp(x)` | XP within the current level (below that level's threshold) | sent |

```lua
R.stat.enable_writes()
R.xp.set_level(10)     -- talent offers for every level gained
```

## Items — `R.give`

Rarities: `"common"`, `"rare"`, `"epic"`, `"legendary"`, `"cursed"`, or none for
any (`R.give.rarities`). With nothing of that rarity owned, nothing happens.

| Call | Does | Status |
|---|---|---|
| `R.give.remove_random(rarity)` | remove one random item | proven (any rarity) |
| `R.give.remove_all(rarity)` | remove every item of that rarity | proven (any rarity) |
| `R.give.duplicate_random(rarity)` | a second copy of a random item — common, rare or epic only | proven (any rarity) |

There is no "remove this exact item": the game's own event cannot name one.

## Talents — `R.talent`

| Call | Does | Status |
|---|---|---|
| `R.talent.upgrade(i)` | +1 tier on the `i`-th talent you own (*needs hero capture*) | proven |
| `R.talent.upgrade_random(n)` | +1 tier on `n` different random talents (default 1) | proven |
| `R.talent.upgrade_lowest(true)` | a random lowest-tier talent straight to legendary | proven |
| `R.talent.upgrade_lowest()` | the same talent, +1 tier only | sent |
| `R.talent.add_random_ultimate()` | a random ultimate talent (*needs hero capture*) | proven |
| `R.talent.reset()` | remove every talent — the hero's starting one stays | proven |
| `R.talent.owned()` | how many of the 10 talent slots are filled, or `nil` | proven |

`upgrade(i)` and `add_random_ultimate()` refuse when the game would crash:
with no talent owned, and with no ultimate left to add.

## Status — `R.status`

| Call | Does | Status |
|---|---|---|
| `R.status.clear()` | clear status effects | proven |
| `R.status.clear_stagger()` | empty the stagger gauge | runs, but heroes never build stagger — nothing to clear |
| `R.status.reset_stagger_resilience()` | reset stagger resilience | runs, but heroes never build stagger — nothing to clear |

## Revive tokens — `R.revive`

The party's revive tokens. Needs `R.stat.enable_writes()` first; online it
refuses unless you play solo (the value is shared with the other players).

| Call | Does | Status |
|---|---|---|
| `R.revive.tokens()` | tokens left, or `nil` outside a run | proven |
| `R.revive.add_token(n)` | `n` more tokens (default 1, up to 99) | proven |

## Melodies — `R.melody`

Melodies are named by their definition name: `Deal_Damage_Around`, `Fully_Heal`,
`Grant_Damage_Overtime`, `Increase_Fountain_Effect`,
`Increase_Move_Speed_At_Day`, `Instant_Level_Up`, `Power_Up_Level_Max`,
`Reduce_MO_Per_Collection`, `Refill_Sandman_Dreams`, `Remove_Key_Requirement`,
`Reveal_Map`, `Slow_Hourglass_Flow` (`R.melody.names()`).

| Call | Does | Status |
|---|---|---|
| `R.melody.choose(name)` | meant to start collecting that melody — **does not work**: the game still picks a random one | not working |
| `R.melody.remove(name)` | drop it | sent (effect unseen) |
| `R.melody.names()` | the melodies loaded this session | proven |

Notes fill the melody bar, so `R.ingredient.add("Note", n)` does work: each full
bar grants a melody. Which melody is the game's own random pick — in game,
`choose("Reveal_Map")` followed by notes granted two melodies, neither of them
Reveal_Map.

## Player controls — `R.control`

| Call | Does | Status |
|---|---|---|
| `R.control.lock()` | freeze the hero's input | proven |
| `R.control.release()` | undo every lock this mod's SDK took | proven |
| `R.control.unlock()` | undo one lock | proven |
| `R.control.held()` | locks currently held | proven |

The game counts locks, so two `lock()` calls need two unlocks. The SDK never
sends an unlock it does not owe, and forgets its locks when a run or chapter
ends. Always pair a lock with a release:

```lua
R.control.lock()
R.schedule.after_main(3, function() R.control.release() end)
```

## Chapter and run — `R.run`

These go to the **world**, not the hero, and act for the session host only — a
co-op client's call does nothing.

| Call | Does | Status |
|---|---|---|
| `R.run.next_chapter()` | finish the chapter as a success; the next one loads, or the run is won after the last | proven |
| `R.run.win()` | end the run as won now | proven |
| `R.run.lose()` | end the run as lost | proven |
| `R.run.world_ready()` | `true` once the current chapter's world has been seen | proven |

Each acts on the **current chapter only**: they refuse between chapters, in a
menu, on a loading screen or during a victory/defeat sequence, and a chapter
takes one end — a second call is refused instead of landing on the next chapter.
`R.run.world_ready()` is `false` until the chapter's first world event.

## When a call returns `false`

The log line says why. The common ones:

| Log says | Fix |
|---|---|
| `no hero dispatcher yet — the hero must act once first` | wait for an attack or ability (`R.give.ready()` turns true) |
| `needs the hero captured (RSMM_ENABLE_HERO_CAPTURE)` | add the loader flag to the manifest |
| `is experimental and off — call R.stat.enable_writes() first` | call it once before `R.xp.*` writes |
| `no chapter is in play` / `world dispatcher has not been seen` | call `R.run.*` during a chapter, after it has started |
| `unknown slot` / `unknown rarity` / `no ingredient named` / `no melody named` | check the spelling against the lists above |
