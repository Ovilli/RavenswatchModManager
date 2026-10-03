---
title: Web editor
description: Build item, talent, ability and map mods in your browser, from your own game files, with nothing to install.
---

The [web editor](/editor/) is `rsmm editor` running in
your browser. It has the same five tabs (Items, Talents, Scripts, Abilities, Map) and
the same checks, and it saves the same mods. You need no Python, no CLI and no
desktop app to use it. Installing the mod it gives you still takes one of those.

## Using it

1. Open [docs.rsmm.me/editor](/editor/). The first visit
   downloads the Python runtime (about 12 MB); later visits use your browser's
   cache.
2. Choose your Ravenswatch folder. In Steam: right-click **Ravenswatch** →
   **Manage** → **Browse local files**. Choosing `DarkTalesResources` inside it
   works too.
3. Your browser asks whether to "upload" the folder. That is its standard
   wording for letting a page read a folder: the files are read on your
   computer and are never sent anywhere.
4. Make your changes. Where the local editor says *Add to mod*, the web
   editor saves the mod and hands it to you as a `.zip`.
5. Unzip it into your mods folder and apply it with the desktop app, or with
   `rsmm restore --all && rsmm apply`.

## What it can and cannot do

| Tab | In the browser |
|---|---|
| **Items** | everything: pick an item, choose *Replace this item* (change the shipped one) or *Make a copy* (a new item beside it), change name, text, rarity (copies only), icon, values and the stat each effect gives, *Check*, save |
| **Talents** | everything: card names and texts, each card's numbers per rarity, every value and the stat each effect gives, *Check*, save |
| **Scripts** | everything: test grants (items, talents and XP handed out when a run starts), for every hero or one |
| **Abilities** | everything: numbers, the graph, *Save to mod* (into your custom hero built on that hero; its saved changes load back when you pick it), *Copy manifest code* |
| **Map** | the recipe, the spots, the 3D terrain, and the chapter's scenery and tiles drawn with the game's own models and textures, read from your install |

To keep working on a mod you saved earlier, press *Open a mod folder…* and
pick that mod's folder. The editor reads its `manifest.toml`, its `init.lua` and
its `icons/`, and nothing else. A mod you save here exists only until you close
the tab, so download it before you leave.

### Opening a mod

Choose the mod beside *Save* and press *Open* (in the browser: *Open a mod
folder…*). Each item, talent card and test grant in it comes back as a change in
the bar, ready to edit. *Save to mod* then writes only the changes you made since
opening it, in place of the blocks they came from. Anything else in the
manifest stays exactly as it was: your comments, other blocks, and kinds the
editor does not edit. A block the editor cannot show exactly (a field it has no
control for, a value the base item no longer has) is listed when you open the
mod and left alone. After a save the mod stays open, so you can keep going.

### Test grants (Scripts)

The Scripts tab makes a mod hand you items, talents and XP at the start of every
run, so you can try a change at once instead of waiting for the game to offer
it. For example: 15 Ace of Spades, a Legendary talent, and 5000 XP (level 1 to 4).
Pick a hero under *Only for* and the grants happen only with that hero. Without
it they reach every hero you play, and a test mod left enabled levels up all of
them. Talents are chosen from that hero's own cards.

The grants are written into the mod's `init.lua`, between two marker lines the
editor owns. Code of your own in that file is left alone. They are for testing:
take them out (remove every row and save) before you publish the mod.

The Items and Talents tabs show each card the way the game will, drawn with the
compendium's own frames and fonts read from your install: highlighted words,
numbers, and the value behind every `{0}`, updated as you type. On the Talents
tab each card sits beside its text and numbers; a number that changes with the
card's rarity has one box per rarity, and *Show cards as* switches the previews
between Common, Rare, Epic and Legendary.

Both tabs take your own icon. On the Items tab, *Upload your own icon* gives the
item a picture of its own (scaled to 192×192 and cooked into a new texture
named after the item). On the Talents tab, *Replace icon* swaps a card's picture
(scaled to 128×128 and cooked over that card's icon), which is how a replacement
talent gets a look to match its new name and text. The PNG is saved in the mod's
`icons/` folder next to `manifest.toml`. Each
change has an undo button (↺), *Reset this item* / *Reset this hero* drops every
change to the one that is open, *Reset everything* (in the bar at the bottom)
drops every pending change in every tab after you confirm, and an unfinished edit is kept in your browser until you add it to a
mod (a dot marks it in the list). Private windows and some browsers do not keep
it.

It works in current Chrome, Edge, Firefox and Safari on a computer. Phones
cannot choose a folder.

## How it works

The page runs the real `rsmm` Python package in a
[Pyodide](https://pyodide.org) worker: the same code as the CLI, built from the
same commit as these docs. Each editor tab is the page `rsmm editor` serves
locally. Its requests go to the worker instead of a local server, and are
answered by the same routes (`rsmm.cli.editor`).

The folder you choose is mounted read-only, and each file is read only when
the engine opens it. Building the item list reads about a megabyte of a
multi-gigabyte install. The asset map is rebuilt from your own
`DarkTalesResources/UsedRscList.ot`, so the site hosts no game files at all.
