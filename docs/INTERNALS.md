# Ravenswatch — Internals / RE notes

> **Historical log.** This file is a reverse-engineering record. Where
> it references `tools/<script>.py`, the current location is
> `src/rsmm/cli/<script>.py` or `src/rsmm/engine/<script>.py`; the
> CLI surface is `./rsmm <name>`. See [SETUP.md](SETUP.md) for the
> current repo layout.
>
> **Companion docs (newer).** This file covers the asset pipeline +
> cipher + cooked-file format. For the binary RE that backs
> `rsmm.call`, see:
>
> - `docs/_re/PIPELINE.md` — Ghidra setup, scripts, regen workflow.
> - `docs/_re/CALLING_GAME_FUNCTIONS.md` — runtime Lua API.
> - `docs/_re/SEED_MAPGEN.md` — worked example.
> - `docs/UNCOOKED_ASSETS.md` — `data/uncooked/` extract + texture
>   container details.

## Overview

This document consolidates observations from the DarkTalesResources directory in Ravenswatch, in a Steam + Proton environment. The structure points to a cooked, indexed, and heavily obfuscated asset pipeline, similar to Unreal Engine cooked content or a proprietary equivalent.

## Root Structure

Main directory:

```text
/home/ovilli/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/Ravenswatch
```

Key components:

- `_Cooking/`
- `UsedRscList.ot`

### `_Cooking/`

- Contains processed runtime assets
- Deep nested folders with obfuscated names
- Represents final cooked game data

### `UsedRscList.ot`

- Central resource index / manifest
- Maps logical IDs to actual asset files
- Core lookup table for runtime loading

## File Types

- `.tpi` - Final packaged asset
- `.tpdl` - Bundled/cooked resource container
- `.yqz` - Compressed or encoded payload
- `.jzy` - Intermediate cooked asset
- `.rvl` - Variant layer / resource variant

These appear to be engine-specific formats.

## Naming and Obfuscation

Examples:

```text
Qqpiwuq
vngtquv
UTS_Fgztxgz
Ni_Qqpiwuqt_Sngugbiquv
Qdlqv!6p6_Susvigl_01
```

Characteristics:

- Pseudo-random consonant-heavy strings
- No semantic meaning preserved
- Consistent structured naming
- Prefix grouping such as `UTS_`, `Ni_`, and `Qdlqv!`

## Encoding Behavior

Example:

```text
UTS_Fgztxgz~KWH.plv.GrbglQqpi.yqz
```

Breakdown:

- `UTS_` - category or group
- `Fgztxgz` - base identifier
- `KWH` - variant tag
- `.plv` / `.yqz` - container layers

This likely reflects a substitution or hash-based naming system.

## Variant System

Examples:

```text
Qdlqv!6p6_Susvigl_01
Qdlqv!3p3_Blrbmqu_Turjv_01
```

Interpretation:

- Quality tiers or build configurations
- Platform or gameplay variants
- Procedural asset duplication system

The same base asset appears in multiple variants.

### Variant Flags

Resolution / build splits seen in the data:

- `6p6`
- `3p3`

These consistently appear in:

- Qdlqv asset groups
- NgumAdllv pipeline outputs
- Srxjrvdidrzv bundles

Likely meaning:

- Different quality tiers
- Different platform scaling sets
- Or level-of-detail buckets

## Asset Pipeline

```text
Raw Assets
   ↓
_Cooking (preprocessing stage)
   ↓
.tpdl bundles
   ↓
.tpi final assets
   ↓
UsedRscList.ot index
   ↓
Runtime loader resolves assets
```

## Resource Index

`UsedRscList.ot` appears to serve as the main lookup layer.

Role:

- Maps logical identifiers to physical files
- Prevents direct filesystem scanning
- Acts as the core runtime lookup system

Evidence:

- No readable paths in the executable
- Assets are only resolved through the cooked system

## Frequency Analysis

From extracted filenames, the most frequent base tokens were:

- `01` - 3302
- `Aqurqv` - 3227
- `Aqur` - 2562
- `Wkglrz` - 2480
- `Mzqxdqv` - 2346
- `NgumAdllv` - 2238
- `FbqzqusOacqbiv` - 2046
- `VZ` - 2045
- `Wzdxgidrzv` - 1990
- `Qqpiwuqv` - 1507
- `Srxxrz` - 1267
- `Firux` - 1091
- `Hquldz` - 1048
- `KWH` - 996

## Asset Group Behavior

Example grouping pattern:

```text
Qdlqv!6p6_Susvigl_01
Qdlqv!6p6_Blrbmqu_01
Qdlqv!3p3_Blrbmqu_01
```

This suggests:

- Same asset family
- Multiple configuration outputs
- Shared base asset name plus variant suffix

## Pipeline Structure Identified

The system appears layered:

- Engine / Runtime Layer
  - Tokens: `Cooking`, `Qqpiwuq`, `tpi`, `jzy`
  - Role: pipeline and runtime orchestration, likely a noise layer in the analysis

- Asset Namespace Core
  - Tokens: `MzidisFqiidzyv`, `qzidis`, `NgumAdllv`
  - Role: root asset generation system

- Gameplay / System Modules
  - Tokens: `Sngugbiquv`, `Wzdxgidrz`, `Mzqxdqv`, `3N`
  - Role: gameplay mechanics and logic systems

- Entity / Content System
  - Tokens: `Fqiidzyv`, `Hgiqudgl`, `VZ`, `01`
  - Role: entity definitions and content registry

- Feature / Specialized Subsystems
  - Tokens: `KWH`, `GrbglQqpi`, `KlraglMzidisDglwqFqiidzyv`
  - Role: isolated feature modules or rendering/UI systems

- Container / File Format Layer
  - Tokens: `tpdl`, `rvl`, `vngtquv`, `Fngtqu2`, `Ni`
  - Role: packaged asset formats and compiled containers

## Key Structural Insight

The asset system is not random obfuscation. It appears to be a deterministic hierarchical naming system:

```text
Root Namespace -> Variant Expansion -> Subsystems -> Containers
```

## Observations

### Strong signals of:

- Packed / cooked asset system
- Deterministic naming obfuscation
- Multi-tier asset generation for performance scaling
- Platform-specific compiled bundles

### Weak signals, not confirmed:

- Unreal Engine-style cooking pipeline
- Compression and symbol mangling
- Resource manifest-driven loading system

## Index Summary

Main system:

- Base assets -> obfuscated tokens
- Variants -> `6p6 / 3p3`
- Build tags -> `KWH`
- Pipeline outputs -> `.plv / .rvl / .tpdl`

## Additional Examples

```text
AssetName~KWH.plv.GrbglQqpi.yqz
AssetName.yugjn.rvl.Fngtqu2.tpdl
```

Interpretation:

- `~KWH` - variant tag, likely platform or build config
- `.plv / .rvl / .tpdl` - cooked asset formats
- `GrbglQqpi / Fngtqu2` - intermediate compiled asset bundles
- `_Cooking` - build pipeline output directory

## Summary

This looks like a fully cooked and indexed game asset system with:

- Obfuscated identifiers
- Variant-based duplication system
- Centralized manifest indexing
- Runtime-only resolution

File names are not meaningful without decoding the index layer.

## Next Steps

1. Parse `UsedRscList.ot` into a mapping table
2. Classify file formats (`.tpdl`, `.tpi`, `.yqz`)
3. Inspect headers for compression signatures
4. Compare repeated prefixes for decoding patterns
5. Build an asset-to-file reconstruction script

## oCTextSaver — engine serialization format (CONFIRMED 2026-05-14)

The engine ships data in **two** forms:

