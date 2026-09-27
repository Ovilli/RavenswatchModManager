---
title: Web editor
description: Build item, talent, ability and map mods in your browser, from your own game files, with nothing to install.
---

The [web editor](/editor/) is `rsmm editor` running in
your browser. It has the same four tabs (Items, Talents, Abilities, Map) and
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
| **Items** | everything: pick a base, change name, text, rarity, icon and values, *Check*, save |
| **Talents** | everything: every value of a hero, card names and texts, *Check*, save |
| **Abilities** | everything: numbers, the graph, *Copy manifest code* |
| **Map** | the recipe, the spots, the 3D terrain, and the chapter's scenery and tiles drawn with the game's own models and textures, read from your install |

It cannot read or change the mods you already have. Each mod you save here
starts empty in the page and exists only until you close the tab, so download it
before you leave. To add blocks to an existing mod, press *Copy* and paste them
at the end of that mod's `manifest.toml`.

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
