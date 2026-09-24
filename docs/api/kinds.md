# Content kinds & confidence

Every content kind carries an honesty rating — how much the bytes it emits are trusted. This page is generated from `rsmm.sdk.content.KIND_CONFIDENCE`, which is what the SDK and `rsmm lint` actually enforce, so it cannot drift from the code.

:::note
Do not edit by hand, and do not restate a rating in prose — link here. Run `rsmm docs-gen` after changing a rating; CI `--check`s it.
:::

**15 kinds** — 12 confirmed, 2 experimental, 1 guess.

| Kind | Confidence | Builder | What it does |
|---|---|---|---|
| `item` | ✅ confirmed | `rsmm.sdk.kinds.items` | Item (magical-object) content builder. |
| `enemy` | ✅ confirmed | `rsmm.sdk.kinds.enemies` | Enemy content builder — two modes. |
| `boss` | ✅ confirmed | `rsmm.sdk.kinds.bosses` | Boss content builder — make a boss arena fight a different boss. |
| `map` | ⚠️ experimental | `rsmm.sdk.kinds.maps` | Map (biome) content builder: clone a shipped mapdef and point a chapter at it. |
| `hero` | ✅ confirmed | `rsmm.sdk.kinds.heros` | Hero content builder: clone a shipped hero into a new roster entry. |
| `talent` | ✅ confirmed | `rsmm.sdk.kinds.talents` | Talent (in-game "Skill") value content builder. |
| `skill` | ✅ confirmed | `rsmm.sdk.kinds.skills` | Hero **skill** (talent) content builder. |
| `modifier` | ⚠️ experimental | `rsmm.sdk.kinds.modifiers` | Custom **game modifier** ("negative mode") content builder. |
| `game_mode` | ✅ confirmed | `rsmm.sdk.kinds.game_modes` | Custom **game mode** (run chapter sequence) builder. |
| `reward` | ✅ confirmed | `rsmm.sdk.kinds.rewards` | **Reward placement** editor — ban/tune what spawns at reward points. |
| `melody` | ❓ guess | `rsmm.sdk.kinds.melodies` | **Melody** editor — retune the Piper's lost-melody definitions. |
| `poi` | ✅ confirmed | `rsmm.sdk.kinds.poi` | **POI / structure** builder — put a point of interest into any chapter. |
| `mesh` | ✅ confirmed | `rsmm.sdk.kinds.meshes` | **Mesh** content builder — put the mod's model in place of a shipped one. |
| `tilegen` | ✅ confirmed | `rsmm.sdk.kinds.tilegen` | Chapter map-generation recipe content builder. |
| `shop` | ✅ confirmed | `rsmm.sdk.kinds.shops` | **Shop** editor — change what the Sandman sells and what it costs. |

## What a rating means

| Rating | Meaning | To ship it |
|---|---|---|
| ✅ `confirmed` | The emitted bytes were verified in-game, end to end. | Nothing extra. |
| ⚠️ `experimental` | Codecs round-trip and the emit succeeds, but the in-game path is unproven. | `sdk.Mod(..., experimental=True)` / `experimental = true`. |
| ❓ `guess` | The byte layout is an educated guess. May be rejected, may crash. | Same opt-in, plus your own testing. |

A mod that registers any non-`confirmed` kind must opt in, and its manifest records it — so nobody ships speculative content believing it works. `rsmm lint` fails the mod otherwise.

The *reason* behind each rating — what was proven, when, and what the rating is still waiting on — is written beside the rating in `src/rsmm/sdk/content.py`. Start there before changing one.

## Starting one

[First mod, by kind](/guides/first-mod-by-kind/) has a minimal, working `manifest.toml` for every row above.
