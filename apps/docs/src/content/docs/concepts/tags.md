---
title: Tags
description: Cross-mod, append-only named groups — the Minecraft #namespace:path analog.
---

A **tag** is a named, cross-mod-extensible group of content — directly modeled
on Minecraft's `#namespace:path` tags (e.g. `#minecraft:logs`). Several mods,
or several call sites, can grow the same tag.

```python
import rsmm.sdk as sdk
m = sdk.Mod(id="Blades", name="Blades")
dagger = m.item("RubyDagger", base="Knife")
m.tag("daggers", [dagger, "VanillaKnife"])
m.commit()
```

## How they behave

- **Append, not replace.** Calling `tag()` again with the same id adds to it
  (de-duped, order preserved). Mod B can extend a tag Mod A created.
- **Members are ids.** Pass id strings or the handles returned by
  `item()`/`enemy()`/… directly — they deref to raw ids.
- **Stored as data.** Tags are written to `mods/<id>/tags.json`; downstream
  tooling and mods aggregate them across all enabled mods (same model as
  `skinpacks.json`).

:::tip[Minecraft analogy]
Exactly like data-pack tags: `#c:ingots` is grown by every mod that adds an
ingot. RSMM tags are the same contract, expressed in the SDK.
:::

## Common problems

:::caution
- **My tag is missing a member from another mod.** Aggregation only includes
  **enabled** mods — check the other mod is applied.
- **Order matters for me, but it changed.** Order is insertion order across
  mods; don't rely on it for correctness, only for display.
:::

See the generated [`Mod.tag` reference](/reference/sdk-api/builder/) for the
exact signature.
