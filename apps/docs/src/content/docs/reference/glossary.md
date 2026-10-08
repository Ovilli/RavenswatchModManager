---
title: Glossary
description: Plain-language meanings of the words used in RSMM and these docs, from "vanilla" to "cooked asset".
---

What the words in these docs mean. The first section is for everyone. The later
sections are for mod makers and people digging into how the game works.

## Everyday words

- **Mod** — short for *modification*: an add-on that changes something in the
  game, such as how a hero looks, how strong an item is, or what the text says.
- **Vanilla** — the game exactly as it comes from Steam, with no mods.
- **RSMM** — Ravenswatch Mod Manager: the app, the website
  [rsmm.me](https://rsmm.me/registry), the web editor and the `rsmm` modding
  tools, together.
- **Registry** — the list of mods shared on rsmm.me. The app's **Browse** page
  shows it.
- **Apply** — write your switched-on mods into the game's files, keeping a copy of
  each original first. The app does this for you when you press **Launch
  Modded**.
- **Restore** — put the original game files back, undoing every mod.
- **Launch Modded / Launch Vanilla** — the app's two play buttons: start the game
  with your mods, or without any.
- **Profile** — a saved set of mods you can switch between. The **Default**
  profile is always the plain game.
- **Enabled / disabled** — whether a mod is switched on in the current profile. A
  disabled mod stays on your computer but isn't used.
- **Load order** — the order mods are applied in. When two mods change the same
  thing, the one applied later wins.
- **Conflict** — two switched-on mods that change the same file.
- **Dependency** — another mod a mod needs in order to work. A missing one shows as
  *missing deps*.
- **Config** — a mod's own settings, changed with its settings button in the app.
- **Overlay** — a small window some mods show on top of the game, like a damage
  meter.
- **Script mod / Lua mod** — a mod that includes a small program written in the
  Lua language, which runs inside the game. Most mods are not script mods.
- **Loader** — a small file (`winhttp.dll`) RSMM puts next to the game so that
  script mods can run. Mods that only change looks, numbers or text don't need it.
- **Experimental** — a kind of change RSMM doesn't fully understand yet. It may not
  work completely, and may crash the game.
- **Doctor** — RSMM's health check. In the app: **Commands → Doctor**. In a
  terminal: `rsmm doctor`.
- **Terminal / command line / CLI** — a window where you type commands instead of
  clicking. Only needed for the modding tools.
- **Web editor** — a page on this site that makes item, talent and ability mods in
  your browser. See [Web editor](/guides/web-editor/).

## Mod-making words

- **`manifest.toml`** — the text file at the heart of every mod. It says what the
  mod is called and what it changes.
- **`[[content]]` block** — a section of the manifest that adds or changes one
  thing, such as an item or an enemy.
- **`[[patch]]` block** — a section of the manifest that changes one value, such
  as a number. Several mods can patch different values of the same file without
  clashing.
- **Kind** — what a `[[content]]` block changes: `item`, `talent`, `enemy`,
  `map` and so on.
- **Base** — the existing game thing a new one is copied from, or the one being
  changed.
- **Lint** — `rsmm lint`: checks a mod for mistakes before you play.
- **Pack** — `rsmm pack`: bundles a mod into one `.zip` file to share.
- **Publish** — upload a mod to rsmm.me so others can install it.

## Assets & cooking

- **Cooked asset** — a game-ready binary baked from a source ("uncooked") asset. Ravenswatch loads everything from `<install>/DarkTalesResources/_Cooking/`. RSMM mods replace cooked files in place.
- **Uncooked asset** — the pre-bake source form (e.g. a PNG before it becomes a `.Texture.dxt`). The `data/uncooked/` mirror is decoded for local reference and is git-ignored.
- **`.gen` file** — a cooked binary that is *positionally serialized* against a per-class schema living inside `Ravenswatch.exe`. Building one from scratch needs the text-`.ot` → binary-`.gen` re-encoder.
- **`.ot` file** — the text/structured form of a cooked object (header + class table + section ranges). The `.ot` decoder parses these.
- **Encoded path / IYG cipher** — cooked files live under obfuscated names: the plaintext path run through a fixed Caesar substitution cipher (`src/rsmm/engine/cipher.py`, `find_iyg.py`). `asset_map.json` maps decoded ↔ encoded.
- **`asset_map.json`** — generated map of every decoded path to its encoded cooked path. Built by walking `UsedRscList.ot` and applying the cipher.
- **`UsedRscList.ot` / `UsedRscCache.ot`** — engine manifests of which resources are cooked. New custom assets register through these.

## Applying & lifecycle

- **Apply** — `./rsmm apply`: copy a mod's overrides into the game, backing up each original as `<file>.rsmm.bak`. Reversible with `./rsmm restore --all`.
- **Patch vs raw** — a mod changes the game either by dropping whole cooked files (**raw**) or by composing declarative `[[patch]]` blocks the applier merges per file (**patch** — conflict-friendly).
- **`manifest.toml`** — the one artifact every mod ships: metadata plus `[[content]]` / `[[patch]]` blocks. Mods ship *data, not code*.
- **Content kind** — a typed builder (`item`, `enemy`, `boss`, `hero`, `map`, `texture`, …) that clones a vanilla **base** and emits a new definition. Each carries a confidence: `confirmed`, `experimental`, or `guess`.

## Entities & gameplay state

Covered end to end in [Anatomy of an entity](/reverse-engineering/entity-anatomy/).

- **Entity (`oCEntity`)** — the world object: hero, enemy, barrel, shrine, dropped item. It holds a transform, links to the scene and its definition, and a map of components — almost no gameplay state of its own.
- **Component** — what gives an entity behaviour. 188 classes; a component is found by *asking its class*, never at a fixed offset on the entity.
- **`…Settings` / `…NetworkData` / `…PersistentData`** — the three companion classes a component can have: the authored data a mod edits, the slice that replicates to other players, and the slice that survives a chapter transition.
- **Definition (`oCEntitySettings`)** — the cooked template an entity is built from. Mods edit definitions; the engine builds instances.
- **HitPoint component** — where health actually lives (current and max). Every damageable entity has one, enemies included. HP is host-authoritative in co-op.
- **Entity value** — a gameplay number in the generic keyed store (attack power, cooldowns, status stacks — ~221 of them). Stored as *base + folded modifiers*, so a raw write is discarded on the next recompute; a durable change must be a modifier.
- **Hit data (`oCEntityHitData`)** — the object an attack travels as. There is no "deal N damage" call; the struct is built inline by the resolver, so mods ride an existing attack rather than fabricating one.
- **Display cache** — the numbers the in-run stat strip prints. A separate copy from the value store, refreshed only when the engine folds a modifier, which is why a working stat change can still show as `0`.

## Engine internals

- **oCEntity / oCEntitySettings** — the engine's entity object and its serialized settings tree. UI pages, enemies, items — all entities composed of component classes.
- **Symbol map** — `data/symbols.json`: the canonical name → address map for engine functions/globals/events. See [Engine symbols](/reference/symbols/).
- **Pattern resolver** — byte-signature database (`function_patterns.json`) that re-finds a function across game updates so mods can call it by name (`rsmm.call`).
- **Loader DLL** — `winhttp.dll` proxy + MinHook + Lua VM injected into the game for Lua-scripted mods (Windows). Texture/asset mods work without it.
- **Anti-tamper / protector** — the protector in `Ravenswatch.exe`. It does not block hooks at function entries; asset mods avoid the runtime path entirely and the loader hooks carefully.  See [Anti-tamper protector](/reverse-engineering/protector/).
