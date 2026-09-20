---
title: Glossary
description: Engine, cooking, and modding terms used throughout these docs.
---

Quick definitions for the terms that show up across the RE notes and guides.

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
- **Anti-tamper / protector** — integrity logic in `Ravenswatch.exe` that crashes common hook points. v1 avoids the runtime path entirely. See [Anti-tamper protector](/reverse-engineering/protector/).