* **Uncooked text** — `.ot` files starting with `//OPROJECT oCTextSaver`.
  Plain ASCII. Self-describing. Game ships at least
  `DarkTalesResources/ApplicationSettings.ot` in this form and loads it
  directly (no cooking). Format:

```
//OPROJECT oCTextSaver
//V1.16
//FLAGS=0
*Classes=N
*Class0=ClassName[class_id](v_major.v_minor)<[parent_class_id]
...
*Objects=M
*SingleObject0=Cidx           <- root object references
...
SingleObject0=C0              <- actual data, by class index
{
    plain_field=value
    typed_field|name=value    <- type prefix: b=bool, i=int, u=uint, f=float
    nested_obj=Cidx           <- nested instance reference
    {
        ...nested data block...
    }
}
```

* **Cooked binary** — `.gen` files (decoded extension; on disk encoded
  via the substitution cipher) under `DarkTalesResources/_Cooking/`.
  Same logical data, packed binary. Layout reverse-engineered so far:

```
[0x00] u32    header_field_0    = 0x10
[0x04] u32    flags             = 0x01
[0x08] str4   "Cooked"          (length-prefixed)
[..]   u32    extra             = 0x01
[..]   u8     tag               = 0x31
[..]   u32    magic             = 0xAABB1111
[..]   u32    class_count
[..]   N * { u32 name_len; bytes name; u32 class_id; u32 v_major; u32 v_minor; u32 parent_id }
[..]   --- object table + property streams (NOT YET DECODED) ---
```

Section markers seen later in stream: `0xAABB1111` and `0xAABB2222`.
Strings inside the data segment are length-prefixed too (e.g. property
values that are strings).

### Decoder

`tools/ot_decoder.py` parses the header + class table. Confirmed working
against `MzidisFqiidzyv/Xziqugbidkq_Srxxrz/Grbgl_Xziqugbidkq_Oacqbi_Hrtql.qzidis.ri.MzidisFqiidzyvLqvrwubq.yqz`
— produces a valid `*ClassN=...` table identical in spirit to the text
form. Class IDs and parent IDs cross-reference correctly.

### Asset extension chains

Cipher tables in `find_iyg.py` finalized 2026-05-14 (fixed bad mappings on
`y`, `Z`, etc). Re-decoded `asset_map.json` now produces clean filenames
end-to-end. Extension counts (top 20):

```
5064  .fbx                                          (raw mesh source)
4373  .entity.ot                                    entity definitions
4373  .entity.ot.EntitySettingsResource.gen         cooked counterpart
2837  .fbx.Geometry.gen
2679  .mat.ot                                       materials
2679  .mat.ot.Material.gen                          cooked counterpart
2661  .png
2654  .png.Texture.dxt
2229  .vfx.ot                                       VFX defs
2229  .vfx.ot.ScheduledVfxSettings.gen              cooked counterpart
2216  .fbx.Animation.gen
2058  .tga
1511  .tga.Texture.dxt
 544  .tga.Texture.nrm
 357  .level.ot                                     level defs
 357  .level.ot.GameStream.gen
 210  .tiledef.ot                                   tile defs
 210  .tiledef.ot.DtTileDefinition.gen
 204  .globalvalue.ot                               global values
 204  .globalvalue.ot.GlobalEntityValueSettings.gen
```

Key pattern: every `*.ot` source has a paired `*.ot.<KindResource>.gen`
cooked output. Means engine knows both forms exist; cooked form is the
*output* of cooking the text source.

The dominance of `.ot` suffixes means the game is fully data-driven from
oCTextSaver files. Modifying any of them gives us native gameplay
control, including UI / menus.

### Main menu asset locations

Decoded asset map points to:

```
encoded:  KgxqJdv\HgdzHqzw.lqkql.ri
decoded:  GameUis\MainMenu.level.ot                (text source, may not ship)

encoded:  Oi\KgxqJdv\HgdzHqzw.lqkql.ri.KgxqFiuqgx.yqz
decoded:  Ot\GameUis\MainMenu.level.ot.GameStream.gen   (cooked binary, ships)
```

The encoded layout uses Windows backslashes; engine loads via
`DarkTalesResources/_Cooking/<encoded-path>` (UsedRscList.ot only lists
encoded names).

### Probe plan — does the engine read uncooked .ot at runtime?

We know `ApplicationSettings.ot` is loaded uncooked (it ships as plain text).
Open question: is that special-cased, or does every `.ot` source get probed
before the engine falls back to the cooked `.gen`?

Step 1 — passive trace via Proton's own logging (no wrapper script;
pressure-vessel strips env from wrappers, so vars must be in launch
options directly):

  Steam Launch Options:
      WINEDLLOVERRIDES="winhttp=n,b" PROTON_LOG=1 WINEDEBUG=+file %command%

  Run game to main menu, quit. Log lands at:
      ~/.var/app/com.valvesoftware.Steam/steam-2071280.log

  Parse with:
      tools/trace_parse.py        # default path baked in

### Probe result (2026-05-14): Outcome B — cooked-only

One launch + main-menu + quit produced 203k log lines. Parser output:

  * 53,892 file opens under `DarkTalesResources/_Cooking/` (encoded names)
  * 85 opens outside `_Cooking/` — all to *named config files*:
        ApplicationSettings.ot     (uncooked oCTextSaver text — editable!)
        EngineSettings.ini
        UsedRscList.ot
        oFMod.ini
        Input/PadHid*.ini
        Ui/Ravenswatch_Cursor.cur

There are **zero** probes for uncooked `.ot` anywhere in the asset tree.
ApplicationSettings.ot is a one-off, special-cased config file the engine
reads at startup. The asset pipeline at runtime is cooked-only: every
asset is loaded by its *encoded* name under `_Cooking/` as binary `.gen`
(or `.tpi`, `.dxt`, `.bank`, etc).

Implication: to override any asset (including MainMenu), we must produce
a binary cooked file at the matching encoded path. Path forward:

  1. Finish object/property parser in `tools/ot_decoder.py`
  2. Build a re-encoder: text `.ot` → binary `.gen`
  3. Backup + replace the target cooked file at its encoded path

### Override mechanism — CONFIRMED 2026-05-14

End-to-end override of a cooked asset works with **no engine hook,
binary edit, or re-encoder**. Procedure that succeeded:

  1. Took two cooked Texture.dxt files in the same encoded directory:
     - target  = `_Cooking/Jd/BrrmHqzw/Aqurqv!JX_AqurTruiugdi_Lrxqr_Wbidkq.jzy.Qqpiwuq.tpi`
                 (decoded: `Ui/BookMenu/Heroes/UI_HeroPortrait_Romeo_Active.png.Texture.dxt`)
     - donor   = same dir, `Aqurqv!JX_AqurTruiugdi_FwzRwmrzy_Wbidkq.jzy.Qqpiwuq.tpi`
                 (SunWukong Active)
  2. Backed up target, copied donor's bytes onto target's path.
  3. Launched the game. Hovering Romeo in the hero-select screen showed
     SunWukong's portrait instead of Romeo's.

Implications:

- Mods at this layer are *file-replacement packages*. A mod just
  ships cooked `.gen` / `.tpi` files; loader symlinks or copies them
  onto the encoded paths under `_Cooking/`.
- No need to defeat anti-tamper for asset overrides — the engine itself
  loads them through the normal cooked-asset pipeline.
- We do *not* need the full text->binary re-encoder to ship a v1 mod
  manager. v1 = asset overrides. v2 = entity-level menu mods requiring
  the encoder.

Failed first attempt is also worth recording: we initially swapped
`Ui/Heroes/Romeo/Portrait_Romeo_01.png.Texture.dxt` and saw no change
in-game. That file is referenced from somewhere else (probably the
encounter / pause card UI), not from the main hero-select tile. The
hero-select uses the `Ui/BookMenu/Heroes/UI_HeroPortrait_<hero>_Active`
set. Lesson: hero-select tiles live under `BookMenu`, not `Heroes`.

