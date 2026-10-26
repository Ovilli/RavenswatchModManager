# Symbol identities for Ravenswatch b9c3642884a8

Checked against executable SHA-256
`b9c3642884a8f3a463782f36c9a3a62bc14c88105315220c733fe6c2229ba904`,
preferred image base `0x140000000`, on 2026-10-25. Addresses below are
preferred-base addresses, not process addresses observed in a running game.

The verification used an existing Ghidra 12.1.4 analyzed snapshot with
`-readOnly -noanalysis`, selected decompilations and cross-references, RTTI,
and focused PE/Capstone byte queries. Both program metadata and the input
executable were checked against the SHA-256 above. No game execution,
runtime hooks, whole-program decompilation, or pattern regeneration was used.

## Serializer mappings that identified registrars

`CustomFlagList_Serialize` previously pointed to `0x140181f90`. That function
registers `oCCustomFlagList` (UID `0x15a9d9be`); it does not serialize an
instance. The serializer is `0x140668a70`, slot 3 of RTTI-identified
`oCCustomFlagList` vftable `0x140efe050`. Its body delegates to
`0x14066bb60(reader, this+8)` and tests the returned byte against 1.

`CustomFlagFilter_Serialize` at `0x140182180` likewise registers
`oCCustomFlagFilter` (UID `0x15a9d9bf`). The UID locator identifies the
registrar, so it has been removed. This pass does not claim a replacement
serializer address for that entry; its historical raw address is retained
only as an explicitly rejected lead.

Both entries are demoted to `unverified`. Generated resolver keys are omitted.
**Before publishing a matching pattern DB, remove its obsolete semantic keys
`CustomFlagList_Serialize` and `CustomFlagFilter_Serialize`.** The existing
validation gate correctly rejects a DB that still contains either key for a
demoted symbol. This PR does not change or regenerate the separately published
pattern DB. An already shipped loader using an older DB is not repaired by
changing the canonical map alone.

## Newly located identities

These 16 entries retain `unverified` status. Static identity is useful for
research and subsequent pattern recovery, but does not establish a working
resolver pattern or a calling convention.

| Symbol | Address | Independent support |
|---|---|---|
| EnemyCamp_Stage3Filter | `0x1403152a0` | Tier `+0x2e0`, minimum `+0x2dc`, flags `+0x2c0`, tribe `+0x318`, weight filtering; called after the tier selector copies a tribe roster. |
| Enemy_RuntimeSpawnPicker | `0x14033a1c0` | Enumerates enemy class registry, filters candidates, weighted-picks, resolves entity resource at `+0x288`, appends spawn data. |
| Entity_AllocInstance | `0x14068f580` | Free-list pop or virtual construction at `+0x50`; links live list; spawn-all caller supplies resource `+0x18`. |
| Id_HashString | `0x1405281b0` | CRC table `0x141436c10`, lazy guard `0x141436bf3`, initial `0xffffffff`, returns `NamedEvent_Id_FromCrc(0, ~crc)`. |
| LevelObject_DestroyVectors | `0x140476f00` | Destroys entries of `+0x80/count+0x88`, then `+0x18/count+0x20`, without per-entry null checks. |
| MagicalObjectPool_SourceLookup | `0x140253ea0` | Compares source GUID qwords `+0x88/+0x90`, scans runtime vector, finds MagicalObjectData component, matches component source pointer. |
| Netcode_EntityReplSetup | `0x140720350` | Slot 28 of RTTI `oCEntityCpntNetwork` vftable `0x140f773f8`; manager at context `+0x10`, role at manager `+0xf8`; mastership diagnostic naming Host/HostUnique. |
| Profiler_GetThreadScopeStack | `0x1405220f0` | TLS `+0x148`, main-thread stack `0x141447cf0`, lazy worker allocation; RAX and caller scope pushes confirm pointer return despite inferred `void`. |
| StringVector_Serialize | `0x14066bb60` | Called by actual CustomFlagList serializer; length and `0x18`-byte cached-ID/string entries; legacy serialized-object envelope. |
| MetaClass_DestructInPlace | `0x1401a1e80` | Registrar ops `+0x90` callback; clears EDX and tail-jumps through object vtable slot 2. |
| MetaClass_GetObjectClass | `0x1401b21a0` | Descriptor `+0x80` callback; tail-jumps through slot 0; CustomFlagList slot 0 returns its registered descriptor. |
| MetaClass_DestructInPlace_Slot0 | `0x1401a3880` | Registrar ops `+0x90`; clears EDX and tail-jumps through slot 0; BasicDamage slot 0 destructor frees only when flag bit 0 is set. |
| MetaClass_Construct_Zero16 | `0x1401a2030` | Zeros two qwords; size-16 oCBox2 registrar stores it in construct slot ops `+0x80`. |
| MetaClass_Construct_Zero8 | `0x1401a1ec0` | Zeros one qword; size-8 oCFloatInterval registrar stores it in construct slot ops `+0x80`. |
| StringFormat_ArgString | `0x14052a050` | Literal `%` path, `f` quoting, `U` uppercase, `u` lowercase, default append; thunk `0x1402188d0`. |
| StringFormat_ArgPointer | `0x1402bd340` | Three-argument leaf loads pointer value, selects `0x%016p` unless spec starts `%`, tail-jumps to formatting helper. |

The small reflection and pointer-formatting leaves were undefined in the
snapshot. Their bytes and registrar/argument-routing references establish the
entry points without creating Ghidra functions. A separate four-argument
adapter at `0x1405101d0` shares `0x%016p`; the string alone does not identify
the requested pointer formatter.

## Related corrections and limits

- The GUID lookup writes a matching **runtime entry** to its out argument,
  rather than the source definition described by the old note.
- The vector serializer's entries contain a cached ID plus an engine string;
  input recalculates that ID. Its compatibility envelope was omitted from the
  earlier plain-string-vector description.
- The string hasher consumes an engine string descriptor in this body. A raw
  C-string ABI is not established.
- `Reward_GenerateAndDistribute` at `0x1401e3340` is the SAME FUNCTION as
  `Reward_InitAllRewards`: seeded roll and candidate gate, not a sibling
  registrar. `UiController_UnbindComponent` at `0x1403469e0` is minimap
  controller slot 6 and clears the field slot 5 fills. These two previously
  established corrections also retain `unverified` status.
- `Entity_FindMagicalObjectComponent` remains unresolved as a distinct routine.
  The pool lookup calls generic `Entity_FindComponentByType` at `0x1406e19a0`
  with `oCDtEntityCpntMagicalObjectData` descriptor `0x141470688`; spawn-all also
  uses the generic routine with `oCDtEntityCpntMagicalObject` descriptor
  `0x141470db8`. No new alias is asserted.
- `MagicalObjectPool_Grow` remains unresolved: the runtime vector uses generic
  reserve `0x14014db80` and insertion `0x14014e030`. The old note cannot choose
  between those operations or establish another pool-specific routine.

The older note updates on referenced/unreferenced globals describe bounded
static searches. References alone do not establish a global's type; missing
direct references do not exclude indirect use. No global address was guessed.

The loader's resolver and ABI gates remain relevant. These mappings are
research evidence and must not be promoted solely because a decompiler's
parameter count agrees with a handwritten signature.
