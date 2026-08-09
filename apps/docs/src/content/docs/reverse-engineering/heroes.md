---
title: Heroes
description: Why a hero definition has no class UID, what its 29 named slots hold, and how the runtime hero controller differs from the definition that builds it.
---

:::note
Status: Tier-1 RE backing `src/rsmm/sdk/kinds/heros.py`, from live Ghidra MCP +
headless decompilation. Fields marked *unconfirmed* need verification before byte
emission. A **net-new hero is the hardest content kind**; a reskin works today.
:::

Heroes are the hardest playable kind because `oCDtHeroDefinition` has **no
registered class UID** — it lives as a nested definition inside a parent
`SkillProfileDataSettings` record. The hero is created and destroyed by the
*parent's* deserializer, not by a top-level factory lookup.

## The chain

```
SkillProfileDataSettings   (UID 0x186adbdf, size 0xd0, factory FUN_1403122f0)
    |  embeds (typed field)
    v
oCDtHeroDefinition         (no UID, ctor FUN_1403143b0, >= 0x900 bytes)
    |  named slots resolve through
    v
oCTLibrary<oCDtHeroDefinition>     (dtor FUN_14032deb0, acquire FUN_14032e960)
                                   (singleton address NOT located — see below)
```

`SkillProfileDataSettings` derives from `oISerializable` (UID `0x1da16c`).

| Class | UID | Size | Ctor | Dtor |
|---|---|---|---|---|
| `SkillProfileDataSettings` | `0x186adbdf` | `0xd0` | registrar `FUN_140192330`, schema cb `FUN_1403122f0` | — |
| `oCDtHeroDefinition` | **none** | **≥ `0x900`** | `FUN_1403143b0` | `FUN_140314930` |
| `oCTLibrary<oCDtHeroDefinition>` | — | — | acquire `FUN_14032e960` | `FUN_14032deb0` |

## The 29 named slots

The ctor writes a long sequence of named-slot tuples plus two sub-record ctors.
Each slot is `{char* name = &DAT_140eb46d0 (empty sentinel), u32 hash =
0x80000000 (unresolved), u32 flag}`, most with an **owner pointer** naming the
library the name resolves in.

| Group | Slots | Owner | Inferred semantic |
|---|---|---|---|
| Pre-ability pairs (`+0x2b8`, `+0x2c8`, `+0x2f0`, `+0x300`) | 4 | `DAT_141447250` | idle / locomotion animation IDs |
| Ability blocks × 4 (`+0x328`, `+0x398`, `+0x408`, `+0x478`) | **12** | `DAT_141446e18` | 4 abilities × {name A, name B, description key} — A likely the power id, B the upgraded variant |
| Standalone (`+0x4e8`) | 1 | (none) | base entity / model ref |
| UI spawner pair (inline, `+0x500..+0x5d8`) | 2 | `DAT_141446f38` | portrait / select-screen UI spawn |
| Melody/talent × 4 (`+0x5d8`, `+0x610`, `+0x648`, `+0x680`) | 8 | `DAT_141447250` | 4 melodies (or talent trees) × {name, alt} |
| Late slot (`+0x7e8`) | 2 | `DAT_1414470f0` | voice bank / sound bank |

Total 29. The owner globals are `oCMetaClass*` records for the respective ID types
(animation, power, sound, UI) — they tell the asset loader **which library to look
the name up in**. Hash `0x80000000` marks the slot unresolved; the loader replaces
it with the real hash and swaps the pointer for a pooled string once the ID
resolves.

*The per-owner mapping is inferred from position and count (4 abilities × 3 names
matches the per-hero ability roster), not confirmed from a dumped record.*

Other notable offsets: `+0x288` installs `oIGameProfileDataOwner` with a 16-byte
GUID from `CoCreateGuid`; `+0x6b8..+0x7d0` is a fixed vector of 5 × 0x38-byte
entries; `+0x7d0` is another `{ptr, count, cap}` collection of 0x38-byte entries;
`+0x828..+0x8a0` is an `oCGameLockSettings` + event-listener + flag-list complex
(the unlock condition); `+0x2a0` is set to 1 at the end of the ctor as a
"fully initialized" marker.

### Three parallel arrays

The dtor shows the parallel-pointer-array pattern plainly:

```c
A : ptr=+0x8a0, count=+0x8a8, cap_flag=+0x8ac
B : ptr=+0x8b0, count=+0x8b8, cap_flag=+0x8bc
C : ptr=+0x8c0, count=+0x8c8, cap_flag=+0x8cc
```

