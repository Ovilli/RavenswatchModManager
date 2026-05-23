# Custom heroes — `oCDtHeroDefinition` + `SkillProfileDataSettings`

> Status: Tier-1 RE notes for `src/rsmm/sdk/kinds/heros.py`. Derived
> from live Ghidra MCP + headless decompilation under `docs/_re/out/`.
> Verify any field marked `# TODO: confirm` before byte emission;
> everything else is read straight from the binary.
>
> The module filename is `heros.py` (kind id `"hero"`), but the doc
> filename is `heroes.md` for English-correctness. See
> [`../../src/rsmm/sdk/content.py`](../../../src/rsmm/sdk/content.py)
> `_KIND_MODULES`.

Heroes are the **hardest** of the four playable kinds because
`oCDtHeroDefinition` has **no registered class UID** — it lives as a
nested definition inside a parent `SkillProfileDataSettings` record
(see [`../MOD_HOOKS.md` "Hero library — still partially unknown"](../MOD_HOOKS.md#hero-library--still-partially-unknown)).
The hero is therefore created/destroyed by the *parent's* deserializer,
not by a top-level factory lookup.

## The chain

```
SkillProfileDataSettings   (UID 0x186adbdf, size 0xd0, factory FUN_1403122f0)
    |  embeds (typed field)
    v
oCDtHeroDefinition         (no UID, ctor FUN_1403143b0, ≥ 0x900 bytes)
    |  named slots resolve through
    v
oCTLibrary<oCDtHeroDefinition>     (dtor FUN_14032deb0, acquire FUN_14032e960)
                                   (singleton address NOT in libraries.json — see below)
```

`SkillProfileDataSettings` itself derives from `oISerializable` (UID
`0x1da16c`); the chain is wired by `FUN_140177100` inside its
registrar.

| Class | UID | Size | Registrar | Schema cb | Ctor | Dtor |
|---|---|---|---|---|---|---|
| `SkillProfileDataSettings` | `0x186adbdf` | `0xd0` | `Register_SkillProfileDataSettings` (`FUN_140192330`) | `FUN_1403122f0` ("Hero skill profile data settings") | — | — |
| `oCDtHeroDefinition` | **none** | **≥ `0x900`** | — (nested) | — | `FUN_1403143b0` | `FUN_140314930` (+ thunk `FUN_1403148f0`) |
| `oCTLibrary<oCDtHeroDefinition>` | — | — | (static init — anchor not located) | — | acquire `FUN_14032e960` | `FUN_14032deb0` |

The hero library is referenced **only** by its own dtor and acquire
helper. The static-init function that installs its vftable + critical
section is not separately identifiable — likely inlined into a larger
group init or named via `__autoclassinit2`. Its singleton address is
therefore still unknown; the dtor takes its `this` pointer through a
function-pointer table consumed by `atexit`.

## `oCDtHeroDefinition` ctor walk — `FUN_1403143b0` (1339 B)

The ctor builds the inheritance chain
`oISerializable → oIResource → oCDtDefinition → oCDtHeroDefinition`
and then writes a long sequence of named-slot tuples plus two sub-record
ctors. The full annotated body:

| Hero offset | Field group | Notes |
|---|---|---|
| `+0x000` (`[0]`) | `vftable` | rewritten 3× during ctor; final = `oCDtHeroDefinition::vftable` |
| `+0x008..+0x020` | `oISerializable` body | zeroed |
| `+0x028..+0x030` (`[5..6]`) | `oIResource::serial_id` + flags | `[5]=0`; low 5 bits of `+0x30` cleared by `& 0xe0` |
| `+0x034` | refcount? | set to `1` |
| `+0x03c` | resource state | `0` |
| `+0x040..+0x060` (`[8..0xc]`) | `oCResourcePath` + free-list links | all `0` post-ctor |
| `+0x060..+0x288` (`[0xc..0x51]`) | `oCDtDefinition` body | sub-records; deferred to schema mining |
| `+0x268` (`[0x4d]`) | u32 (loaded flag?) | `0` |
| `+0x270..+0x288` (`[0x4e..0x50]`) | `oCDtDefinition` ptrs | `0` |
| `+0x284` | `oCDtDefinition` flags u16 | `0x0101` |
| `+0x288` (`[0x51]`) | `oIGameProfileDataOwner::vftable` | built by `FUN_1400c7a00` — installs `oIGameProfileDataOwner` body + 16-byte GUID |
| `+0x288+sub` | GUID Data1..Data4 | from `CoCreateGuid` |
| `+0x2b0` (`[0x56]`) | u32 | `0` |
| **`+0x2b8` (`[0x57]`)** | **named-slot `power_idle_anim_name.ptr`** | `&DAT_140eb46d0` — uses owner `DAT_141447250` |
| **`+0x2c0..+0x2c4` (`[0x58]`)** | **`power_idle_anim_name.hash`** + flag | `0x80000000`, `0` |
| **`+0x2c8` (`[0x59]`)** | **named-slot `power_idle_anim_alt.ptr`** | `&DAT_140eb46d0` |
| **`+0x2d0..+0x2d4` (`[0x5a]`)** | hash + flag | `0x80000000`, `0` |
| `+0x2d8` (`[0x5b]`) | owner ptr | `DAT_141447250` |
| `+0x2e0` (`[0x5c]`) byte | enable flag | `1` |
| `+0x2e8` (`[0x5d]`) | reserved | `0` |
| **`+0x2f0` (`[0x5e]`)** | **named-slot 2.a** | `&DAT_140eb46d0`, owner `DAT_141447250` |
| `+0x2f8..+0x300` | hash + flag | `0x80000000`, `0` |
| **`+0x300` (`[0x60]`)** | **named-slot 2.b** | `&DAT_140eb46d0` |
| `+0x308..+0x30c` | hash + flag | `0x80000000`, `0` |
| `+0x310` (`[0x62]`) | owner ptr | `DAT_141447250` |
| `+0x318` (`[63]`) byte | enable | `1` |
| `+0x320` (`[64]`) | reserved | `0` |
| **`+0x328` (`[0x65]`)** | **ability 1 name A** | `&DAT_140eb46d0`, owner `DAT_141446e18` |
| `+0x330..+0x334` (`[0x66]`) | hash + flag | `0x80000000` |
| **`+0x338` (`[0x67]`)** | **ability 1 name B** | `&DAT_140eb46d0` |
| `+0x340..+0x344` (`[0x68]`) | hash + flag | `0x80000000` |
| `+0x348` (`[0x69]`) | owner | `DAT_141446e18` |
| `+0x350` (`[0x6a]`) byte | enable | `1` |
| `+0x358` (`[0x6b]`) | reserved | `0` |
| `+0x360` (`[0x6c]`) | enum-ref | `_DAT_1412c7590` |
| `+0x368` (`[0x6d]`) u32 | enum value | `0xffffffff` |
| **`+0x370` (`[0x6e]`)** | **ability 1 description key** | `&DAT_140eb46d0` |
| `+0x378..+0x37c` (`[0x6f]`) | hash + flag | `0x80000000` |
| `+0x380..+0x390` (`[0x70..0x72]`) | reserved triple | `0,0,0` |
| `+0x398..` (`[0x73..0x79]`) | **ability 2 block** | same shape as `[0x65..0x6b]` |
| `+0x3d0..+0x3ec` (`[0x7a..0x7d]`) | ability 2 enum + desc | same shape as `[0x6c..0x6f]` |
| `+0x3f0..+0x408` (`[0x7e..0x80]`) | reserved triple | `0,0,0` |
| `+0x408..` (`[0x81..0x87]`) | **ability 3 block** | same shape |
| `+0x440..+0x45c` (`[0x88..0x8b]`) | ability 3 enum + desc | same shape |
| `+0x460..+0x478` (`[0x8c..0x8e]`) | reserved triple | `0,0,0` |
| `+0x478..` (`[0x8f..0x95]`) | **ability 4 block** | same shape |
| `+0x4b0..+0x4cc` (`[0x96..0x99]`) | ability 4 enum + desc | same shape |
| `+0x4d0..+0x4e8` (`[0x9a..0x9c]`) | reserved triple | `0,0,0` |
| **`+0x4e8` (`[0x9d]`)** | **standalone name slot** (model? portrait?) | `&DAT_140eb46d0`, **no owner ptr** |
| `+0x4f0..+0x4f4` (`[0x9e]`) | hash + flag | `0x80000000` |
| `+0x4f8` (`[0x9f]`) byte | enable | `0` (note: differs from earlier groups) |
| `+0x500..+0x5d8` (`[0xa0..0xba]`) | **inline `oCEntityGameUiSpawner + oCEntityCpntPicker`** | built by `FUN_1406d3ac0` — contains 2 more `&DAT_140eb46d0` slots for the UI/preview spawn |
| **`+0x5d8` (`[0xbb..0xc1]`)** | **melody/talent slot 1** | named-slot pair + owner `DAT_141447250` |
| **`+0x610` (`[0xc2..0xc8]`)** | **melody/talent slot 2** | same shape |
| **`+0x648` (`[0xc9..0xcf]`)** | **melody/talent slot 3** | same shape |
| **`+0x680` (`[0xd0..0xd6]`)** | **melody/talent slot 4** | same shape |
| **`+0x6b8..+0x7d0` (`[0xd7..0xf9]`)** | **vector of 5 × 0x38-byte entries** | built by `_eh_vector_constructor_iterator_(.., 0x38, 5, FUN_140114920)` → talent tree row, power upgrade row, or signature row |
| `+0x7d0..+0x7e8` (`[0xfa..0xfc]`) | array header (ptr, count, cap) | dtor frees via `FUN_1402106e0` → 0x38-stride loop, so this is another variable-length collection of 0x38-byte entries (powers? talents?) |
| **`+0x7e8..+0x808` (`[0xfd..0x103]`)** | **portrait/voice slot** | `&DAT_140eb46d0`, owner `DAT_1414470f0` |
| `+0x820` (`[0x104]`) | u32 | `0x10000` |
| `+0x828..+0x8a0` (`[0x105..0x113]`) | **`oCGameLockSettings + oCGameEventListenerSettings + 2 × oCCustomFlagList + oCCustomFlagFilter`** | built by `FUN_1400c76a0` — unlock condition + event listener |
| **`+0x8a0` (`[0x114]`)** | **parallel array A: data ptr** | `0` post-ctor; populated by deserializer |
| `+0x8a4..+0x8ac` (`[0x115]+0,+4`) | **A: count + flag** | `0` |
| **`+0x8b0` (`[0x116]`)** | **parallel array B: data ptr** | `0`; cleared by dtor |
| `+0x8b8..+0x8bc` (`[0x117]+0,+4`) | **B: count + flag** | `0` |
| **`+0x8c0` (`[0x118]`)** | **parallel array C: data ptr** | `0`; cleared by dtor |
| `+0x8c8..+0x8cc` (`[0x119]+0,+4`) | **C: count + flag** | `0` |
| `+0x8d0..` (`[0x11a..]`) | free-list link slot | reused by `FUN_14032e960` as the next-pointer when entry sits in pool |
| `+0x2a0` (`[0x54]`) byte | "fully initialized" | set to `1` at end of ctor |

**Total minimum size:** the dtor walks `[0x114..0x119]` and the
acquire helper uses `[0x11a]` for free-list link, so the allocation
size is at least **`0x8d0` bytes** and almost certainly rounded up to
**`0x900`** for the pool. `# TODO: confirm` against `oCMetaClass`
size record once the hero MetaClass is located.

### Counted `&DAT_140eb46d0` sentinels in the ctor body

`grep -c 'DAT_140eb46d0' FUN_1403143b0__0x1403143b0.c` → **27** direct
hits + **2** more inside `FUN_1406d3ac0` (the inline UI spawner) =
**29 named slots total**. Categorized:

| Group | Count | Owner pointer | Inferred semantic |
|---|---|---|---|
| Pre-ability pair (`[0x57]/[0x59]` and `[0x5e]/[0x60]`) | 4 | `DAT_141447250` | **idle / locomotion animation IDs** (2 pairs) |
| Ability block × 4 (`[0x65..0x9c]`) | **12** | `DAT_141446e18` | **4 abilities × {name A, name B, desc key}** — A is likely the power id, B the upgraded variant, desc the i18n key |
| Standalone (`[0x9d]`) | 1 | (none) | **base entity / model ref** |
| UI spawner pair (inside `FUN_1406d3ac0`) | 2 | `DAT_141446f38` | **portrait / select-screen UI spawn** |
| Melody/talent × 4 (`[0xbb..0xd6]`) | 8 | `DAT_141447250` | **4 melodies (or 4 talent trees) × {name, alt}** |
| Late slot (`[0xfd]/[0xff]`) | 2 | `DAT_1414470f0` | **voice bank / sound bank** |

= 4 + 12 + 1 + 2 + 8 + 2 = **29** ✓

The three "owner pointer" globals (`DAT_141447250`, `DAT_141446e18`,
`DAT_1414470f0`, `DAT_141446f38`) are `oCMetaClass*` records for the
respective ID types (animation, power, sound, UI). They tell the asset
loader **which library to look the name up in** when the cooked record
provides a string. The "Hash = `0x80000000`" sentinel marks the slot
as unresolved; the loader replaces it with the real FNV-1a hash and
swaps the ptr for a pooled string once it resolves the ID.

> `# TODO: confirm` — the per-owner mapping is inferred from
> *position* in the layout (animation pairs come before abilities,
> abilities before melodies/talents) and *count* (4 abilities ×
> 3 names matches Ravenswatch's per-hero ability roster).
> Confirm by dumping a vanilla hero record once the loader is
> instrumented.

## `oCDtHeroDefinition` dtor walk — `FUN_140314930` (1020 B)

The dtor exhibits exactly the parallel-pointer-array pattern the brief
flagged. Three independent arrays:

```c
A : ptr=[0x114], count=[0x115], cap_flag=[0x115]+4 at +0x8ac
B : ptr=[0x116], count=[0x117], cap_flag=[0x117]+4 at +0x8bc
C : ptr=[0x118], count=[0x119], cap_flag=[0x119]+4 at +0x8cc
```

For each, the loop body is the standard
`for i in 0..count: if entry: ((*entry).vftable)[8](entry); ((*entry).vftable)[0x10](entry, 1)` —
i.e. each entry is a polymorphic owning pointer with a virtual
destructor + scalar-deleting dtor. The "extra" `+0x8ac/0x8bc/0x8cc`
field is the *capacity-allocated* flag — when set, the buffer itself
is `free()`-equivalent-released.

Following the array-clears, the dtor descends through the inline
sub-records in reverse-init order:

| Dtor call | Field hit |
|---|---|
| `FUN_14067ea10([0x105])` | `oCGameLockSettings` complex (matches `FUN_1400c76a0` ctor) |
| `FUN_1402044f0([0xfd])` | named-slot release (portrait/voice) |
| `FUN_1402106e0([0xfa])` | **another 0x38-stride vector** (variable-length, NOT one of A/B/C) |
| `_eh_vector_destructor_iterator_([0xd7], 0x38, 5, FUN_140114920)` | the 5-entry fixed vector at `+0x6b8` |
| 4× `FUN_140114920([0xd0])..([0xbb])` | melody/talent name slots |
| `FUN_1400c6660([0xa0])` | UI spawner (`FUN_1406d3ac0` body) |
| `FUN_1400c6a50([0x8f]..[0x65])` | ability blocks 4..1 |
| 2× `FUN_140114920([0x5e],[0x57])` | animation name slots |
| `FUN_1401334e0([0x4e])` | `oCDtDefinition` body cleanup |
| `FUN_140503ed0([0xa])` | `oIResource` resource-path cleanup |

The dtor finally restores `[0x51] = oIGameProfileDataOwner::vftable`,
`[0]` back through `oCDtDefinition::vftable → oIResource::vftable →
oISerializable::vftable` (mirror of ctor).

## `Register_SkillProfileDataSettings` — `FUN_140192330` (464 B + xrefs)

The visible function body only sets up the parent UID `0x186adbdf`,
size `0xd0`, factory `FUN_1403122f0`. The `oCDtHeroDefinition` name
string at `0x140eddd78` is referenced **twice** from data at
`0x140192f21` / `0x140192f28` — i.e. inside the **field-schema table**
that the registrar emits for `SkillProfileDataSettings`. The two
references are the **field-type-name pointer** for one (or two)
nested-record fields in the schema.

This is consistent with the registrar pattern documented in
[`../MOD_HOOKS.md` "Schema-declarer pattern"](../MOD_HOOKS.md#schema-declarer-pattern-confirmed):
`SkillProfileDataSettings` declares a typed field "hero_definition"
of type `oCDtHeroDefinition*` (or `oCDtHeroDefinition[]`) in its
schema. The deserializer for `SkillProfileDataSettings` therefore:

1. Reads the parent's `0xd0`-byte preamble.
2. Hits the nested field marker → looks up `oCDtHeroDefinition` by
   name (not by UID).
3. Calls `FUN_1403143b0` to construct it inline.
4. Streams the named-slot values (animation/power/talent/melody/voice
   IDs) into the appropriate offsets, replacing `&DAT_140eb46d0`.
5. Streams the variable-length arrays at `[0x114]/[0x116]/[0x118]`.

**The hero library is populated by this nested deserialization.** The
acquire helper `FUN_14032e960` pulls an entry off the free list at
`+0x170` of the library, runs the ctor on it, and links it via the
library's `+0x180` critsec. The caller of `FUN_14032e960` (the parent
deserializer) then fills in the named-slot values from its own byte
stream.

## Library singleton — *still missing*

The `oCTLibrary<oCDtHeroDefinition>` singleton **address** is the one
piece of metadata we still need. Search criteria:

- The dtor `FUN_14032deb0` is reached only via `FUN_14032e1e0` (the
  scalar-dtor thunk). `FUN_14032e1e0` itself is referenced exclusively
  as a vftable slot (slot 0 of the library's own vftable).
- The library vftable address `oCTLibrary<class_oCDtHeroDefinition>::vftable`
  is referenced in only one C file (the dtor itself). The static-init
  function that does `_DAT_<addr> = vftable; InitializeCriticalSectionAndSpinCount(_DAT_<addr>+0x118, ...);`
  is **not** named.
- Hint: every other `oCTLibrary` singleton uses the form
  `oCTLibrary_<T>__static_init` at a fixed `FUN_14004????` or
  `FUN_140048???` address (see [`../MOD_HOOKS.md` "MCP-confirmed engine internals"](../MOD_HOOKS.md#mcp-confirmed-engine-internals-live-re)).
  A grep for `atexit(&LAB_140e<???>)` callbacks adjacent to other
  library inits should turn up the hero one.

Until that singleton is located, **runtime injection of new heroes
through the library directly is not possible**. The path that does
work is via the parent `SkillProfileDataSettings` record: emit a cooked
asset containing one of those (with UID `0x186adbdf`) and let the
normal level-load deserializer build the hero for us.

## Insertion recipe (cooked-asset path)

1. **Create the parent settings record.** Allocate `0xd0` bytes,
   write UID `0x186adbdf` in the first 4 bytes of the cooked record
   header. The factory `FUN_1403122f0` will be invoked at load time
   to set the display name.
2. **Embed the hero.** The parent's schema declares a nested
   `oCDtHeroDefinition` field. After the parent preamble, emit the
   hero body in the layout above — most importantly:
   - Animation names (2 pairs of `string,u32_hash`) at the
     `[0x57]/[0x59]/[0x5e]/[0x60]` slots.
   - 4 ability blocks at `[0x65]/[0x73]/[0x81]/[0x8f]`, each carrying
     two name strings + a description i18n key.
   - 4 melody/talent name pairs at `[0xbb]/[0xc2]/[0xc9]/[0xd0]`.
   - Portrait/voice/sound-bank name at `[0xfd]`.
   - Standalone model ref at `[0x9d]`.
3. **Variable-length arrays.** Append the lengths + the actual entries
   for arrays A (`[0x114]`), B (`[0x116]`), C (`[0x118]`) and for the
   `+0xfa` 0x38-stride vector. **What `A/B/C` contain is not yet
   confirmed** — most likely powers, talents and melodies as full
   nested records (each being its own definition-typed payload). The
   matching `oCDtPowerDefinition` / `oCDtTalentDefinition` /
   `MelodyDefinition` classes are registered elsewhere
   (`MelodyDefinition` library singleton is at `0x1414129c0`).
4. **Text bank.** Emit one i18n entry per ability description key
   (4 entries minimum) plus one for the hero's display name. Use the
   `RSMM_<modid>_<heroid>_<slot>` key convention from
   [`../../SDK_V3.md` i18n](../../SDK_V3.md#i18n).
5. **Patch the hero pool.** The level-load orchestrator
   `LevelGs_StateLoadingResource_Load` reads
   `Map+0x720..0x728` (random hero pool) and `Map+0x738..0x748`
   (played hero pool) at stage 0 — your custom hero must be listed
   in at least one of those for it to be selectable in-run.

For the v3.0 SDK we don't have a clean way to splice new entries into
the random hero pool yet; the `clone-and-patch` model below stages the
asset and leaves the pool patch as a `# TODO` for the apply layer.

## Mapping to the v3 SDK builder

`emit()` writes a manifest under
`<out>/_pending_heroes/<hero_id>/hero.json` plus support files (text
bank, portrait copy, etc.) describing the pieces above. The apply
pipeline (next phase) translates the manifest into either:

- a cooked asset that the engine loads through the normal
  `LoadUsedRscList_or_Archive` path, *or*
- a runtime patch the loader DLL applies once we have a stable address
  for `oCTLibrary<oCDtHeroDefinition>`.

Unknown fields fall back to **clone-from-base**: copy a vanilla hero
def's bytes verbatim and patch only the offsets above.

## See also

- [`../MOD_HOOKS.md`](../MOD_HOOKS.md) — registry / library vftable
  ABI shared by every kind, hero notes in "Heroes" section, and
  status note in "Hero library — still partially unknown".
- [`../GHIDRA_MCP.md`](../GHIDRA_MCP.md) — live RE harness.
- [`items.md`](items.md) — sister doc for the magical-object kind;
  follow the same `clone-and-patch → schema mining` progression.
- `docs/_re/out/decompiled_all/0314/FUN_1403143b0__0x1403143b0.c` —
  raw hero ctor.
- `docs/_re/out/decompiled_all/0314/FUN_140314930__0x140314930.c` —
  raw hero dtor.
- `docs/_re/out/decompiled_all/0192/FUN_140192330__0x140192330.c` —
  raw `Register_SkillProfileDataSettings`.
- `docs/_re/out/decompiled_all/0312/FUN_1403122f0__0x1403122f0.c` —
  `SkillProfileDataSettings` schema callback.
