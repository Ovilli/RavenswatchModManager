---
title: Content kinds (registries)
description: How RSMM registers new content by cloning vanilla bases — the Minecraft registry analog.
---

A **content kind** is a typed builder that clones a vanilla **base** and emits
a new definition. This is RSMM's analog of a Minecraft registry: you don't
hand-author engine bytes, you declare *"a new item like `Knife`"* and the SDK
materializes it.

```python
import rsmm.sdk as sdk
m = sdk.Mod(id="RubyMod", name="Ruby Mod")
m.item("RubyDagger", base="Knife", name="Ruby Dagger")
m.enemy("FastRat", base="Rat", name="Fast Rat")
m.commit()
```

Available kinds include `item`, `enemy`, `boss`, `hero`, `map`, plus the
asset kinds `texture` and `model`, and the grouping kind `tag`. The full,
current list and signatures are in the generated
[SDK reference](/reference/sdk-api/builder/).

## Confidence — the RSMM twist

Minecraft registries always work; RSMM kinds describe a **reverse-engineered**
byte format, so each kind carries a confidence:

| Confidence | Meaning | Requirement |
|---|---|---|
| `confirmed` | Emitted bytes verified in-game | usable directly |
| `experimental` | Plausible, not fully verified | needs `Mod(..., experimental=True)` |
| `guess` | Schema partially understood | needs `experimental=True`; may crash |

`rsmm lint` enforces the opt-in gate, so you can't accidentally ship a `guess`
kind without acknowledging the risk.

:::tip[Minecraft analogy]
`m.item(base="Knife")` ≈ `DeferredRegister` registering an item that copies an
existing one's properties. The `base` is the vanilla prototype; `**fields`
override specific values. See [Coming from Minecraft](/concepts/from-minecraft/).
:::

## Common problems

:::caution
- **`kind 'x' is 'experimental'` error.** Add `experimental=True` to your
  `Mod(...)` — and expect to test in-game.
- **New content doesn't appear in-game.** Most kinds also need engine-side
  registration (e.g. a versiondef / UsedRscList entry). The applier handles
  the confirmed pipelines; experimental kinds may not be wired end-to-end.
- **Unknown base.** The `base` must name a real vanilla definition. Browse
  candidates with the relevant `rsmm` listing command.
:::

## Related

- [Tags](/concepts/tags/) — group content across mods.
- [Mods ship data, not code](/concepts/data-not-code/) — why this is declarative.
- [Authoring mods](/guides/modding/) — the full how-to.