Each loop body is the standard
`for i in 0..count: entry->vftable[8](entry); entry->vftable[0x10](entry, 1)` —
every entry is a polymorphic owning pointer with a virtual destructor. The extra
field is the capacity-allocated flag; when set, the buffer itself is released.

Allocation size is therefore at least `0x8d0`, almost certainly rounded to `0x900`
for the pool.

## How the hero gets built

`Register_SkillProfileDataSettings` sets up UID `0x186adbdf`, size `0xd0`, factory
`FUN_1403122f0`. The `oCDtHeroDefinition` name string is referenced **twice from
data** inside the field-schema table the registrar emits — i.e.
`SkillProfileDataSettings` declares a typed nested field of type
`oCDtHeroDefinition`. So the parent deserializer:

1. Reads the parent's `0xd0`-byte preamble.
2. Hits the nested field marker → looks up `oCDtHeroDefinition` **by name, not by
   UID**.
3. Calls the hero ctor to construct it inline.
4. Streams the named-slot values into the right offsets, replacing the sentinel.
5. Streams the variable-length arrays A / B / C.

The acquire helper pulls an entry off the library's free list at `+0x170`, runs
the ctor, and links it via the library's `+0x180` critical section.

## The missing library singleton

The `oCTLibrary<oCDtHeroDefinition>` singleton **address** is the one piece of
metadata still missing. The dtor is reached only via a scalar-dtor thunk that is
itself referenced exclusively as slot 0 of the library's own vftable, and the
static-init that does `_DAT_<addr> = vftable;
InitializeCriticalSectionAndSpinCount(...)` is unnamed — likely inlined into a
larger group init.

**Until that singleton is located, runtime injection of new heroes through the
library is not possible.** The path that does work is the parent record: emit a
cooked asset containing a `SkillProfileDataSettings` and let the normal level-load
deserializer build the hero.

## Insertion recipe (cooked-asset path)

1. **Parent settings record** — `0xd0` bytes, UID `0x186adbdf` in the cooked
   header. The factory runs at load time to set the display name.
2. **Embed the hero** in the layout above: animation name pairs, 4 ability blocks
   (two name strings + a description key each), 4 melody/talent name pairs,
   portrait/voice slot, standalone model ref.
3. **Variable-length arrays** — lengths + entries for A, B, C and the 0x38-stride
   vector. **What A/B/C contain is not confirmed**; most likely powers, talents
   and melodies as full nested records.
4. **Text bank** — one i18n entry per ability description key plus the hero's
   display name, using the `RSMM_<modid>_<heroid>_<slot>` key convention.
5. **Hero pool** — the level-load orchestrator reads `Map+0x720..0x728` (random
   hero pool) and `Map+0x738..0x748` (played hero pool) at stage 0. A custom hero
   must be listed in at least one to be selectable in a run. There is no clean
   splice for this yet.

Unknown fields fall back to **clone-from-base**: copy a vanilla hero's bytes
verbatim and patch only the offsets above.

## The runtime hero object

Everything above is the **definition** — static data used to *build* a hero. At
runtime the playable hero is a different object: `oCDtEntityCpntHeroController`
(`HeroController_Ctor`), the hero controller **component** of the entity. This is
what the loader captures as the "hero pointer" for `R.entity` / `R.combat`.

| Offset | Field |
| --- | --- |
| `+0x15c8` | current HP (f32, plain mirror) |
| `+0x15cc` | max HP (f32) |
| `+0x15d0` | missing-health ratio (f32, default 1.0) |
| `+0x15d4` | ratio divisor (f32, default 0.5) |
| `+0x1d80` | HUD HP-mirror pointer (local player only) |
| `+0x1fc..+0x220` | 10-slot ability/input config (int tags `{0,1,1,1,2,1,1,1,1,3}`) |

Controller size ≈ `0x1e40`.

**Most hero stats are not plain fields.** They are
`oe::EntityCpntValueSignal<bool|int|float|oCVec3>` sub-components — the ctor builds
dozens. Writing a signal fires a change notification on the gameplay bus, which is
*why* stat changes surface as named events. HP is the exception: it is additionally
mirrored to the plain f32 at `+0x15c8` for the hot path, which is exactly why
`R.combat` can read and write HP directly while energy, cooldowns and speed live
inside signal objects with no fixed plain-float offset. Reaching those is a
per-signal RE job, not a constant lookup — see
[Stats & XP](/reverse-engineering/stats/) for the keyed store that covers most of
them.