### Mod manager v1 — `tools/apply_mods.py`

Because cooked overrides are accepted by the engine without any runtime
hook (see above), the v1 mod manager doesn't need the DLL, the IO hook,
or the Vulkan layer. It is a single Python script:

  tools/apply_mods.py              # apply current mods/ state
  tools/apply_mods.py --restore-all
  tools/apply_mods.py --list
  tools/apply_mods.py --dry-run

A mod is a directory under `mods/<ModId>/`:

  mods/<ModId>/
    manifest.toml          # id/name/version/author/enabled
    assets/<decoded-path>  # mirrors the human-readable decoded path

The script:

  1. Walks `mods/`, parses each manifest, collects override files.
  2. Resolves each decoded path -> encoded path via `asset_map.json`.
  3. Diffs against `<install>/DarkTalesResources/_Cooking/.rsmm_state.json`.
  4. For each newly-active override:
       - back up original cooked file to `<file>.rsmm.bak` (once)
       - copy mod file onto the encoded path
  5. For each no-longer-active override: move `.rsmm.bak` back.
  6. Writes new state file (sha1 of mod file + original).

Verified end-to-end with `mods/ExampleMod/` shipping Romeo's
`UI_HeroPortrait_Romeo_Active.png.Texture.dxt` replaced by SunWukong's.

### ApplicationSettings.ot — high-value tweakables

`DarkTalesResources/ApplicationSettings.ot` is plain-text oCTextSaver
loaded uncooked. Beyond game-balance fields, it contains:

- **External URLs** at lines 6668-6671. Editing them re-targets the
  main-menu button actions:

  ```
  m_sDiscordUrl     = https://discord.gg/passtechgames
  m_sPatchNoteUrl   = https://www.passtechgames.com/ravenswatch-year-1
  m_sBugReportsUrl  = https://my.nacongaming.com/support/game/ravenswatch
  m_sNewUpdateUrl   = https://store.steampowered.com/dlc/2071280/
  ```

  Combined with the text-bank relabel of `Common~EN:Menu_Discord` ->
  "Mods (RSMM)", this is enough to turn the Discord button into a real
  mod-manager entry point that opens an arbitrary URL (a GitHub repo, a
  locally-hosted mod-list HTML page, etc).

- **Cheats UI layer** at line 5573 (`Vector[13] = oCGameUiLayerDesc` with
  `m_sName=Cheats`, `m_iPriority=100`). The engine *registers* a Cheats
  UI layer; we don't yet know how to *show* it (likely gated by a hard
  check in `Ravenswatch.exe`, possibly a debug build flag or hotkey
  binding). Worth investigating: the layer's hash-ID 4-tuple
  (2586023665, 1153599675, 3382377381, 3432447172) may correlate with a
  runtime call site.

- **UI layer roster** (in order): Ground, Empty, LifeBar, InGame,
  Sandman, HUD, InGame menus, Book menus, Video, Loading, Fade In/Out,
  System messages, Now Saving, Watermarks, **Cheats**, Child, Woman, Man,
  Old Woman, Old Man, Corpse, Hero_Common.

### Adjacent attack surfaces (already editable, no encoder needed)

  * **`ApplicationSettings.ot`** — plain-text oCTextSaver, loaded
    uncooked. Contains: `oCGameUiApplicationSettingsSection`,
    `oCFlagsApplicationSettingsSection`, modifier sections, NG+ rules,
    bark configuration. Flipping flags or adding UI layer descriptors
    here is the cheapest mod hook the game offers.
  * **`EngineSettings.ini`** — top-level engine config. Likely contains
    renderer/loader flags. Worth scanning for path-redirect or
    mod-friendly options.
  * **`UsedRscList.ot`** — the manifest. Adding entries (encoded names)
    may make the engine accept *new* cooked files that don't exist in
    the shipped manifest. Untested but plausible.

  Outcome A: log contains opens of paths ending `.ot` outside `_Cooking/`
      -> engine probes for uncooked override. We can drop modded `.ot`
         files at those paths and skip the re-encoder entirely.

  Outcome B: log only shows opens inside `_Cooking/` for encoded names
      -> engine is cooked-only. Path forward is text `.ot` -> binary `.gen`
         re-encoder + replace the cooked file (with backup).

### Path to in-game native UI

Once probe outcome is known:

1. (If outcome B) Finish object/property parser in `ot_decoder.py`, then
   build the re-encoder (text `.ot` -> binary `.gen`).
2. Pull the MainMenu level — its cooked asset is at
   `DarkTalesResources/_Cooking/Oi/KgxqJdv/HgdzHqzw.lqkql.ri.KgxqFiuqgx.yqz`.
3. Inject a "Mods" button entity that references existing widget classes
   already used by the menu.
4. Wire the button: either (a) the button triggers an existing engine
   event we hijack from our `winhttp.dll` loader, or (b) we add new
   entity nodes that drive a native widget tree for the mod list.

## Class survey (2026-05-14)

`tools/class_survey.py` walks every `.yqz` in `_Cooking/` and buckets by
root class name. Counts + body-size spread highlight the easiest classes
to reverse-engineer (uniform body size = fixed-layout schema, no
length-prefixed strings).

Top of the table (24 distinct root classes total):

```
cls                                                count   min    max  uniform
oCDtEnemyCampDifficultyDefinition                      6    18     18  *
GameModeDefaultDefinition                              1    30     30  *
VersionDefinition                                      1 13303  13303  *
oCEntitySettingsResource                            4384    45   5150
oCGeometry                                          2842   200 4305425
oCMaterial                                          2686   159    364
oCScheduledVfxSettings                              2229    22     74
oCAnimation                                         2216   198  48932
oCGameStream                                         357    24  21778
oCDtTileDefinition                                   210    70    177
oCGlobalEntityValueSettings                          204    20     31
oCDtEnemyDefinition                                   80    28    172
AchievementDefinition                                 42    32     36
oCDtEnemyTribeDefinition                              24    21     70
GameModifierDefinition                                22    29     32
oCDtHeroDefinition                                    12    32     87
oCCollisionMesh                                       11  1032  31950
oCDtRewardDefinition                                   6    26     30
oCDtIngredientDefinition                               6    43     75
oCTexture                                              5  1062 4194371
ChallengeDefinition                                    5   331    430
oCDtEnemyCampTierDefinition                            4    22     26
oCDtMapDefinition                                      4   141   6288
oCDtDreamShardDefinition                               4    79     80
```

Narrow-spread classes are prime first targets for empirical schema
extraction: `oCMaterial` (~2x spread, almost certainly string-content
variation around a fixed framework), `oCScheduledVfxSettings`,
`oCGlobalEntityValueSettings`, `AchievementDefinition`, `GameModifierDefinition`.

### Decoded schemas (`tools/class_diff.py`)

`tools/class_diff.py <ClassName>` walks all cooked files of that class
and reports which byte offsets vary across instances. Constant offsets =
struct framework; varying offsets = data fields. Schemas decoded:

#### `oCDtEnemyCampDifficultyDefinition` (18 bytes, 6 samples)

```
0x00  u32     reserved = 0
0x04  u8      flag1 = 1
0x05  u8      flag2 = 1
0x06  u8      difficulty_index   (varies 1..5)
0x07  3-byte  padding
0x0a  float   min_value          (e.g. 40.0)
0x0e  float   max_value          (e.g. 45.0)
```

Reveals camp difficulty bands. Modders can change spawn intensity per
band by patching the two floats.

#### `oCGlobalEntityValueSettings` size=23 (143 instances)

