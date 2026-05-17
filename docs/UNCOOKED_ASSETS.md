# Uncooked asset mirror

`data/uncooked/` is a human-readable view of every cooked asset
Ravenswatch ships. Generated locally, **never committed**, intended
solely as a development reference so modders can see what they're
overriding before they override it.

## What's in there

```
data/uncooked/
    3D/                  characters, scenery, animations
    Audio/               FMOD banksets
    Definitions/         enemies, items, modes, modifiers, achievements
    EntitySettings/      cooked entity property bodies
    Heroes/              hero-specific assets
    Materials/           shader / material defs
    Maps/                level definitions
    Text/                localization GAM XLS dumps
    Ui/                  UI sprites, portraits, menus
    _root/
        DarkTalesResources/
            ApplicationSettings.ot   verbatim copy
            EngineSettings.ini       verbatim copy
            UsedRscList.ot           verbatim copy
    ... ~20 more top-level dirs
```

Totals after a full run on the current build:

| Bucket | Count | Notes |
|---|---|---|
| `.png` (decoded textures) | 4,776 | BC1, BC3, BC5, RGBA8, font atlases |
| `.gen` (cooked binary)    | 15,431 | engine-native, body schemas in `Ravenswatch.exe` |
| `.gen.txt` (sidecar)      | 15,362 | structural dump per .gen (class table + section ranges + embedded strings) |
| `.dxil`                   | 116    | compiled HLSL — no decompiler in repo |
| `.fnb`                    | 6      | proprietary font binary |
| `.ot`                     | 2      | plain oCTextSaver text |
| Root files                | misc   | settings + manifests |
| **Total**                 | **35,696** files, **3.2 GB** |

## How it's built

Two scripts, both idempotent:

```sh
# 1. extract cooked → readable (decodes .tpi/.zux/.nrm textures to PNG,
#    copies the rest raw).
python3 scripts/extract_uncooked.py

# 2. for each .gen file, dump structural decode as a sibling .gen.txt
python3 scripts/decode_gen_sidecars.py
```

Re-run both after a game update. Both walk `data/asset_map.csv` (encoded
↔ decoded path index), so they pick up new assets automatically once
`./rsmm rebuild-asset-map` regenerates the map.

### Texture decoder

`extract_uncooked.py` parses the `oCTexture` (.tpi) / `oCTextureNorm`
(.zux) container header to find width, height, format, and the
pixel-data offset:

```
ff ff ff ff                         end of class table
22 22 bb aa 11 11 bb aa 00 00 00 00 sentinel 1
22 22 bb aa 11 11 bb aa 00 00 00 00 sentinel 2
<extra_mip_count: u32>
<width: u32>
<height: u32>
<unk: u32>
<format: u32>      ← 0=BGRA8, 4=BC1, 5=BC3, 35=BC5 (ATI2)
<mip0_size: u32>
<mip0_size: u32>   duplicate
<pixel data: mip0_size bytes>
[<mip1, mip2, ... if extra_mip_count > 0>]
```

Format 35 is BC5 normal data — only X,Y stored, the script reconstructs
Z = sqrt(1 − X² − Y²) so the saved PNG looks like a real normal map.

### Structural sidecars

`decode_gen_sidecars.py` invokes the existing `rsmm.engine.ot_decoder`
(see `docs/INTERNALS.md` — same module that powers `./rsmm decode`).
For each `.gen` it writes a `.gen.txt` containing:

- header (`//OPROJECT oCTextSaver`, flags, hdr_size)
- class table (every class name + class ID + version)
- section ranges (offset + length)
- every embedded string inside each section

Per-class property bodies stay opaque — the schemas live inside
`Ravenswatch.exe` (`docs/INTERNALS.md` §schema). The sidecars are still
enough to identify *what* each cooked file references (which texture,
which material, which shader, which donor file).

The 69 `*LocalText.gen` files fail decode — they don't use the standard
oCTextSaver class header. Tracked as a follow-up.

## Why it's gitignored

`data/uncooked/` is git-ignored. Two reasons:

1. **Size** — 3.2 GB. Each contributor regenerates it locally.
2. **Copyright** — these are Ravenswatch's own assets in readable form.
   Distributing them is redistribution of game content, not modding.

The same logic applies inside mods. `rsmm pack <id>` SHA1s every file
in `mods/<id>/assets/` and `_root/` against the original cooked asset
(and the `data/uncooked/` mirror). Byte-identical files cause pack to
refuse:

```
$ ./rsmm pack MyMod
refusing to pack MyMod: contains files byte-identical to original game assets ...
  assets/Ui/BookMenu/Heroes/UI_HeroPortrait_Romeo_Active.png.Texture.dxt
        (matches original cooked asset)
```

Override with `--allow-vanilla` for personal backups only.

## How modders use the mirror

1. **Find what to override** — grep the tree to discover decoded
   paths.
   ```sh
   find data/uncooked/Ui -name "*Portrait*"
   ```
2. **See what's already there** — open the PNG in any image viewer,
   or read the `.gen.txt` sidecar to see which donor files / shaders
   the asset references.
3. **Author the override** in `mods/<id>/assets/<same/decoded/path>`,
   using either a raw byte replacement or a `[[patch]]` block in
   `manifest.toml` (see `docs/MODDING.md`).
4. **Verify** — `./rsmm apply` swaps the cooked file in place;
   `./rsmm pack <id>` ships only changed bytes.
