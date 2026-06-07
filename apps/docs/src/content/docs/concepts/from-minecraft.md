---
title: Coming from Minecraft modding
description: A Rosetta stone mapping Forge/Fabric/NeoForge concepts to their RSMM equivalents.
---

RSMM was deliberately shaped around the Minecraft modding mental model. If
you have written a Forge, Fabric, or NeoForge mod, most of what you know
transfers — only the words and the file formats change.

:::tip[The one big difference]
Minecraft mods ship **code** that runs inside a modded game. RSMM mods ship
**data** that RSMM bakes into the game's own cooked-asset files — no modded
runtime required for most content. Scripted behaviour is the exception, via
the optional loader DLL. See [Mods ship data, not code](/concepts/data-not-code/).
:::

## Rosetta table

| Minecraft modding | RSMM equivalent | Notes |
|---|---|---|
| `fabric.mod.json` / `mods.toml` | `manifest.toml` | Mod metadata + declared content. |
| Registries / `DeferredRegister` | [Content kinds](/concepts/content-kinds/) (`Mod.item`, `Mod.enemy`, …) | Register a definition cloned from a vanilla base. |
| Tags (`#minecraft:logs`) | [Tags](/concepts/tags/) (`Mod.tag`) | Cross-mod, append-only named groups. |
| Mappings (Yarn / MCP / Mojmap / SRG) | [Symbol map](/concepts/mappings/) (`data/symbols.json`) | Semantic names → engine functions/globals. |
| Access Transformers / Access Wideners | `callable` symbols (`engine::Name()`) | Exposes raw engine functions as typed calls. |
| Mixins (SpongePowered) | Loader DLL hooks + [event bus](/reference/symbols/) (`R.on`) | Runtime behaviour injection (MinHook + Lua). |
| Data generation (datagen) | SDK emitters (`engine/*_cook`) | RSMM materializes cooked bytes at `apply` time. |
| Data packs | Declarative `[[content]]` / `[[patch]]` | No code; merged by the applier. |
| Resource packs | Texture/asset overrides | Work **without** the loader DLL. |
| Lang files (`en_us.json`) | i18n (`lang/<locale>.toml`) | Merged into the game's text banks. |
| Mod loader (Fabric Loader / Forge) | RSMM + `winhttp.dll` loader | Asset mods need only RSMM; Lua needs the loader. |
| Game-version compat (`1.20.1`) | `target_game_build` + pattern resolver | Byte-pattern resolution survives game updates. |
| Inter-mod APIs (`@ApiStatus`, IMC) | `R.api.expose` / `R.api.require` | Version-gated published APIs. |

## How the analogies hold up

### Registries → content kinds

In Forge you `register` a new `Item` into a registry. In RSMM you clone a
vanilla **base** and register a new definition:

```python
import rsmm.sdk as sdk
m = sdk.Mod(id="RubyMod", name="Ruby Mod")
dagger = m.item("RubyDagger", base="Knife", name="Ruby Dagger")
m.commit()
```

Like a registry, each kind validates and de-dupes ids. Unlike Minecraft,
each kind carries a **confidence** (`confirmed` / `experimental` / `guess`)
because the byte format is reverse-engineered — see
[Content kinds](/concepts/content-kinds/).

### Mappings → the symbol map

Minecraft's obfuscated names are made readable by a mappings file. RSMM's
engine functions read as `FUN_140xxxxxxx` in a fresh disassembly;
`data/symbols.json` is the canonical map to semantic names, and — like a
*refmap* — it resolves by **byte pattern**, not fixed address, so names
survive game patches. See [Mappings](/concepts/mappings/).

### Mixins → loader hooks

Where you would write a Mixin, RSMM detours the function natively in the
loader DLL or subscribes to a generated event from Lua
(`R.on("<event>", cb)`). Both are opt-in and only load when the loader is
present.

## Where to go next

- [Your first mod](/getting-started/first-mod/) — the Minecraft "make a
  block" equivalent.
- [Authoring mods](/guides/modding/) — the full how-to.
- [Concepts](/concepts/content-kinds/) — the understanding-oriented pages.