```
0x00  u32     reserved = 0x00000003
0x04  u32     flags
0x08  u32     reserved = 0
0x0c  float   VALUE                  <-- the single payload float
0x10  u32     reserved = 0
0x14  u8      end_flag = 0
0x15  u8/u16  reserved = 0
0x12  u8      reserved = 0
0x14  u32     reserved (END marker at body end)
```

143 game-balance constants. Sample decoded names + current values:

```
   -100.0000   Hero_Is_Vulnerable_Value
     25.0000   Shield_On_Combat_Modifier
      5.5000   Ignite_Duration_Value
      5.0000   Bleed_Duration_Value
      5.0000   Chilled_Duration_Value
      5.0000   Regeneration_Duration_Value
      1.0000   Chapter_Scaling_Enemies_Damage_Factor
      1.0000   Chapter_Scaling_Enemies_Max_Health_Factor
      1.0000   Resistant_III_Value
      0.7500   Resistant_II_Value
      0.5000   Resistant_I_Value
      0.2500   ActivityScore_StoryQuestValue
      0.2000   Card_Attack_Damage
      0.1000   ActivityScore_MiniBossValue
      0.0100   Card_Heal_Ratio
   ...
```

Tooling: `tools/make_global_value_mod.py` generates a complete mod
directory that patches any subset of these floats. Example:

```sh
tools/make_global_value_mod.py --mod-id LongerStatusEffects \\
    Bleed_Duration_Value=10 Ignite_Duration_Value=11
tools/make_global_value_mod.py --list-values    # see all 143
```

The other 60 size=20 / size=31 instances have a different framework
(no float payload, mostly enum/flag-like), not handled yet.

#### `oCDtRewardDefinition` (26 or 30 bytes, 6 samples)

Zero varying offsets across the 6 instances in each size bucket. The
reward identity comes from the filename / encoded path; the file body
is template-fixed. No useful mod surface here without the re-encoder.

#### `AchievementDefinition` (32 or 36 bytes, 42 samples)

Almost entirely constant; only 2 bytes vary (achievement flags) at the
tail of the size=36 bucket.

#### `GameModifierDefinition` size=29 (19 samples)

```
0x00  u32     reserved = 0x05
0x04  u32     reserved = 0x02
0x08  u32     reserved = 0
0x0c  u8      flag = 1
0x0d  END marker (inner section)
0x15  float   modifier_value   (e.g. -0.15, +0.10)
0x19  u16     reserved
0x1b  u16     reserved
```

Modifier-system values (damage/speed/etc deltas applied as game
modifiers). 4-byte float at body-offset 0x15.

### Translation text banks (`_Cooking/Qqpi/`)

`Qqpi/` decodes to `Text/`. Each translatable subject is two files:

```
<Name>~GAM.xls.LocalText.gen           # base: ordered list of keys
<Name>~GAM.xls.LocalText.gen.Lang<XX>  # one per language: ordered values
```

Format of both base and per-language files:

```
0x00  u32   header_size = 0x10
0x04  u32   reserved    = 0
0x08  u32   reserved    = 0
0x0c  u32   entry_count
0x10  u32   entry_count          (same; possibly capacity)
0x14  ---- entries ----
        u32 byte_len_n
        n bytes of UTF-8
```

Key[i] in the base maps to Value[i] in each language file. No internal
section markers. No checksum. Trivial to edit.

Language-code mapping (encoded suffix on disk -> decoded ISO code):

```
GgzyMU = LangEN   GgzyEW = LangJA   GgzyIO = LangKO
GgzyLJ = LangRU   GgzyMF = LangES   GgzyNM = LangDE
GgzyTG = LangPL   GgzyVL = LangFR   GgzyXQ = LangIT
GgzyTQ-BL = LangPT-BR  GgzyYA-F = LangZH-S  GgzyYA-Q = LangZH-T
GgzyLWR = LangRO
```

Tool: `tools/make_text_mod.py` lists keys/values and generates a mod
that overrides them. Confirmed in-game 2026-05-14 by renaming
`Common_EN:Menu_Discord` from "Discord" to "Mods (RSMM)" — visible on
the main menu.

`tools/apply_mods.py` resolves the `.Lang<XX>` suffix without needing
asset_map entries for every sibling.

### oCEntitySettingsResource — empirical structure (body <= 80)

Of the 4384 `oCEntitySettingsResource` cooked files, 1522 have a body
section <= 80 bytes (i.e. an entity with no/few extra components). Diff
of the smallest few shows an identical framework — they vary only in a
single 16-byte field that's clearly per-entity unique:

```
0x00  03 00 00 00          u32 = 3                (object count?)
0x04  [01 00 00 00]         u32 = 1   (optional; absent in body=45 sample)
0x08  00 00 00 00           u32 = 0
0x0c  00                    u8  = 0   (padding/alignment)
0x0d  10 00 00 00           u32 = 0x10 (length-of-GUID?)
0x11  <16 bytes>            GUID (entity ID — unique per file)
0x21  00 00 00 00           u32 = 0
0x25  ff ff ff ff           u32 = -1  (no parent / null reference)
0x29  00 00 00 00           u32 = 0
0x2d  22 22 bb aa           inner END marker
```

So every entity carries a 128-bit GUID. That's what the engine uses to
refer to entity instances across files. Implications:

- Adding a new entity to a level (e.g. a "Mods" button to MainMenu)
  needs a freshly-minted 128-bit ID. UUIDv4 is the obvious choice; needs
  validation that the engine accepts any unused value.
- Editing existing entities is safe; we don't need to change the GUID.

This is the most concrete piece of `oCEntitySettingsResource` schema we
have so far. With ~80 small-body samples, more byte-level diffing should
recover the rest of the framework.

### Title menu entity layout (`Title_Menu_Ui.entity.ot.EntitySettingsResource.gen`)

Decoded enough of the title-menu cooked file to *add* a real new button
to the menu without writing a full re-encoder.

`Title_Menu_Ui` registers 55 component classes (oCEntity*, oCUI*,
oC2dElement*, oCFMod*, etc.) and contains 66 sections in the cooked
file. Sections are not flat — many are bracketed BEGIN/END blocks
containing one entity component each.

