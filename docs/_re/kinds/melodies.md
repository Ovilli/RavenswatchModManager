# Melodies (the Piper's lost melodies)

Class: `oe::dt::MelodyDefinition`, asset glob `*.melodydef.ot`.
Codec: `cooked_schemas.definitions._dsl_spec("MelodyDefinition", "melodydef.json", …)` —
generic DSL spec, byte-stable round-trip over **all 12** retail files
(`tests/test_melody_kind.py::test_all_retail_melodydefs_round_trip_byte_for_byte`).
SDK kind: `melody` (`src/rsmm/sdk/kinds/melodies.py`), confidence **`guess`**.

Ghidra VAs below come from the MCP-attached program, which is a *different/older build*
than the live exe (see the `scripts/disasm.py` banner) — treat them as class-identity
evidence, not as addresses to bake into anything.

- `oe::dt::MelodyDefinition::vftable` @ `0x140f29b70` (31 slots, deserialize-shaped)
- `oCTLibrary<oe::dt::MelodyDefinition>::vftable` @ `0x140f29af8` (registry singleton)
- runtime: `MelodyEntityCpnt` `0x140ed74a0`, `MelodyProfileData` `0x140f00af0`,
  `MelodyUiViewerEntityCpnt` `0x140f2e910`

No function in the attached DB is named `*Melody*` — the deserializer is still an unnamed
`FUN_*`, so the field names below are mined from the **data population**, not decompiled.

## Corpus

12 defs under `data/uncooked/Definitions/Melodies` (`Deal_Damage_Around`, `Fully_Heal`,
`Grant_Damage_Overtime`, `Increase_Fountain_Effect`, `Increase_Move_Speed_At_Day`,
`Instant_Level_Up`, `Power_Up_Level_Max`, `Reduce_MO_Per_Collection`,
`Refill_Sandman_Dreams`, `Remove_Key_Requirement`, `Reveal_Map`, `Slow_Hourglass_Flow`).
Each has a paired effect entity, cooked and present:
`EntitySettings\Objects\Melodies\<stem>.entity.ot.EntitySettingsResource.gen`.

## Decoded layout

The DSL spec exposes `field_a` + `entity_ref`; everything after is preserved verbatim in
`_tail_hex`. Parsing the tail across the whole corpus gives a completely uniform shape:

```
field_a    u32     melody enum index
entity_ref tresptr ["EntitySettings", "Objects\\Melodies\\<stem>.entity.ot"]
--- _tail_hex ---
a          u32     4 | 5 | 6            (unknown; tier/weight?)
b          u32     always 3             (version tag?)
flags      u8 x3   varies per melody    (unknown)
guid       16B     unique per melody
           u32=1, u8=0                  (constant across all 12)
BEGIN(4)
  BEGIN(5) u32 count=0 END              (empty list, always)
  BEGIN(5) u32 count, lstr*count END    <- game-modifier exclusion list
END
```

`BEGIN`/`END` = `1111bbaa` / `2222bbaa`, the standard `ot_decoder` block framing; the u32
after `BEGIN` is a class tag, not a length (same convention as `game_modifier_cook`).

### `field_a` is a dense enum index

Across the 12 defs `field_a` takes the values `{0..11}`, each exactly once
(`test_field_a_is_a_dense_unique_enum_index`). It is an index, not free data.

### The trailing string list is game-modifier exclusions

Every string in every def is an **exact stem** of a file in
`data/uncooked/Definitions/GameModifiers` (`test_every_retail_exclusion_is_a_real_modifier_stem`):

| melody | exclusions |
|---|---|
| `Fully_Heal` | `NightOnly`, `DayOnly`, `NoFeathers` |
| `Slow_Hourglass_Flow` | `NoBossTimer`, `OneChapter` |
| `Reveal_Map` | `NoMinimap` |
| `Increase_Fountain_Effect` | `NoFountains` |
| `Grant_Damage_Overtime` | `NoBossTimer` |
| `Power_Up_Level_Max` | `OneChapter` |
| (6 others) | *(empty)* |

The semantics read straight off the pairings — a melody is withheld when a run modifier
would make it meaningless or degenerate (`Reveal_Map` under `NoMinimap`,
`Increase_Fountain_Effect` under `NoFountains`, `Slow_Hourglass_Flow` under `NoBossTimer`).
**Direction is inferred, not proven**: exclude-when-active is the reading that fits all 12,
but nothing rules out a whitelist reading with an inverted flag elsewhere.

## Why this kind is override-only — no new melodies

Same wall as [[skins]] / heroes:

1. `field_a` is dense `{0..11}` — there is no free index for a 13th melody.
2. `Ui\Melodies` ships exactly 12 per-melody icons (`UI_Melody_Icon_Galahad` …
   `UI_Melody_Icon_Turtle`) plus `_bg` / `_Hover` / `_Locked` chrome — a 1:1 match with
   the 12 defs.
3. The melodydef carries **no icon ref and no name/text ref**. The def→icon→name mapping
   is therefore resolved outside the asset, by index or by name, in code or in a UI
   layout the def cannot reach.

So a net-new melodydef would deserialize but have no index, no icon and no label. The kind
does not attempt it; it edits the 12 that exist, as a plain retail override (the emitted
asset lands at the vanilla decoded path and `rsmm apply` backs up + replaces it).

## Levers the `melody` kind exposes

- `effect="<stem>"` — repoint `entity_ref` at another retail melody's effect entity. The
  melody keeps its own index, GUID, icon and name; only the granted effect changes.
- `exclude=[...]` — replace the game-modifier exclusion list (`[]` clears it). Unknown
  stems raise (typo guard against the `GameModifiers` corpus).

`field_a`, `a`, `flags` and `guid` are deliberately **not** exposed — `field_a` and `guid`
are identity, `a`/`flags` are unmined.

## Open / unproven

- **No in-game playtest of either lever.** This is why the kind is `guess`, not
  `experimental`: unlike `reward`, whose codec was at least exercised in a run, nothing
  here has been loaded by the game.
- `a` (∈ {4,5,6}) and the 3 flag bytes are unidentified. Candidates: unlock tier, chapter
  gating, day/night applicability.
- Exclusion-list direction (blacklist vs whitelist) unconfirmed — see above.
- The overlay reference (github `rblaurent/ravenswatch-melody-overlay`, read-only) gives
  corroborating *runtime* offsets — melody GUID slots at scene-context `+0x760` (3 × 16B,
  slot order = unlock order), hero melody array at hero `+0x13a0` with u32 count at
  `+0x13a8`, melody state at cpnt `+0x68` (1=collecting, 2=completed), melody asset GUID at
  `+0x1c8`. The per-melody GUID in the def is the natural join key to those slots, which is
  the obvious next step if a runtime `R.melody` API is ever wanted.
