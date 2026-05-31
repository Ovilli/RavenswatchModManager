# Authoring mods with the Python SDK

Step-by-step guide to building a Ravenswatch mod with `rsmm.sdk`. The SDK is
the supported authoring path — you describe a mod in Python and it writes the
`mods/<id>/` tree for you. (Prefer this over hand-editing config/manifest
files.)

> Design reference: [`SDK_V3.md`](SDK_V3.md). Asset internals:
> [`INTERNALS.md`](INTERNALS.md). RE notes for content kinds:
> [`_re/kinds/`](_re/kinds/).

## 1. Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## 2. Your first mod

A mod is a `with sdk.Mod(...) as m:` block. Everything you call on `m`
accumulates in memory; the tree is written atomically when the block exits.

```python
# build.py
from rsmm import sdk

with sdk.Mod("FrostPack", version="1.0.0", author="you", name="Frost Pack") as m:
    m.i18n("EN", {"FrostPack_hello": "A chill wind blows."})
```

```bash
python build.py          # writes mods/FrostPack/
rsmm list                # see it registered
rsmm apply               # install into the game
```

## 3. Typed content + handles

`m.item / m.enemy / m.boss / m.map / m.hero` each clone a vanilla **base**
and return a `ContentRef` handle (like Forge's `RegistryObject`). Pass a
handle anywhere another content id is expected — it's resolved to the raw id
automatically.

```python
with sdk.Mod("FrostPack", version="1.0.0", author="you", name="Frost Pack") as m:
    blade = m.item("FrostBlade", base="Orb_Grants_Strength",
                   name="Frost Blade", rarity="legendary")
    m.enemy("FrostGhoul", base="Marsh_Ghoul", hp=200, is_elite=True)
    m.boss("IceLord", base="Baba_Yaga_Boss", drops=[blade])   # ref -> id
```

Don't know the valid `base` ids? List them:

```bash
rsmm schema                 # counts per kind
rsmm schema item --grep Orb # filter
rsmm schema hero            # every hero base id
```

> Heads-up: some content kinds aren't fully reverse-engineered yet and will
> raise `SchemaNotMined` on `apply` with a pointer to the RE work needed.
> Items + enemies are the most complete. See [`_re/kinds/`](_re/kinds/).

## 4. Tags — cross-mod groups

Tags group content into named, **append-across-mods** sets (à la Minecraft
`#namespace:path`). Pass handles or raw ids:

```python
m.tag("daggers", [blade, "VanillaKnife"])
m.tag("daggers", another_dagger)   # same tag id -> appends (deduped)
```

Tags land in `mods/<id>/tags.json`; the loader exposes them to Lua at runtime
as `rsmm.tags()` so gameplay scripts can read them.

## 5. Assets — textures, models, skins

```python
m.texture("3D/Characters/Heroes/Melusine/Textures/T_Melusine_ALB.png",
          "art/my_melusine_albedo.png")          # PNG/DDS/TGA, auto-cooked
m.model("3D/Characters/Heroes/Juliet/Juliet_GEO.fbx.glb",
        "art/low_poly_juliet.glb", rotate_deg=(90, 0, 0))
m.skinpack("Crimson Pack", key=0x900001,         # new selectable skin slot
           ac_id="RW000PSAC000000A", al_id="RW000PSAL000000A")
```

Decoded asset paths come from `data/asset_map.json` (`rsmm decode` /
`rsmm uncook` help you find them). Skins: see [`_re/kinds/skins.md`](_re/kinds/skins.md).

## 6. Config + i18n

```python
m.config({"fields": {"frost_damage": {"type": "float", "default": 1.5}}})
m.i18n("EN", {"FrostBlade_desc": "Freezes on hit."})
m.i18n("FR", {"FrostBlade_desc": "Gèle à l'impact."})
```

## 7. Test it offline (no game needed)

`rsmm.sdk.testkit` asserts over a mod's staged state without applying it.

```python
# test_frostpack.py
from rsmm import sdk
from rsmm.sdk.testkit import expect, assert_no_conflicts

def build():
    m = sdk.builder.ModBuilder("FrostPack", version="1.0.0",
                               author="you", name="Frost Pack")
    blade = m.item("FrostBlade", base="Orb_Grants_Strength", name="Frost Blade")
    m.tag("daggers", [blade])
    m.i18n("EN", {"FrostBlade_desc": "Freezes."})
    return m

def test_frostpack():
    m = build()
    (expect(m)
        .has_item("FrostBlade")
        .has_tag("daggers", "FrostBlade")
        .field_equals("item", "FrostBlade", "name", "Frost Blade")
        .i18n_complete()       # every key present in every locale
        .clean())              # no validate() warnings

def test_no_clashes():
    assert_no_conflicts(build())   # safe to ship alongside itself
```

```bash
pytest test_frostpack.py
```

`m.summary()` returns a dict of everything staged (content, assets, tags,
i18n, skinpacks, deps) — handy to `print()` while iterating.

## 8. Lua runtime hooks (optional)

Code that runs *in-game* lives in `mods/<id>/init.lua` and reacts to events:

```lua
local R = require "rsmm"
R.events.on("setup", function() R.log("FrostPack loaded") end)
R.events.on("level_up", function(p) R.log("level up!") end)  -- opt-in event
local tags = R.tags()                                        -- your tags.json
```

Lifecycle: `setup` → `ready` → `tick`*. Gameplay events (`level_up`,
`run_end`) require `RSMM_ENABLE_GAME_EVENTS=1` — see
[`_re/kinds/events.md`](_re/kinds/events.md).

## 9. Package + distribute

```bash
rsmm pack FrostPack            # -> dist/FrostPack.zip (refuses vanilla bytes)
rsmm keygen mykey              # optional Ed25519 signing
rsmm sign dist/FrostPack.zip --key mykey
```

Publish a `repo.json` (see [`MODDING.md`](MODDING.md) + `rsmm.sdk.repo`)
pointing at the zip + its sha256. Users install with:

```bash
rsmm repo add https://example.com/repo.json
rsmm install FrostPack                 # resolves, verifies, unpacks
rsmm install https://x/FrostPack.zip   # or a direct archive
```

## Quick reference

| Goal | Call / command |
|------|----------------|
| New content (handle) | `m.item/enemy/boss/map/hero(id, base=…)` |
| Find base ids | `rsmm schema [kind] [--grep T]` |
| Group content | `m.tag(id, [refs…])` |
| Override asset | `m.texture/model/asset(decoded, src)` |
| New skin slot | `m.skinpack(name, key=…)` |
| Config / strings | `m.config({...})` / `m.i18n(loc, {...})` |
| Preview staged state | `m.summary()` |
| Offline assertions | `from rsmm.sdk.testkit import expect, assert_no_conflicts` |
| Build / inspect / apply | `python build.py` · `rsmm list` · `rsmm apply` |
| Package / install | `rsmm pack <id>` · `rsmm install <id\|url>` |
| Auto-API docs | `rsmm docs-gen` → `docs/api/` |