Top-level section payload starts with a u32 *class index* (selecting the
component class from the file's class table), followed by an inner
parent-ref block, then a self-GUID + length-prefixed internal name, then
class-specific payload bytes. So the layout of *every* top-level
component section is:

```
[ 0] MARK_BEGIN (outer)
[ 4] u32   class_index           # into local class table
[ 8] MARK_BEGIN (inner parent-ref block)
[12] u32   = 0x18                # block size marker
[16] 16B   parent GUID           # often all-zero (no parent ref)
[32] u32   parent path strlen    # often 0
[..] N bytes UTF-8 parent path
[..] MARK_END
[..] 16B   self GUID
[..] u32   strlen
[..] N bytes UTF-8 internal name
[..] class-specific payload
[..] MARK_END (outer)
```

For `oCEntityCpntStateSettings` (class index 7 in this file), the
class-specific payload includes a *picker array* — an ordered list of
references to other entity components in the same file. Format:

```
[ ..] u32   picker_count
[ ..] picker_count * { MARK_BEGIN; u32(0x18); 16B target GUID;
                       u32 path strlen; path UTF-8; MARK_END }
```

Each picker path is `[ClassTag] <Hierarchy\Path\To\Component>` where
ClassTag identifies the referenced component class:

| ClassTag          | Component class                            |
|-------------------|--------------------------------------------|
| Spawner Value     | oCEntityCpntSpawnerValueSettings           |
| Entity Spawner    | oCEntityCpntEntitySpawnerSettings          |
| Window Ui         | oCEntityCpntWindowUiSettings               |
| State             | oCEntityCpntStateSettings                  |
| Timer             | oCEntityCpntTimerSettings                  |
| FMod Event        | oCEntityCpntFModEventSettings              |
| Game Ui           | oCEntityCpntGameUiSettings                 |
| Picture Ui        | oCEntityCpntPictureUiSettings              |
| Cpnt Value Tester | (one of the *TestSettings classes)         |
| String Format     | oCEntityCpntStringFormatValueSettings      |

The title menu's `State Init` state has a 10-entry picker array — five
buttons × two component refs each (Spawner + Text):

```
[Spawner Value] Title_Menu_Ui\Old Menu\Play Button Text
[Entity Spawner] Title_Menu_Ui\Old Menu\Play Button Spawner
[Spawner Value] Title_Menu_Ui\Old Menu\Discord Button Text
[Entity Spawner] Title_Menu_Ui\Old Menu\Discord Button Spawner
[Spawner Value] Title_Menu_Ui\Old Menu\Patch Button Text
[Entity Spawner] Title_Menu_Ui\Old Menu\Patch Button Spawner
[Spawner Value] Title_Menu_Ui\Old Menu\Bug Button Text
[Entity Spawner] Title_Menu_Ui\Old Menu\Bug Button Spawner
[Spawner Value] Title_Menu_Ui\Old Menu\Exit Button Text
[Entity Spawner] Title_Menu_Ui\Old Menu\Exit Button Spawner
```

Each button spawner section (`oCEntityCpntEntitySpawnerSettings`)
references the template `EntitySettings/GameUis/Common_Ui/Title_Menu_Button.entity.ot`,
so each button is an instance of the same template. Each button text
section (`oCEntityCpntSpawnerValueSettings`) back-references its
spawner by full picker path AND by raw 16-byte target-GUID.

**Add-button strategy** (implemented in `tools/make_real_menu_button_mod.py`):

1. Clone the Discord Button Spawner section bytes; rewrite self-GUID to
   a fresh UUID; substring-rename "Discord Button" -> "Mods Button" in
   every length-prefixed string (recomputing strlen prefixes).
2. Clone the Discord Button Text section bytes; rewrite self-GUID; swap
   the back-reference target-GUID from the Discord Spawner's GUID to
   the new Mods Spawner's GUID; substring-rename "Discord Button" ->
   "Mods Button".
3. In the State Init section, increment picker_count 10 -> 12 and
   append two new picker entries pointing at the new Spawner + Text
   clones by GUID + path.
4. Splice the patched State Init back into the cooked file; append the
   two cloned sections at the end of the file. Marker-balance is
   preserved end-to-end; no section sizes are stored anywhere so
   variable-length splices are safe.

Successful tests confirm:
- Patched file parses cleanly through `tools/ot_decoder.py` (68 top-
  level sections, picker array now has 12 entries).
- Engine accepts the file at runtime (TBD — needs in-game verification).

Known open question after applying the patch:
- The clone shares button position with Discord; if positions are
  explicit floats inside the spawner payload (likely), both buttons
  render on top of each other. If the NavigableZone auto-stacks, the
  new button appears below Exit. Either way the fix is to identify the
  position field in `oCEntityCpntEntitySpawnerSettings` and offset it
  in the clone — left to a follow-up.

## In-game Mod page (Social tab 7th page)

Implemented by `tools/make_social_mods_page_mod.py` (mod `SocialModsPage`).
Adds a 7th selectable page entry to the in-game Social tab without
touching the original News page.

### Approach

The Social tab's child pages are listed in section `Dt Social Book Page`
inside `Social_Book_Page.entity.ot.EntitySettingsResource.gen`. That
section's payload contains a slot array:

```
[u32 count]
[count * page slot]
```

Each page slot is a variable-length blob with this rough layout:

```
BEGIN 0x1d
  lpstr "EntitySettings"
  lpstr "<entity .ot path>"
  BEGIN 0x13 <16B GUID> lpstr "[Game Ui] ..."  END
  BEGIN 0x13 <16B GUID> lpstr "[State] ..."    END
  BEGIN 0x14 0x00
    BEGIN 0x15 ... END
    lpstr "Text"
    lpstr "<bank>.xls"
    u32 <text-key index>
    lpstr "<text key name>"
  END
  BEGIN 0x14 0x01 0x00
    BEGIN 0x13 <16B tester GUID> lpstr "" END
    <4-byte tester hash>
    BEGIN 0x15 ... END
  END
END END END
```

Slot 0 is the News page. The walker locates the 6 slot starts by
scanning for `MARK_BEGIN + 0x1d 00 00 00`, then identifies the count
u32 at `slots[0] - 4`.

### Phase 1 — page bump verified

Byte-for-byte duplicate of slot 0 inserted after slot 5; count bumped
6 → 7. Engine produced two functional "News" entries (slot 0 and slot
6) sharing the same `SocialNewsPage` entity instance. Confirms the
engine resolves picker target-GUIDs per-instance (scoped to the spawn
parent), so two slots pointing at the same entity coexist cleanly.

### Phase 2 — separate Mods entity

1. Cloned cooked file `SocialNewsPage.entity.ot.....gen` byte-for-byte
   under a new encoded filename:
     `Wll_Brrm_Tgyqv!Frbdgl!FrbdglHrtvTgyq.qzidis.ri.MzidisFqiidzyvLqvrwubq.yqz`
   (decodes to `EntitySettings\GameUis\All_Book_Pages\Social\SocialModsPage.entity.ot.EntitySettingsResource.gen`).
   GUIDs were **not** regenerated; per-instance scope handles collisions.
2. Slot 7 in `Social_Book_Page`'s `Dt Social Book Page` patched:
   - entity path lpstr `SocialNewsPage` → `SocialModsPage`
     (same byte length, in-place swap)
   - text-key u32 `0x148` (= 328, `Book_Page_News`) → `0x1e3` (= 483,
     `Book_Page_DLC`)
   - text-key lpstr `Book_Page_News` (14B) → `Book_Page_DLC` (13B);
     length change is **safe in this section** (Dt Social Book Page
     tolerated the 1-byte shrink + 387-byte insertion without audio
     break).
3. `MainMenuMods` adds `Book_Page_DLC=Mods` so the tab label reads
   "Mods" in-game.
4. `UsedRscList.ot` gets a 3-line triplet appended for the new entity:
   ```
   MzidisFqiidzyv
   KgxqJdv\Wll_Brrm_Tgyqv\Frbdgl\FrbdglHrtvTgyq.qzidis.ri
   MzidisFqiidzyv\KgxqJdv\Wll_Brrm_Tgyqv!Frbdgl!FrbdglHrtvTgyq.qzidis.ri.MzidisFqiidzyvLqvrwubq.yqz
   ```

### Phase 3 — header text inside cloned entity

The page-header label is referenced from a `Title_Label` section
(Section 91 in the cloned entity) as:

```
lpstr "Text"
lpstr "Common~GAM.xls"
u32 <text-key index>
lpstr "<text key name>"
```

Patching `Book_Page_News` → `Book_Page_DLC` here (14B → 13B) **broke
audio**: with the 1-byte shrink, FMod/state-machine bindings stopped
firing across the scene. Whether the audio break was due to a cached
class-payload offset or some other length-encoded internal field is
unconfirmed; what is confirmed is that **length-stable lpstr edits
inside cloned entities are audio-safe and length-changing edits are
not**.

Fix: replace with a 14-byte text key. The mod uses `Book_Page_Shop`
(also 14B, index 454/`0x1c6`) as the swap target. `MainMenuMods` then
renames `Book_Page_Shop=Mods` so the header reads "Mods" while
preserving byte length.

### Phase 4 — hide inherited tile artwork

The cloned entity inherits 3 tiles (DLC / Discord / PatchNote) from
SocialNewsPage. Removing the tile sections would shift bytes and risk
the audio break. Instead, the mod blanks them visually by rewriting
every per-tile texture lpstr's directory component from `News` to
`Void` (same 4-character substring, so byte length unchanged):

```
BookMenu\News\Newsbg_Mask.png      -> BookMenu\Void\Newsbg_Mask.png
BookMenu\News\Newsbg_Border.png    -> BookMenu\Void\Newsbg_Border.png
BookMenu\News\Newsbg_DLC4.png      -> BookMenu\Void\Newsbg_DLC4.png
BookMenu\News\Newsbg_DIscord.png   -> BookMenu\Void\Newsbg_DIscord.png
BookMenu\News\Newsbg_Update4.png   -> BookMenu\Void\Newsbg_Update4.png
BookMenu\News\QRCode_Discord.png   -> BookMenu\Void\QRCode_Discord.png
BookMenu\News\QRCode_PatchNote.png -> BookMenu\Void\QRCode_PatchNote.png
```

`BookMenu\Void\` is not a real directory, so the engine's texture
load silently fails for each tile, leaving the tile region blank.

### Hard limits

- **No new text keys.** `make_text_mod.py` only updates existing keys
  in the cooked `Common~GAM.xls` bank. Distinct in-page labels per
  Mods tile require finding existing keys with matching byte lengths
  and renaming them — and only the renamed copies are available, so
  the original meaning is lost.
- **No new click behaviour.** Each tile's click resolves to a
  compiled engine method (e.g. `Modal Methods`, `Discord Link
  Methods`). Adding a new mod-manager action would require either
  hooking into one of those compiled methods or substituting a
  different method picker target — but the available methods are
  fixed by the engine binary.
- **No dynamic mod listing.** The engine has no awareness of the
  `mods/` directory at runtime; everything in the in-game UI is
  serialized from cooked assets at build time.

### Audio-safety rule

When editing a **cloned entity's** cooked payload, every lpstr swap
must preserve byte length. When editing a **parent picker array** in
a different file (e.g. `Dt Social Book Page` inside
`Social_Book_Page....gen`), length changes are tolerated as long as
the section's outer BEGIN/END markers stay balanced.

## Conclusion

The game appears to use a layered compiled asset ontology:

- Engine layer as noise
- Namespace generation system
- Gameplay and content subsystems
- Containerized file formats

This structure can likely be reconstructed via graph clustering.

## Phase 3 — Live engine instrumentation via MinHook (2026-05-15)

### Loader architecture

- `winhttp.dll` proxy (MinGW cross-build, `.def` forwarders to `winhttp_real.dll`)
- Wine loads it because Steam launch options set `WINEDLLOVERRIDES="winhttp=n,b" %command%`
- `DllMain` spawns a worker thread which calls `rsmm::install_engine_hooks()`
- Process filter: `GetModuleFileNameW` → skip if leaf != `Ravenswatch.exe`. Required
  because `crashpad_handler.exe` is spawned with the same winhttp override and
  resolves the link-time VA to a non-executable page (`MH_ERROR_NOT_EXECUTABLE`).

### PE relocation

Ghidra link-time ImageBase: `0x140000000`. Wine ASLR puts the .exe somewhere
else per launch (observed `0x6ffffc6a0000`). Resolve runtime VAs as:

```text
runtime = GetModuleHandleW(nullptr) + (link_va - 0x140000000)
```

A retry loop on `VirtualQuery` (up to 5 s) covers a race where the loader
thread fires before the exe's `.text` mapping is fully committed.

### Hooked functions

| Link VA       | Symbol (Ghidra)                       | Purpose                                |
|---------------|---------------------------------------|----------------------------------------|
| `0x1401145b0` | `FUN_1401145b0` (oCString init/copy)  | Captures any path string the engine constructs at runtime. Filter: substring match on `Social`/`Friend`/`Book_Page`/`News`/`Mods`. |
| `0x140487040` | `FUN_140487040` (resource hashmap)    | The canonical resource-by-path lookup. Returns a handle the engine treats as the loaded entity. |

`FUN_140487040` is an FNV-1a + SwissTable-style probe (lowercased path,
16-byte vectorized bucket scan). One entry per *path*, not per call-site —
the engine caches resources by path hash.

### Captured handles (one run)

```text
Friend_List_Recent.entity.ot       -> 0x671db80
Friend_List_Model.entity.ot        -> 0x671db38
Friend_List_Manage.entity.ot       -> 0x671daf0
Friend_List_Invite.entity.ot       -> 0x671daa8
Friend_List_Request.entity.ot      -> 0x671dbc8
Friend_List_Blacklist.entity.ot    -> 0x671da60
SocialNewsPage.entity.ot           -> 0x671de50   (News tile, slot 0)
Social_Book_Page.entity.ot         -> 0x671df28
End_Credits_Book_Page.entity.ot    -> 0x671d280
```

Handles vary per launch (allocator). The mapping path → handle stays 1:1
within a launch.

### The architectural breakthrough

`tools/make_social_mods_page_mod.py` clones slot 3 (Friend_List_Recent) and
appends it as slot 7 (Mods). Both slots reference the **same path** string
`GameUis\All_Book_Pages\Social\Friend_List_Recent.entity.ot`.

`FUN_140487040` resolves that path **once**, caches by hash, and returns the
**same handle** (`0x671db80`) for every subsequent lookup. Result: slot 7
and slot 4 are literally the same entity. The engine has no way to
distinguish them.

This is why none of the previous attempts to make slot 7 behave
differently (button rebinding, text rename, etc.) survived — the engine
short-circuits to the cached entity before any slot-local context exists.

### Implication

Per-slot divergence requires per-slot **path** divergence. Two options:

1. Point slot 7 at a *real* alternate cooked entity (audio-fragile,
   needs a clone with regenerated GUIDs).
2. Point slot 7 at a *fake* path the engine will look up but won't find,
   then intercept in `hook_resource_lookup` and return a substitute
   handle (existing entity or one we pre-load).

Option 2 is the live-loader path forward.

### Phase 3 — Redirect outcome (empirical)

Implemented option 2: cooked file now references `Mods_List.entity.ot`
(does not exist on disk); `hook_resource_lookup` returns a cached
substitute handle. Trace confirms mechanism:

```text
redirect cache: substitute='SocialNewsPage.entity.ot' handle=0x6721cd0
redirect path='GameUis\All_Book_Pages\Social\Mods_List.entity.ot'
              real=0x0 sub=0x6721cd0 out=0x6721cd0
```

`real_resource_lookup` returns 0 (path miss); we return the substitute
handle the engine had cached for a different real path. Engine accepts
the handle and renders the substitute's entity tree.

**Substitute experiments:**

| Substitute path                       | Visual outcome |
|--------------------------------------|-----------------|
| `SocialNewsPage.entity.ot`            | Renders, but News-page tile textures sized for slot 0 geometry → blown-up sprites in slot 7's friend-list container. |
| `Friend_List_Invite.entity.ot`        | Renders full invite list, functional (invite buttons work). Layout offset to centre of book panel because the entity's internal layout is tuned for a different render context. |
| `Friend_List_Model.entity.ot`         | Renders at correct slot position with placeholder/random-username rows from the model template. No offset. Row contents fetched at runtime via Steam Friends API (not via `FUN_1401145b0`), so cannot be intercepted from oCString hook. |
| `MagicalObjects_Compendium_Page.entity.ot` | Renders inside slot. Item names *are visible* but come from a runtime controller (`MagicalObjectsCompendiumPageUiControllerEntityCpntSettings`), not embedded bytes. Decoder shows only UI element internal names + texture paths + 1 text-bank key. No item-name lpstrs to patch. |
| `System_Book_Page.entity.ot`          | Decoded: 45 classes, controller-driven via `BookOptionsUiControllerEntityCpntSettings`. Static lpstrs: only a handful of text-bank keys (`Common_Back`, `Common_Enter`, `Menu_Settings`, etc.). Rows spawned dynamically. Not suitable. |
| `Modal_Social_Options_Menu.entity.ot` | Renders 6 static button rows (`Book_Page_Blacklist`, `Social_Page_Mute`, `Social_Page_Report`, `Social_Page_Send_Friend_Request`, `Social_Page_Show_Gamercards`, `Social_Page_Unmute`) — exactly the kind of static text-bank-keyed button list we want. **But** the modal is sized for a fullscreen overlay; rendered into a book-page slot the buttons cover the entire book panel. Unfixable without entity-level layout patching. |
| `Friend_List_Model.entity.ot` *(chosen substitute)* | **Confirmed clean.** Renders at correct slot position. Placeholder rows from the model template. No baked-in static labels — row text comes from Steam Friends API (does not pass through `FUN_1401145b0`, so cannot be intercepted from the oCString hook). Aesthetic only; no path to inject mod names from here. |

### Where this leaves us

Two dead ends and one cosmetic fit:

1. **Slot-friendly book pages are all controller-driven.** None of the
   simple book-page entities have a static N-button-list shape with
   per-button text-bank keys. Their layouts come from a controller
   that populates rows at runtime from game data (heroes, items,
   memories, friends, etc.).
2. **Static-button-list modals are fullscreen.** `Modal_Social_Options_Menu`
   has the exact button structure we want, but its layout assumes a
   fullscreen overlay context. Rendered into a slot the buttons cover
   the entire book panel.
3. **Friend_List_Model fits the slot cleanly** but offers no string
   surface we control (row content is Steam-fed).

Therefore: to actually display mod names + toggle state, we have to
either (a) build a custom Mods entity from scratch with the right
layout, or (b) entity-patch an existing fullscreen modal's layout
fields to slot dimensions. Both are significant binary-format work
that has been deferred since Phase 1.

### Live-trace insight worth keeping

Visible UI text comes from a `Common~GAM.xls` lookup keyed by an
lpstr in the entity. We already proved at the build level (Phase 1)
that `Book_Page_DLC=Mods` overrides reliably via
`tools/make_text_mod.py`. So if any future substitute exposes N
static text-bank keys we can rename, the path from key to visible
text is trivial — the gap is finding/building the substitute itself.

**Conclusions:**

1. The redirect mechanism is fully working. Engine treats the substitute
   handle as authoritative; renders its entity tree at slot 7.
2. The substitute is also fully **interactive** — Friend_List_Invite's
   invite buttons function in slot 7 the same as in their original
   context. The engine has no slot-aware UI scoping for our purposes;
   if we wire a substitute entity whose buttons fire useful events,
   those events will fire.
3. Visual fit depends on the substitute's baked layout. Per-slot
   geometry lives inside the substitute entity, not the slot picker.
   To get a clean Mods panel we either pick the cleanest existing
   layout or build a custom cooked entity.

### Audio safety still holds

The cooked-file patch still only touches `Dt Social Book Page` (a
picker array, length deltas tolerated). No cloned-entity payloads
need byte-exact lpstr swaps. Crash-free across all runs.

## Phase 5 Stage B — own the Mods_List cooked file (2026-05-16)

Previously slot 7's picker pointed at the fake decoded path
`GameUis\All_Book_Pages\Social\Mods_List.entity.ot`, which did not
exist on disk; the loader's `hook_resource_lookup` returned a
cached substitute handle (Friend_List_Invite) so the slot rendered
*something*. Stage B ships a real cooked file at that path.

### Approach

`tools/make_mods_list_entity.py` now:

1. Source-clones the bytes of `Friend_List_Recent.entity.ot.
   EntitySettingsResource.gen` (13314 bytes — chosen because the
   friend-list family already renders cleanly at the slot 7
   position; static button section with text-bank keys at
   `Social_Page_Report` / `Social_Page_Block` / `Social_Page_Add`
   etc. is exactly the shape we want long-term).
2. Writes the clone to
   `mods/SocialModsPage/assets/EntitySettings/GameUis/All_Book_Pages/Social/Mods_List.entity.ot.EntitySettingsResource.gen`.
3. Appends an asset-map row mapping the new encoded path
   `MzidisFqiidzyv\KgxqJdv\Wll_Brrm_Tgyqv!Frbdgl!Hrtv_Gdvi.qzidis.ri.MzidisFqiidzyvLqvrwubq.yqz`
   to its decoded counterpart (cipher.py round-trip verified).
4. `apply_mods.py` then drops the cooked file at the encoded path
   with the normal backup pipeline. Since the path didn't exist
   in vanilla there is no backup file — `--restore-all` deletes
   the dropped file (clean rollback).

### Why no GUID regeneration

Phase 1 already proved (page bump verified) that the engine
resolves picker target-GUIDs scoped to the spawn parent. Two
slots pointing at the same internal GUIDs coexist cleanly — the
resource cache keys by *path*, and our path is distinct. Byte-
clone is safe.

### Verified

- `tools/ot_decoder.py` parses the new file cleanly (31 classes,
  16 sections, matches source).
- `apply_mods.py --list` lists both SocialModsPage files; the new
  one resolves to its encoded destination without an
  `[no asset_map match]` warning.
- `apply_mods.py` installs the file at the encoded path; state
  file records it as added (no backup since vanilla had nothing
  there).

### Required follow-up — UsedRscList.ot triplet (2026-05-16)

First in-game test after Stage B showed the loader trace line:

```
redirect path='GameUis\All_Book_Pages\Social\Mods_List.entity.ot' real=0x0 sub=...
```

`real=0x0` means `real_resource_lookup` still returns 0 even though
the cooked file is on disk at the encoded path. Cause: the engine's
resource-hashmap (FUN_140487040) only resolves paths that exist in
the startup manifest `DarkTalesResources/UsedRscList.ot`. The
shipped manifest has no entry for our new path.

Format of a UsedRscList entry (3-line triplet, plain UTF-8 text):

```
MzidisFqiidzyv
KgxqJdv\Wll_Brrm_Tgyqv\Frbdgl\<Name>.qzidis.ri
MzidisFqiidzyv\KgxqJdv\Wll_Brrm_Tgyqv!Frbdgl!<Name>.qzidis.ri.MzidisFqiidzyvLqvrwubq.yqz
```

Top-level dir, short encoded path (`\` separators preserved), full
encoded path (sub-dirs collapsed with `!`). All three lines use
cipher-encoded letters per `tools/cipher.py`.

`tools/make_mods_list_entity.py` now also appends the triplet for
`Mods_List` and writes the patched manifest to
`mods/SocialModsPage/assets/_root/DarkTalesResources/UsedRscList.ot`.
`apply_mods.py` installs it via the `_root/` channel with the
normal backup pipeline (`UsedRscList.ot.rsmm.bak`). On next game
launch the engine indexes our encoded path → `real_resource_lookup`
returns a real handle → loader's redirect block selects `real` over
`sub` → slot 7 renders our owned file (Friend_List_Recent layout in
its own distinct cache slot).

`tools/make_social_mods_page_mod.py` previously cleaned up the
`_root/.../UsedRscList.ot` artifact as Phase 2 legacy. That cleanup
is now scoped to remove only `_root/.../_Cooking` (the Phase 2
cloned-entity artifact); the UsedRscList path is preserved.

### What this unblocks

- The redirect block in `loader/src/hook_engine.cpp` selects
  `real` over `sub` automatically — once the file is installed,
  the live substitute is no longer needed. Substitute remains as
  a fallback for users running the loader without
  `apply_mods.py`.
- All future entity-level edits (layout, text-bank rebind, button
  count) land on a file we *own*. They no longer risk affecting
  the real Friend_List_Recent.

### What this still does NOT give us

Same three defects called out in NEXT_STEPS.md #1, now scoped to
our owned file rather than the substitute:

1. **Layout** is inherited from Friend_List_Recent, which is
   slot-friendly but assumes friend-list internal context.
2. **Row text** still comes from the
   `FriendsListUiControllerEntityCpntSettings` component via the
   Steam Friends API, not from cooked-bytes lpstrs the
   `oCString` hook can rewrite.
3. **Back/click event sinks** still target the parent friend-list
   flow, so clicks fire but their listeners are no-ops in our
   slot's parent tree (Phase 4 click-toggle still works because
   it taps the modal-title `oCString` construction, not the
   click destination).

Concrete next-session work (in order of payoff):

a. **Layout-bounds RE.** Diff `oC2dElementDesc` instances across
   sized cohorts (`tools/class_diff.py oC2dElementDesc`) to find
   the width/height/position floats. With those identified, a
   single patch shrinks the inherited bounds to actual slot
   dimensions.
b. **Strip the FriendsListUiController section.** Now that we
   own the file, find the section index (by class — index
   `FriendsListUiControllerEntityCpntSettings` in the local
   class table) and elide it. Marker-balanced removal of one
   top-level section is the same operation we already do in
   `tools/make_social_mods_page_mod.py` for slot insertion,
   just inverted.
c. **Replace static button labels.** The cooked file has lpstr
   `Common~GAM.xls` followed by length-prefixed text-bank keys
   (`Social_Page_Report` etc.). Audio-safety rule says the
   lpstr swap must preserve byte length, but `make_text_mod.py`
   can rebind the *values* of any existing key — so renaming
   `Social_Page_Report=Toggle Mod 1` is enough to produce visible
   "Toggle Mod 1" without touching the cooked entity.
d. **Per-row click identity.** Once buttons render mod names, the
   existing click-signal hook (`Invite friend to party` modal
   title) becomes per-row identifiable: capture the last Steam
   ID seen on the `oCString` hook just before the modal title
   fires (the loader already tracks `g_last_steam_id`), map to
   the row index that was selected, derive the mod from a fixed
   row-to-mod-id table.

## Phase 4 — Click-toggle pipeline (working end-to-end)

Goal achieved: clicking a row in the in-game Mods tab toggles a
mod's `enabled` flag on disk. Pipeline:

1. **Loader DLL detects click.** The substitute entity is
   `Friend_List_Invite.entity.ot`. Each row click spawns an
   invite-confirmation modal whose title localizes to the string
   `"Invite friend to party"`. We hook `FUN_1401145b0`
   (oCString init/copy) and watch for that exact 22-byte string.
   When it fires AND `g_substitute_handle != 0` (Mods tab visited
   this session), we record an event to
   `mods/_clicks.log` with a timestamp and a monotonic counter.

   Hook target: `0x1401145b0` (already installed for path
   capture). Identifying the click string was a single broad-burst
   trace; the localizer call site is `link va = 0x14055d95c`
   inside `FUN_14055d850`. No new MinHook target required.

2. **Python tool drains the click log.** `tools/process_clicks.py`
   reads `_clicks.log`, compares the event count against a stored
   counter (`mods/_clicks.state`), and applies one toggle per
   unprocessed click. Toggles cycle through `mods/*/manifest.toml`
   in alphabetical order (ExampleMod, LongerStatusEffects,
   MainMenuMods, SocialModsPage). State is durable, so re-running
   the tool without new clicks is a no-op.

3. **Apply mods normally.** `tools/apply_mods.py` reads the
   updated manifests and applies/restores cooked files according
   to the new enabled state.

### Workflow

```text
WINEDLLOVERRIDES="winhttp=n,b" RSMM_ENGINE_TRACE=1 %command%
  # in-game: Social → Mods sub-tab → click rows
  # exit game

python3 tools/process_clicks.py
  # cycles N toggles for N unprocessed clicks

python3 tools/apply_mods.py
  # applies new enabled state to cooked dir
```

### Limitations

- **No per-row identity.** The current signal only tells us "a
  click happened in the Mods slot." We cycle through mods in
  order; clicking does not select a specific mod. Mapping click
  to mod requires capturing the row's Steam ID (visible in the
  trace at `ra=0xf9692e/0xf969f6/...`) or the in-engine
  selection index.
- **Inviting still fires.** Friend_List_Invite's native click
  action is still Steam invite. The mod toggle is a side effect
  of detecting the localized modal title. The modal also pops up
  in-game.
- **No live UI feedback.** Toggle takes effect only after
  `process_clicks.py` + `apply_mods.py` + relaunch. The Mods tab
  still shows friends, not mod names.

### What this proves

The redirect mechanism is sufficient to turn an in-game UI click
into a persistent disk write under our control. The remaining
work is cosmetic + semantic: getting the Mods tab to show mod
names instead of friends, and getting per-row identity so each
mod has a dedicated button. Both are deferred to a custom-entity
build pass.

## Phase 4b — Per-row click identity via Steam ID (2026-05-16)

Each row in the Friend_List_Invite substitute carries the Steam
friend's 64-bit ID, which the engine stringifies as a 17-digit
decimal through `FUN_1401145b0` just before constructing the
invite modal's title. Capturing that string between the row click
and the click-signal fire gives a stable per-row handle.

### Loader changes

`loader/src/hook_engine.cpp`:

- `g_last_steam_id` (previously declared but unused) is now
  populated inside `hook_string_init` whenever a 17-digit
  all-numeric oCString passes through, gated on the redirect
  being armed (`g_substitute_handle != 0`) to keep
  pre-Mods-tab noise out.
- `clicks_record` appends `steam_id=<17-digit>` to the event
  line when the captured ID is non-empty.

### Python changes

`tools/process_clicks.py` now parses the new `steam_id=` field.
A persistent map at `mods/_clicks_id_map.json` binds each Steam
ID to a specific mod (first sighting auto-assigns the next mod
in alphabetical order, subsequent sightings are stable).
Clicks without a `steam_id=` (e.g. from a loader build that
predates this change) fall back to the legacy alphabetical
cycle, so old click logs still process cleanly.

The mapping file is hand-editable — users who want a specific
row → mod binding can pre-seed it.

### Workflow

```text
# 1. Build + deploy rebuilt loader (dist/winhttp.dll)
loader/build.sh
tools/install_loader.sh

# 2. Reset stale click counter (optional)
tools/process_clicks.py --reset

# 3. Launch game with engine trace
WINEDLLOVERRIDES="winhttp=n,b" RSMM_ENGINE_TRACE=1 %command%
#   Social -> Mods -> click rows -> exit

# 4. Process clicks
tools/process_clicks.py
#   First click on Steam ID A: binds A -> ExampleMod, toggles ExampleMod
#   First click on Steam ID B: binds B -> LongerStatusEffects, toggles it
#   Second click on A: re-toggles ExampleMod (binding stable)

# 5. Apply toggles to cooked state
tools/apply_mods.py
```

### Limits

- Steam friends list ordering is not stable across launches (Steam
  re-orders by online status). The Steam ID is stable; the
  visible row position is not. Users editing `_clicks_id_map.json`
  by hand will need to know which Steam ID corresponds to which
  visible row.
- An empty friends list shows no rows to click, so the binding
  table can't bootstrap on accounts without Steam friends.
  Acceptable trade-off because (a) most Ravenswatch players have
  Steam friends and (b) the underlying friend-list substitute is
  Stage B's transitional layout — the long-term plan is a
  custom Mods row source so this constraint goes away.
