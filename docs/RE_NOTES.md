# Ravenswatch cooked-format reverse engineering notes

Working notes for the modding pipeline (uncook ↔ cook). Living document — not a
spec. Update as schemas are filled in.

## Status

| Stage | Class / piece | Status | Owner file |
|-------|---------------|--------|-----------|
| 1 | Corpus dump (25 classes / 21k files) | done | `data/cooked_classes.json` |
| 2 | vtable + Serialize VA per class | done | `data/cooked_class_map.json` |
| 3 | Container codec (parse + emit, round-trip) | done | `src/rsmm/engine/cooked.py`, `tests/test_cooked_roundtrip.py` (450/450) |
| 4 | `oCTexture` schema (v1.14) | pending | — |
| 5a | `oCGeometry` container fields (v1.2) | done (this doc) | — |
| 5b | `oCMesh` submesh payload (was assumed `oCSubMesh`) | done (this doc) | — |
| 5c | `oCMeshBuffer` outer + unique-buffer path (v1.4) | done (this doc) | — |
| 5c.i | Per-stream `oSTriangleMesh`/`oCVec3VertexLayer` data layout | partial (this doc) | — |
| 5d | Per-instance / bone matrix list at +0x98 | partial (this doc) | — |
| 5e | `oCSkeleton` sub-object at +0x80 (was assumed index buffer) | pending | — |
| 6+ | Encoders & glTF bridge | partial (provisional decoder writable; encoder TBD until 5c.i closes) | — |

## Container codec

Both Type A (`.yqz/.gen`, `.tpi/.dxt`, `.zux/.nrm`) and Type B (stream
containers like `oCGameStream`) round-trip byte-stable. See module docstring
in `src/rsmm/engine/cooked.py`. Sections in the codec are raw payload blobs —
no per-class interpretation.

Asset containers carry **no CRC32**. CRC32 is `.ob` save-file only (see
ravensmith for that variant; not implemented here).

## Stream-vtable convention (confirmed across all 25 classes)

Param 2 of every `Serialize(this, stream)` call is a stream object whose
vtable indices are stable engine-wide:

| Slot | Method | Purpose |
|------|--------|---------|
| `+0x10` | begin-section helper | nested BEGIN/END section bracket on disk |
| `+0x20` | `is_reading()` → char | branch reader vs writer (0 = reading) |
| `+0x60` | string | u32 length + UTF-8 bytes (no NUL terminator) |
| `+0x70` | u8 / bool | 1 byte |
| `+0x78` | f32 | 4-byte IEEE 754 |
| `+0x90` | u32 / i32 | 4 bytes |
| `+0xa0` | embedded sub-object | nested Serialize() of an oC* class |

Helper functions called by Serialize bodies:

- `FUN_1404fbea0(stream, scratch, class_uid)` — version-gate helper. Returns
  a small struct; `*(u32 *)(ret + 4)` = saved schema version. Used as
  `if version < N: read_default_else_skip; else: read_from_stream` per field
  for migration.
- `FUN_1401c8720(stream, this_ptr)` — TResourcePtr / smart-ptr serialize.
- `FUN_14010c960`, `FUN_140312360`, `FUN_140115cb0`, `FUN_1402068e0` —
  string construct / append / move helpers.

## Class taxonomy (from manifest)

| Class | UID | Cur. version | Body size range | Use |
|-------|-----|--------------|-----------------|-----|
| `oCTexture` | 0x000016f6 | 1.14 | 46 B → 17.6 MB | All textures (.tpi/.zux/.yqz) |
| `oCGeometry` | 0x000016b8 | 1.2 | 200 B → 4.1 MB | 3D meshes |
| `oCMaterial` | 0x000016be | 1.28 | 159 B → 364 B | Materials |
| `oCAnimation` | 0x0000159d | 1.5 | 198 B → 35 KB | Animations |
| `oCCollisionMesh` | 0x0030986b | 1.3 | 1 KB → 32 KB | Collision |
| `oCEntitySettingsResource` | 0x16f5f7a3 | 1.0 | 49 B → 5 KB | Entity defs |
| `oCScheduledVfxSettings` | 0x0052992b | 1.2 | 22 B → 74 B | VFX timelines |
| `oCGameStream` | 0x014c31bf | 1.1 | 24 B → 22 KB | Level streams |
| `oCDt*Definition` (10 kinds) | various | various | small | Game data |

Full table + sample paths in `data/cooked_classes.json`. Vtable + Serialize
addresses in `data/cooked_class_map.json`.

## `oCGeometry` (v1.2) — partial schema

Decompile of `FUN_14064b0c0` (Serialize). Cooked file has TWO sections (one
from `oIResource::Serialize` parent + one from this).

### Section 0 — `oIResource::Serialize` output

4 bytes. Always observed as `00 00 00 00` in sampled v1.2 files. Likely a
resource-flags u32. Schema TBD (decompile of `oIResource::Serialize` at
vtable[3] of `oIResource`'s vtable, derivable from the same RTTI scan).

### Section 1 — `oCGeometry::Serialize` output

```
1. SubObject "bone/instance vector" at this+0x98
   - Read by FUN_14065a7c0(stream, this+0x98)
   - Layout:
       u32 zero_or_flags        (always 0 observed)
       u32 count                (or 0xAABB1111 marker for legacy schema)
       count * Element {
           f32 matrix[16]       (4x4 row-major transform, 64 B)
           lstring name_a       (u32 len + bytes, e.g. "Empty", "L_Locator")
           lstring name_b       (u32 len + bytes, often empty)
       }
   - When `count == 0xAABB1111`, a versioned header follows
     (string + 3 u32s) before the actual count.

2. u32 submesh_count       at this+0x90

3. u8 has_index_buffer     (computed write-side from this+0x80 non-null
                            AND *(this+0x80 +0xa0) != 0)

4. submesh_count * SubObject<oCSubMesh>  → vector at this+0x88
   (sub-object schema: TBD — see Stage 5b)

5. if has_index_buffer:
       SubObject<IndexBuffer>            → stored at this+0x80
       (schema: TBD — see Stage 5c)

6. version-gate (v >= 1):
       AABB { f32 xMin, yMin, zMin, xMax, yMax, zMax }   at this+0x68
       (confirmed via FUN_1404d4a60 = 6 consecutive f32 reads)

7. version-gate (v >= 2):
       struct { u32 = 0x01010000, u32 = 0x01010000, u8 = 1 }
       at local stack — looks discarded? May be migration flag set.
```

### Observed tiny-mesh payload (section 1, 208 B)

`LMN_RrlhSwli_Msqv_Grbgiruv.hap.Kqrxqius.yqz` (342 B file, decoded name has
"Grbgiruv" → "Locators" — locator group, hence no submeshes/indices):

```
u32 leading_zero        = 0
u32 element_count       = 2
Element 0:
  matrix4x4 (64 B)      = mostly identity-ish with translation
  lstring "Empty"       (4+5)
  lstring ""            (4+0)
Element 1:
  matrix4x4 (64 B)
  lstring "Empty.001"   (4+9)
  lstring ""            (4+0)
[trailing bytes]        — 5b 5c 5d ... 01 01 00 00 01 01 01
                          (AABB tail + v>=2 trailing struct, mostly zero
                          since this asset has no submesh data)
```

This confirms the bone/instance vector model. Larger meshes will have
submesh sub-objects + index buffer payload after the element vector.

## Sub-mesh class identification (Stage 5b — name correction)

The class embedded inside `oCGeometry` at offset `+0x88` (the submesh
std::vector) is **NOT** `oCSubMesh`. It is **`oCMesh`** (RTTI mangle
`.?AVoCMesh@@`, class UID `0x000016c0`).

Discovery: at the factory call in `oCGeometry::Serialize`,
`FUN_14049f0e0(&DAT_1414657e0, &DAT_14143ca10, ...)` invokes the resource
manager pinned to a `oCTLibrary<oCMesh>` instance. Verified by static
initializer at `0x140098620`:

```c
_DAT_1414657e0 = oCTLibrary<class_oCMesh>::vftable;
```

The second arg `&DAT_14143ca10` is NOT a class name — it is a small struct
of two `std::string`s holding the literal text `">DYN"` (an "anonymous /
dynamic resource" sentinel — see `FUN_14049f0e0` early branch:
`if (length == 4 && memcmp(name, ">DYN", 4) == 0) ...`).

RTTI search confirms there is no `oCSubMesh`, `oCSubmesh`,
`oCMeshSection`, or `oCGeometrySubMesh` symbol in the binary.

Related sub-object classes discovered while tracing this:

| Class | UID | Cur. version | Manager VA | Serialize VA | Role |
|-------|-----|--------------|------------|--------------|------|
| `oCMesh` | `0x000016c0` | 1.2 | `0x1414657e0` | `0x14064fdc0` | One per submesh inside `oCGeometry+0x88` |
| `oCMeshBuffer` | `0x000016c1` | 1.4 | `0x141465c80` | `0x140650a80` | Vertex+index buffer inside `oCMesh+0x70` |
| `oCMaterial` | `0x000016be` | 1.28 | `0x141465e30` | `0x14064c200` | Material at `oCMesh+0x68` (already resolved) |
| `oCSkeleton` | TBD | TBD | `0x14144af10` | `0x1405b4c40` | Sub-object at `oCGeometry+0x80` (was previously assumed to be an index buffer — wrong) |

All four were appended to `data/cooked_class_map.json`.

The `oCGeometry+0x80` correction matters: it is not an index buffer; the
mesh's index data lives inside `oCMeshBuffer`. The `+0x80` slot is the
mesh's optional skeleton (rig).

## `oCMesh` (v1.2) — schema

Decompile of `FUN_14064fdc0` (Serialize). One `oCMesh` instance per submesh
of the parent `oCGeometry`. Version-gate UID `0x16c0` is used as the
identity for `FUN_1404fbea0` lookups.

In-memory fields touched by Serialize:

| Offset | Meaning |
|--------|---------|
| `+0x68` | `TResourcePtr<oCMaterial>` (or owned `oCMaterial` if unique) |
| `+0x70` | `TResourcePtr<oCMeshBuffer>` (the actual vertex / index data) |
| `+0x78` | `std::string` — appears in v >= 2 only (name? optional tag?) |

Wire layout (writer / reader symmetric), in stream order:

```
1. bool material_is_default            (vtbl +0x70 — 1 byte)
     write-side computed as:
       material_is_default = ((*(this+0x68)) == NULL ||
                              (*(*(this+0x68)) + 0x48) == NULL)

2. branch on material_is_default:
   - true (no material / default):
       material is the engine default; nothing extra written.
   - false:
       branch on material's lifecycle:
       - shared resource ref (refcount > 1):
           TResourcePtr<oCMaterial> {
              lstring class_or_type_name
              lstring resource_path_or_id
           }                              (FUN_1401c8720 — 2x vtbl +0x60)
       - unique / inline (refcount == 1):
           SubObject<oCMaterial>          (vtbl +0xa0)
       - many-material edge-case:
           SubObject written into a chained binary stream via
           FUN_1404fd1c0 (oCBinarySaver + oCMemoryBinaryStream).
           Rarely seen — schema TBD.

3. SubObject<oCMeshBuffer>               (vtbl +0xa0)
     The vertex / index buffer for this submesh.

4. version-gate (v >= 2):
       lstring tag_or_name                (vtbl +0x60 at this+0x78)
     For v1.2 files this field is always present (current shipped
     version is 1.2 across all observed corpus).
```

Cross-checks against a real sample (see "Sample" below) suggest the
material/meshbuffer ordering is: material subobject bracket first,
meshbuffer subobject bracket second.

## Stream-vtable convention update (verified during Stage 5c)

While tracing `oCMeshBuffer::Serialize` and the named-instance reader
`FUN_1404cb570` against a real sample, two additional vtable slots and one
side-effect were nailed down:

| Slot | Method | On-disk emission (binary stream) |
|------|--------|----------------------------------|
| `+0x38` | schema annotation (takes a string like `"typeof(oCTVector<t_Object>)"`) | **0 bytes** — annotation only |
| `+0x40` | blob read/write (`(stream, data_ptr, byte_count, "Bytes")`) | **`u32 byte_count`** prefix, then `byte_count` raw bytes |
| `+0x60` | `lstring` (length-prefixed UTF-8 string) | `u32 len`, then `len` bytes (no NUL) |
| `+0x68` | `u8` (separate from the bool slot at `+0x70`; used for typed flags/modes) | 1 byte |

This rewrites the prior assumption that `+0x40` was a raw `count*N` blob
with no header. The byte-prefix from `+0x40` is what shows up as the second
`u32` we kept seeing inside vertex-stream payloads (= `count * stride`).

## `DAT_1412efa50` — engine default-buffer signature

A 64-byte (16-float) block at `0x1412efa50` in `Ravenswatch.exe`. Reading
the bytes via `pefile`:

```
1.0  0.0  0.0  0.0
0.0  1.0  0.0  0.0
0.0  0.0  1.0  0.0
0.0  0.0  0.0  1.0
```

**It is the 4x4 identity matrix.** `oCMeshBuffer::Serialize` uses
`memcmp(&DAT_1412efa50, *(this+0x78)+0x10, 0x40)` to test whether this
buffer's stored transform equals the engine's identity-default. If yes
(plus `*(this+0x80) == 1`), the buffer is treated as shared-default and
`unique_flag` is written as `0`; otherwise `unique_flag = 1` and a full
unique buffer is written.

## `oCMeshBuffer::Serialize` (v1.4) — full outer schema

Decompile of `FUN_140650a80`. Confidence: **high** for the outer envelope;
**medium-low** for the per-stream payload (see Stage 5c.i below).

### Parent prelude (written by the dispatch wrapper, not by `FUN_140650a80`)

```
u32 oIResource flags / reserved      (4 B)   — empirically 6 for our sample;
                                                value semantics still TBD
```

### Self body (`FUN_140650a80`)

```
1. u8  unique_flag                          (vtbl +0x70)
     write-side computed as:
       if (*(this+0x80) == 0) OR
          (*(this+0x80) == 1 AND
           memcmp(*(this+0x78)+0x10, IDENTITY_4x4, 64) == 0)
         unique_flag = 0
       else
         unique_flag = 1

2. version-gate (v < 4 — legacy path; not emitted by current shipping files):
     - acquire default oSTriangleMesh at this+0x68 via FUN_1404d22b0
       (= FUN_1404d7cc0 alloc + FUN_1404d2150 push with identity matrix)
     - read named-instance via FUN_1404cb570(*(this+0x68), stream, "<no name>")
   v >= 4 — current 1.4 path:
   if unique_flag == 0:
       ensure default mesh struct exists at this+0x68 (FUN_1404d7cc0
       allocates a stub `oSTriangleMesh`, FUN_1404d2150 pushes it with an
       identity per-draw matrix taken from DAT_1412efa50)
       read named-instance via FUN_1404cb570(*(this+0x68), stream, "<no name>")
   if unique_flag == 1:
       read full unique buffer via FUN_1404d1e30(this+0x68, stream)

3. AABB (v >= 1):
     FUN_1404d4a60(stream, this+0x90) — 6 consecutive f32 reads
     { f32 xMin, yMin, zMin, xMax, yMax, zMax }

4. f32 (v == 2 ONLY): vtbl+0x78(stream, local, 0) — value discarded on read.
   Absent for v >= 3 files.

5. f32 (v >= 3): vtbl+0x78(stream, this+0xc8, 0) — stored at this+0xc8
   (semantically a "level-of-detail factor" or "shadow-bias"-style scalar — TBD).
```

The `"<no name>"` literal is the **call-site argument** to `FUN_1404cb570`;
it is NOT written to disk by `FUN_1404cb570` itself. The named-instance
reader uses it as a default annotation label for error messages and in
text-stream mode only.

## `FUN_1404d1e30` (unique-buffer reader) — schema

Decompile reads:

```
u32 leading_flag = 1            (always 1 on disk — set by writer as a literal)
u32 stream_count                (number of vertex-stream sub-objects)
stream_count * SubObject<oCTStream>   (each via FUN_1404cb570(stream_obj, "<no name>"))

u32 draw_count                  (number of per-draw entries)
draw_count * {
    u32 stream_index            (index into the stream array above)
    f32 matrix[16]              (4x4 transform — 64 B)
}
```

The on-disk per-draw struct is `4 + 64 = 68 bytes`. In memory the layout is
0x50 (80 bytes) because the runtime caches the resolved `stream_ptr` at
+0x00 and stores the stream_index at a +0x04 cursor. On disk, only the
stream_index (u32) and matrix (16 f32) are serialized — total 68 B per draw.

## `FUN_1404cb570` — the named-instance reader

This is **not** `oCVec3VertexLayer::Serialize`. It is a generic serializer
for "stream / triangle-mesh" objects whose schema version is its OWN field
(`local_res10[0]`), independent of the surrounding class's version.

The current shipped version (set by the writer as `dword ptr [RBP + 0x6f], 0x7`)
is **7**. The third argument (a C-string like `"<no name>"`) is a label only,
not emitted to disk by this function.

### Layout for `ver == 7`, uncompressed mode (`*(param_1 + 0x49) == 0`)

```
u32 ver = 7                            (vtbl +0x90, always emits 7 on save)
u8  comp_mode at +0x49                 (vtbl +0x68)
                                         0 = uncompressed
                                         1 = quantized-20B-per-vertex
                                             (via FUN_1404c3440)
                                         2 = quantized-18B-per-vertex
                                             (via FUN_1404c3dc0)
[ comp_mode == 0 (uncompressed path): ]
  vtbl +0x38("typeof(oCTVector<t_Object>)")   — annotation, 0 bytes
  u32 count                            (= *(param_1 + 0x10); element count)
  u32 byte_size                        (= count * 0x30 — emitted by vtbl +0x40
                                         as its blob length prefix)
  byte_size bytes of element data      (stride 0x30 = 48 B per element;
                                         element layout TBD — see Stage 5c.i)

  Then a trailing tail:
  lstring annotation                   (vtbl +0x60 of an empty/symbolic string,
                                         observed empty in sample)
  (v >= 2) vector<ptr> at +0x38        (via FUN_14020d700; element stride 8 B
                                         = ptrs, each ptr serialized via
                                         vtbl +0xa8 = sub-object)
  (v == 4 only) 16 f32                 (a 4x4 matrix; absent for v == 7)
```

### Layout for older versions

- `ver == 1`: full default-case branch — includes tangent / binormal
  side-channel allocation (`FUN_1404c4f10`, `PTR_s_tangent_1412ef988`,
  `PTR_s_binormal_1412ef978`) and a sub-resource named "skinning"
  (`PTR_s_skinning_1412ef958`). This is where the `"tangent"` /
  `"binormal"` strings come from in older content. Not used by v1.4 files.
- `ver == 2`: just `FUN_1404d62e0` (vector of 0x30-byte elements with the
  same BEGIN-style versioning header as `oCTVector<t_Object>`).
- `ver in [3,4,5,6,7]`: the modern path described above. v < 5 still uses
  `FUN_1404d62e0`; v >= 5 switches to the typeof+u32+byte-blob form.

### Quantized vertex paths (`comp_mode == 1` or `2`)

These take a `local_res18` parameter passed down from the caller (`*(param_1 + 0x10)`).
For oCMeshBuffer's default-buffer call, the caller passes an `oSTriangleMesh`
where +0x10 holds the vertex count, so `local_res18` ends up being count.

- **mode 1** (`FUN_1404c3440`) — 20 bytes per vertex:
  - 3 * u16 quantized position (using mins/maxes from a header bbox)
  - 3 * u16 quantized normal (Lambert-style packing into 6 bytes)
  - 1 * u32 packed tangent + extras (`FUN_140516d70` produces it from f32x4)
  - On-disk header: 3 + 3 + 3 + 3 + 3 f32 (5 vec3 mins/maxes — 60 B), then
    count * 20 B = data.
- **mode 2** (`FUN_1404c3dc0`) — 18 bytes per vertex:
  - same as mode 1 but normal/tangent packed differently (octahedral?)
  - on-disk header: 3+3 f32 bbox + 2 f32 quant scales + extra u8 byte
    descriptors + 3+3+3 f32 mins/maxes (~72 B), then count * 18 B = data.

These quantized paths are produced by the engine cooker when the source
mesh has vertex data — they're the format used by skinned / static
geometry. The decoder needs to dequantize back to f32 for round-trip.

## Stage 5c.i — per-stream element layout (still partial)

The 48-byte element written by FUN_1404cb570's uncompressed path is the
in-memory "vertex" struct held by an `oSTriangleMesh` (or similar). 48 B
matches:
- `12 B position (f32x3)`
- `12 B normal   (f32x3)`
- `8  B uv0      (f32x2)`
- `4  B color    (u8x4)`
- `12 B tangent  (f32x3)`
  → 48 B total

…but the exact field order, signedness, and whether tangent is packed has
not been independently verified by reading f32 values out of the sample
yet. The sample's `oCMeshBuffer` is the default-buffer path with a stub
`oSTriangleMesh` (8 triangles, 24 indices, identity matrix) and shows
small per-vertex floats that *look* like a 48-byte format but could also
be the v=7 default with an inner array of indices + tail of vertices.
Marking as TBD — Stage 5c.i.

## `oCVec3VertexLayer` (v1.2) — schema

Decompile of `FUN_1404ddd80` (the self body). Parent serialize is
`oIVertexLayer::Serialize` at `FUN_1404ddb70`, which only writes one field:

### `oIVertexLayer::Serialize` (v1.0)

```
lstring name      (vtbl +0x60 at this+8 — the layer's textual name,
                   e.g. "binormal", "tangent", "position", "normal", ...)
```

### `oCVec3VertexLayer::Serialize` (v1.2, self body)

UID for `FUN_1404fbea0` version-gate lookup is `0xd43924b`.

```
[ v < 2 (legacy) ]:
  FUN_14012afd0(stream, this+0x18)
    — reads a length-prefixed std::vector<oCVec3>:
      u32 count
      count * { f32 x, f32 y, f32 z }    (12 B each)

[ v >= 2 (current) ]:
  u8 comp_mode at this+0x28              (vtbl +0x68)
       0 = uncompressed / fall through
       1 = quantized 8 B per vertex
       2 = empty (skip — schema returns 1, no data)

  comp_mode == 1:
    u32 count at this+0x20               (vtbl +0x90)
    FUN_1404d4550(this+0x18, count, 1)   — resize array to count
    FUN_1404b3d40(stream, this+0x18)     — read quantized stream:
      f32 bbox xMin
      f32 bbox xMax
      f32 bbox yMin
      f32 bbox yMax
      f32 bbox zMin
      f32 bbox zMax
      count * { u16 qx, u16 qy, u16 qz }  (6 B per vertex)
      (dequantization: f = qx / 65534.0 * (xMax - xMin) + xMin)

  comp_mode == 2:
    (no data — returns success immediately; in-memory vector left empty)

  comp_mode == 0:
    (v < 2 only) FUN_14012afd0  — legacy vec3 list (per above)
    vtbl +0x38("typeof(oCTVector<t_Object>)")  — 0 bytes
    u32 count at this+0x20                     (vtbl +0x90)
    resize array to count                       (FUN_140cb5f70 zero-fill)
    vtbl +0x40 blob:
      u32 byte_size = count * 12
      count * { f32 x, f32 y, f32 z }
```

The `name` lstring written by the oIVertexLayer parent identifies the
semantic ("binormal", "tangent", "position", "normal", "uv0", "color", ...).

### Sample verification (`binormal` side-channel, section 1 of our sample, 313 B)

Confirmed byte-stable parse:

```
0000: u32 oIResource prelude    = 7
0004: u32 lstring name len      = 8
0008: 8 bytes "binormal"
0010: u8  comp_mode             = 0    (uncompressed)
0011: u32 count                 = 24   (vertex count, at +0x20)
0015: u32 byte_size             = 288  (= 24 * 12, vtbl +0x40 blob prefix)
0019: 288 bytes = 24 * vec3(f32)
      vertex[0]  = (0.0, 1.6e-07, 1.0)
      vertex[1]  = (0.0, 1.6e-07, 1.0)
      ... (4 verts of same)
      vertex[4]  = (-1.0, 0.0, 0.0)
      ... (a few unit-vector reorderings — looks consistent with per-face
            tangent-space binormals of a unit cube's 24 corner vertices)
```

Total: `0x19 + 288 = 0x139 = 313 B` ✓.

Section 2 (`tangent`) follows the identical schema — 312 B total because
"tangent" is 7 chars not 8.

## `oIVertexLayer` (v1.0) — schema

```
lstring name      (vtbl +0x60 at this+8)
```

Trivially short; the bulk of the data lives in derived classes
(`oCVec3VertexLayer`, `oCVec2VertexLayer`, `oCVec4VertexLayer`,
`oCFloatVertexLayer`, `oCSkinning8VertexLayer`, `oCSkinning16VertexLayer`).

### Discovered VAs (Stage 5b/5c)

| Class | UID | Cur. version | Serialize VA | Parent |
|-------|-----|--------------|--------------|--------|
| `oIVertexLayer` | `0xd3e6496` | 1.0 | `0x1404ddb70` | `oISerializable` |
| `oCVec3VertexLayer` | `0xd43924b` | 1.2 | `0x1404ddd80` | `oIVertexLayer` |
| `oCVec2VertexLayer` | TBD | TBD | TBD | `oIVertexLayer` |
| `oCVec4VertexLayer` | TBD | TBD | TBD | `oIVertexLayer` |
| `oCFloatVertexLayer` | TBD | TBD | TBD | `oIVertexLayer` |
| `oCSkinning8VertexLayer` | TBD | TBD | TBD | `oIVertexLayer` |
| `oCSkinning16VertexLayer` | TBD | TBD | TBD | `oIVertexLayer` |
| `oSTriangleMesh` (internal) | n/a | n/a | n/a (uses `FUN_1404cb570`) | — |

The skinning / vec2 / vec4 / float layer classes share the same
parent-then-self pattern; their bodies are simpler variants of
`FUN_1404ddd80` with different element sizes (likely 8, 16, 4 B
respectively). Decompile pending.

## `oCSkeleton` (?) — TBD (Stage 5e)

Sub-object at `oCGeometry+0x80`. Was previously believed to be an "index
buffer" — that was wrong. Schema is fully TBD. Serialize VA = `0x1405b4c40`,
vtable VA = `0x140f53fc0`. Class UID still TBD (not seen in any cooked
class table yet — likely only present in skinned-mesh `.yqz` files).

## Sample dump: `3N/NqbglSwaq_1p1.hap.Kqrxqius.yqz` (2550 B, v1.2 oCGeometry)

Class table (from cooked container):

```
oCGeometry         id=0x16b8  v=1.2  parent=oIResource
oIResource         id=0x17b6  v=1.1  parent=oISerializable
oISerializable     id=0x1da16c v=1.0 parent=0xffffffff
oCMesh             id=0x16c0  v=1.2  parent=oIResource
oCMaterial         id=0x16be  v=1.28 parent=oIResource
oCShaderParamSet   id=0x2630f82 v=1.0 parent=oISerializable
oCMeshBuffer       id=0x16c1  v=1.4  parent=oIResource
oCVec3VertexLayer  id=0xd43924b v=1.2 parent=oIVertexLayer
oIVertexLayer      id=0xd3e6496 v=1.0 parent=oISerializable
```

Top-level cooked container sections (Type B, four sections):

| idx | bytes | content |
|-----|-------|---------|
| 0 | 12 | u32(2), u32(7), u32(7) — TBD (likely an `oIResource` parent header) |
| 1 | 313 | `oCVec3VertexLayer` "binormal" payload (vertex stream side-channel) |
| 2 | 312 | `oCVec3VertexLayer` "tangent" payload |
| 3 | 1573 | `oCGeometry` main body (bone vector + 1 submesh sub-object) |

Section 3 internal bracket map (BEGIN = `0xAABB1111`, END = `0xAABB2222`,
both written aligned by the engine's `+0x10`/`+0x18` stream helpers when
a subobject `+0xa0` write is in progress):

```
off    event       depth
----   ---------   -----
0      raw         —      u32(0), u32(0), u32(1), u8(0)   (oCGeometry self prelude, 13 B)
13     BEGIN       1      open oCMesh submesh subobject
  17     raw       —      u32(3), u8(1)                   (oCMesh prelude: TBD interpretation)
  22     BEGIN     2      open material subobject
    26     raw     —      u32(4), u32(0)
    34     BEGIN   3      (empty inner — schema TBD)
    38     raw     —      u32(5), u32(0)
    46     END     3
    50..132 ~80 B  —      material payload (oCMaterial + oCShaderParamSet)
  133    END       2      close material
  137    BEGIN     2      open oCMeshBuffer subobject
    141..1515 ~1374 B raw  vertex / index buffer (sample analysis below)
  1516   END       2      close oCMeshBuffer
1532   END         1      close oCMesh submesh
1532..1572 ~40 B —        oCGeometry trailing fields (AABB f32x6 + v>=2 trailing struct)
```

Annotated oCMeshBuffer payload (`offset 141..1515`, 1375 B inside section 3):

```
+0000: 06 00 00 00   u32  oIResource prelude  (= 6; flag semantics TBD)
+0004: 00            u8   unique_flag = 0  → default-buffer path
+0005: 07 00 00 00   u32  FUN_1404cb570 ver = 7  (current shipped)
+0009: 00            u8   comp_mode = 0   → uncompressed path
+000a: 18 00 00 00   u32  count = 24       (= *(stream + 0x10);
                                              for an oSTriangleMesh this
                                              field is "triangle/index count")
+000e: 0c 00 00 00   u32  byte_size = 12   (vtbl +0x40 blob length prefix)
                          ⚠ but count * 0x30 = 1152, not 12. The 12 here
                          does NOT match the asm-derived `count * 48` byte
                          size. Either:
                            (a) the asm-stride 0x30 is wrong for the
                                default-buffer-path's oSTriangleMesh;
                            (b) the vtbl +0x40 prefix is in elements not
                                bytes, with stride being implicit;
                            (c) there is an intermediate header u32 here
                                I'm misreading.
                          Marking as Stage 5c.i TBD pending more samples.
+0012..0x027  24 * u32   small ints 0,1,2,2,1,3,4,5,6,5,4,7,8,9,a,9,8,b,
                         c,d,e,d,c,f
                         → looks like 24 triangle-list indices (8 tris)
                         → if true, these are 24 * 4 = 96 bytes, but the
                           "byte_size = 12" doesn't match either reading.
+0072..       12 * (f32 x, f32 y, f32 z)  candidate vertex positions
                                          for the 8-triangle indexed mesh
... trailing tail with more f32s and the lstring annotation that closes
    FUN_1404cb570
+0530 (1328 bytes in): final two f32 = 0x3f800000 0x3f800000 (1.0, 1.0)
+1373..1374: 00 00  (likely the empty trailing lstring annotation
                    + the vtbl +0x60 NUL terminator behavior)
```

The exact stride and byte layout of the per-element vertex / triangle data
inside FUN_1404cb570's uncompressed-mode blob is the remaining unsolved
piece for closing the encoder. The decoder can still extract positions
(starting from the post-index region) and indices empirically — see
`docs/MOD_AUTHORING.md` once the helper is shipped.

The triangle-list indices `0,1,2,2,1,3,4,5,6,5,4,7,8,9,a,9,8,b,c,d,e,d,c,f`
form a sensible quad-strip pattern for the 6 faces of a cube
(each face = 2 triangles sharing an edge → 8 triangles × 3 indices = 24).

## Outstanding sub-class schemas (Stage 5b / 5c / 5d / 5e)

Done in this update:
- `oCMesh` (v1.2) schema — field-by-field above. (Stage 5b done)
- `oCMeshBuffer` (v1.4) outer envelope — `FUN_140650a80` fully decompiled
  and matched against sample. (Stage 5c done)
- `FUN_1404d1e30` unique-buffer reader — fully decompiled. (Stage 5c done)
- `FUN_1404cb570` named-instance reader — schema mapped per version stamp
  (1..7), including the three compression modes for v >= 3.
- `oCVec3VertexLayer` (v1.2) + `oIVertexLayer` (v1.0) — schemas added.
- `DAT_1412efa50` is the 4x4 identity matrix used as the engine's
  default-buffer signature.
- Stream-vtable convention table updated: `+0x40` blob writes are
  length-prefixed.

Still TBD:

- **`oIResource::Serialize`** — the universal parent prelude. Section 0 of
  our sample is `u32(2), u32(7), u32(7)` (12 B), and the meshbuffer
  payload starts with `u32(6)`. These look like a `(major, minor, hash)`
  triple but the writer code has not been decompiled yet. Decompile of
  `oIResource::Serialize` (vtable[3] of `oIResource`'s vftable, derivable
  from the same RTTI scan that resolved everything else).
- **Stage 5c.i — per-stream element layout inside `FUN_1404cb570`'s
  uncompressed mode** — the asm consistently computes `byte_size = count
  * 0x30`, but the sample shows what reads as `count = 24, byte_size =
  12` plus a stream of u32 indices afterward. Either the stride is
  context-dependent (oSTriangleMesh stores 12-byte stride after all,
  with 0x30 being a memory-side packing) or there's an intermediate
  header u32 we're misreading. Cross-validation with a larger sample
  (e.g. a 50 KB+ `oCGeometry` with multiple submeshes) should
  disambiguate.
- **`oCSkeleton` payload at `oCGeometry+0x80`** — schema is fully TBD.
  Only present for skinned meshes (skeleton-bound; this sample does not
  have one). Serialize VA = `0x1405b4c40`.
- **Trailing struct `{u32=0, u32=0x01010000, u32=0x01010000, u8=1}`** in
  oCGeometry — confirmed byte layout from sample (13 B total at end of
  section 3, after the AABB). Semantic of those constants is still TBD;
  they look like a "version-tag triple + flag" but their writer hasn't
  been decompiled yet.
- **Many-material edge case in `oCMesh`** — `FUN_1404fd1c0` chains an
  `oCMemoryBinaryStream` for the material write. Schema unknown.
- **Quantized-vertex paths' exact header bytes** — `FUN_1404c3440` (20 B
  per vertex) and `FUN_1404c3dc0` (18 B per vertex) emit non-trivial
  header structs (bboxes, octahedral packing tables). The Ghidra decompile
  was sketched in this work but not byte-validated against a quantized-mode
  sample. Any non-default-buffer mesh in the corpus will exercise these.
- **Semantic of top-level container sections 1+2** ("binormal", "tangent"
  side-channels) — the schema is now solved (they are `oCVec3VertexLayer`
  full Serialize outputs), but the question of WHY they appear as
  top-level sections instead of nested sub-objects of the meshbuffer is
  unresolved. Hypothesis: they are emitted by an `oCBinarySaver`
  pre-pass when the cooker decides this mesh needs auxiliary tangent
  space, with the container writer storing each in its own section so
  they can be streamed lazily (per-batch) at runtime. Decompile of the
  cooker call site for `PTR_s_tangent_1412ef988` / `PTR_s_binormal_1412ef978`
  would confirm.

Each remaining item requires:
1. RTTI scan (already have `python -m rsmm.dev.ghidra_resolve`).
2. Ghidra MCP decompile of vtable[3].
3. Field-by-field validation against a sample payload.

## Tools added in this work

- `src/rsmm/dev/cooked_manifest.py` — corpus scan → class manifest.
- `src/rsmm/dev/ghidra_resolve.py` — PE RTTI scan → vtable + Serialize VAs.
- `src/rsmm/engine/cooked.py` — container codec (parse + emit).
- `tests/test_cooked_roundtrip.py` — byte-stable round-trip across .yqz /
  .tpi / .zux (450 files sampled per run).

## Stage 5c.i — FUN_1404cb570 per-element stride (SOLVED)

Inner reader `FUN_1404d7d30` (called by ver<5 path `FUN_1404d62e0`) issues
12 consecutive stream `+0x78` (f32) reads per element: 8 inline + 4 via
`FUN_140126e40`. Per-element stride = **48 bytes (0x30)** = 12 f32:

| Offset | Field        | Type      |
|--------|--------------|-----------|
| 0x00   | position     | vec3 f32  |
| 0x0c   | normal       | vec3 f32  |
| 0x18   | uv0          | vec2 f32  |
| 0x20   | tangent      | vec3 f32  |
| 0x2c   | handedness   | f32       |

For ver>=5 uncompressed path, the same 0x30 stride is emitted as one
`vtbl+0x40` length-prefixed blob (`u32 byte_size = count*0x30`). Confirmed
against two real samples.

Earlier `count=24, byte_size=12` misread was a different path: ver>=7
`FUN_1404cb570` has two data sections — a u32 count at `*(this+0x10)`,
then dispatch on count to `FUN_1404d5b30` (u8 indices), `FUN_1404d5ce0`
(u16 indices), or a `count*0xc` vec3 blob.

## Stage 5d — oIResource prelude (PARTIAL)

`oIResource::Serialize` at `0x1400c2240` is a no-op stub (`return 1`); it
writes zero bytes. The leading section in every cooked file is actually
container-level metadata emitted by `oCBinarySaver`, not by oIResource.
Layout is 3–5 u32 fields whose count correlates with class-graph
complexity (more nested sub-objects ⇒ more fields). Per-field semantics
need a separate decompile of the cooker pre-pass (not the runtime
deserializer). Round-trip passthrough is already byte-stable via the
existing container codec, so no schema change is required to ship apply
pipeline — only inspection clarity.

## Stage 5e — oCSkeleton (SOLVED — decode side)

- Class UID: `0x1617`
- Current saved version: `1.1`
- `oCSkeleton::Serialize` at `0x1405b4c40` calls `FUN_1405cb350` to read
  the bone vector at `this+0x98`.
- Per-bone: **`oCBone::Serialize`** (UID `0x1614`, v1.1), 304 (0x130)
  bytes in-memory, dispatched as embedded sub-objects via stream slot
  `+0xa0`.
- Bone bind-pose translation: `+0x118` (3 floats) within bone struct.
- AABB at oCSkeleton `+0xa8..+0xbc` (6 floats xMin/yMin/zMin/xMax/yMax/zMax),
  version-gated for saved-version > 0.
- Each per-bone payload is its own BEGIN/END-bracketed sub-object — the
  existing container codec already frames it correctly without any
  changes.

Encode side (cooker quantization pipelines `FUN_1404c3440` mode-1 20B/vertex
and `FUN_1404c3dc0` mode-2 18B/vertex) remains TBD; static-mesh decode →
GLB lands in this phase, decode-only.

## Stage 7 — oCAnimation (v1.5) corpus validation

Round-trip verified on real `.yqz` cooked animations. Schema in
`src/rsmm/engine/cooked_schemas/animation.py` parses the full layout:

- `oIResource` 4-byte parent prelude (section 0)
- `oCAnimation` body (section 1):
  - `u32 res_prelude` (dispatch-wrapper preface; 0 in corpus)
  - lstring `name`
  - `u32 track_count` (or BEGIN typeof header path if first u32 = 0xAABB1111)
  - track_count × oCAnimationTrack sub-objects (BEGIN/END framed)
  - `f32 frame_step` (= 1 / frame_rate)
  - 6 × f32 AABB (via `FUN_1404d4a60`)
  - `FUN_1405b31d0` trailing struct at ver=5:
    - `u32 sub_ver` (= 5)
    - 5 × f32, 3 × f32 (via `FUN_140126ec0`), 4 × u8, u8 (v≥2), f32 (v≥3),
      u32 (v≥5) — typically the frame_rate (e.g. 30)

Per oCAnimationTrack (v1.7) — bone keyframe block:

- `u32 res_prelude` + `u32 leading_u32` + lstring bone_name
- 6 parallel streams alternating (times_u32_count + values_blob6) for
  Translation / Rotation / Scale axes
- Times: `u32 wire` per entry (holds a quantized u16 timestamp; remaps
  to seconds via `t * duration / 65535.0`)
- Values: `u32 size=6 + 6 bytes` per entry
  - T / S: 3 × signed i16, fixed-point `value = i16 / 1024` (NOT the
    per-anim AABB range — that earlier note was wrong). From the quantizer
    `FUN_1404ad910`: `q = round(clamp(value, -32, 31) * DAT_140fc6a74)`
    with `DAT_140fc6a74 = 1024.0`.
  - R: 48-bit smallest-three quaternion packing (from `FUN_1404ad540`)
- Trailing `f32 duration` (== animation duration in v1.7)

### Keyframe dequantization constants (SOLVED — decode side)

All read from `Ravenswatch.exe` .rdata and validated against the corpus:

- **Time**: `t = u16 / 65535 * duration` seconds (`DAT_140fc6ab0 = 65535`).
- **Translation / Scale**: `value = signed_i16 / 1024` (`DAT_140fc6a74 =
  1024`, clamp `[-32, 31]`). 1024 == 1.0. The earlier `/32767` guess
  collapsed every scale to ~0.03, which is why preview rigs rendered
  invisible.
- **Rotation** (smallest-three, `FUN_1404ad540`):
  - 48-bit field: `bits[46:45]` = largest-axis index, then three signed
    15-bit component fields `[44:30] [29:15] [14:0]` in axis order
    (largest axis omitted).
  - `component = signed15(field) / (sqrt(2) * 16383)`
    (`DAT_140fc6860 = 2.0`, `DAT_140fc6a98 = 16383`).
  - Omitted largest axis = `+sqrt(1 - a^2 - b^2 - c^2)` (encoder
    sign-flips so the largest is positive).
  - Validated **100% unit-norm across ~1.1M shipped keyframes**; identity
    blob `00 00 00 00 00 20` decodes to `(0, 0, 0, 1)`.

The decoder now emits a genuinely viewable `.glb`: one node per bone seeded
with its keyframe-0 rest pose, a shared octahedron "joint marker" mesh so
the bones are visible, and animation samplers/channels with the corrected
TRS curves.

Round-trip strategy: `decode()` produces a viewer-loadable `.glb` whose
JSON `extras.rsmm.raw_payload_b64` carries the original cooked section
bytes; `encode()` reads them back. Byte-stable provided the `.glb` was
authored by `decode()` (re-quantizing arbitrary glTF still requires the
forward packing path — decode is exact, re-cook goes via raw_payload_b64).

Corpus validation: **2240 / 2240** shipped `.yqz` animations round-trip
byte-stably (full coverage).

## Stage 8 — oCGlobalEntityValueSettings (v1.1) — SOLVED (decode + encode)

Schema in `src/rsmm/engine/cooked_schemas/global_values.py`. Decompile of
`FUN_1406de4e0` (Serialize) + byte validation against the full corpus.

Body wire order (after the 4-byte oIResource prelude section):

```
u32 res_prelude (= 0)
lstring name                 (the global value's key)
lstring string2              (a category tag — "Hero", "New Game Plus", ...)
SubObject<oCEntityValueUnion>  (BEGIN/END framed)
u8 flag_be, u8 flag_bc, u8 flag_bf   (3 trailing flag bytes)
```

`oCEntityValueUnion` (uid `0xd97f3e3`, v1.6):

```
u32 union_ver (= 3)
u32 type   0=float, 1=int, 2=bool, 3=vector3
u32 pad    (= 0)
value:  type0 f32 | type1 i32 | type2 u8 | type3 3×f32
```

All 204 shipped files share one container framing template (variant A,
hdr_a 0x10, flags 0x1, extra 1, type_tag 0x31, fixed 4-class table), so
`encode_container` rebuilds the container deterministically — the JSON is
fully self-describing (no opaque passthrough) and **byte-stable
round-trips 204 / 204**, with field edits flowing through to re-cooked
bytes. `scripts/extract_uncooked.py` mirrors these to
`data/uncooked/**/*.globalvalue.json`.

## Stage 11 — VFX / GameStream / CollisionMesh (asset-ref passthrough)

`src/rsmm/engine/cooked_schemas/asset_refs.py` — one generic
`AssetRefsHandler` for classes whose deep recursive schema isn't fully typed
but whose moddable payload is a set of embedded asset paths:

- `oCScheduledVfxSettings` (2368/2368) — the deferred recursive
  particle/`oIRsSettingsGroup` system; exposes the `Materials\\*.mat.ot`
  refs the effect uses.
- `oCGameStream` (390/390) — level object streams.
- `oCCollisionMesh` (16/16) — collision geometry.
- `oCMaterial` (2873/2873, v1.28) — exposes the albedo / MRA / normal
  texture refs (`Textures\\*.tga|.png`) + shader ref (`*.px.ot`) the
  material points at, so a material can be repointed / reskinned. The
  variable `oCShaderParamSet` (named param values — colors, floats) stays
  in the opaque literal stream; typing it later just moves those bytes into
  named fields. `material.py` no longer registers a stub — it defers here.

Decode splits the concatenated section bytes into verbatim literal chunks +
length-prefixed strings that look like asset refs (path separator or known
extension), exposing the refs as an editable `asset_refs` list. Encode
re-interleaves and re-splits by stored section lengths, mapping each ref's
length delta to the section that held it (`ref_offsets` / `ref_orig_lens`).
**Byte-stable round-trip; ref edits (e.g. repoint a VFX at a different
material) verified.** The recursive trees themselves stay in the verbatim
literals — same trade as the entity-settings component tree.

With this every root cooked class in the shipped corpus (all 25) has a
registered schema: full decode for textures / geometry / animation /
material / global-values / definitions, and byte-stable + editable-ref
coverage for the deep nested settings/stream classes.

## Stage 10 — oCEntitySettingsResource (byte-stable + editable path)

`src/rsmm/engine/cooked_schemas/entity_settings.py`. Serialize
`FUN_1406e5af0` is trivial (one `oCEntitySettings` sub-object at +0x98);
the real content is the nested component tree. The family is heterogeneous
(~62% "spawnable" entities carrying a 16-byte GUID + type string + a
`*.entity.ot` path; the rest component-only) and frequently splits
sub-objects across many container sections (2–689; strings can straddle a
boundary).

Handler strategy: parse the **concatenated** section bytes; locate the
spawnable block structurally via the `u32(16) + 16-byte guid + u32(1)`
anchor (works regardless of the variable type string), then expose
`entity_type` / `entity_path` as editable with the surrounding bytes kept
as `_pre_hex` / `_post_hex`. The container framing + section lengths are
stored in `_container`; on encode the concatenation is re-split by those
lengths with any length delta from an edited path absorbed into the section
containing the edit point. Component-only files (no anchor) are pure
byte-stable passthrough (`_pre_hex` = whole stream).

**4699 / 4700 byte-stable** (the one failure is a malformed container the
codec itself rejects — `class_count=205`); **2279** expose an editable
entity path. Path-length edits verified to re-split correctly. The deep
component-value tree (`oCEntityCpntValueSettings` / `oCEntityValueUnion`)
is left in the opaque region — same call as the deferred VFX tree.

## Stage 9 — oCDt*Definition data tables (framework + first class)

`src/rsmm/engine/cooked_schemas/definitions.py`. All `*Definition` leaf
classes derive from a shared `oCDtDefinition` base (`FUN_14030f880`, uid
`0x1768ce8e`) whose serialized body is two version-gated `u8` flags; each
leaf appends its own fields. The module is a registry of per-class
`_DefSpec`s (body decode/encode + container framing template), all served by
one generic `DefinitionHandler` that produces byte-stable editable JSON and
rebuilds the container deterministically. `scripts/extract_uncooked.py` has
a generic `*Definition.gen → <stem>.json` branch driven by the registry.

For classes whose container class table varies between files (an optional
sub-object class appears only when a nested vector is non-empty), the spec
sets `embed_container=True` and the framing + class table round-trips
through a `_container` block in the JSON instead of a fixed template.

Implemented:

- **oCDtEnemyTribeDefinition** (v1.1) — Serialize `FUN_14031b080`: base +
  empty `vector<TResourcePtr>` (`FUN_140337a10` @+0x2a0) + `u8` @+0x2b0 +
  `SubObject<oCCustomFlagList>` (u32 list_ver, u32 count, count × lstring =
  the tribe flag names). **25/25 byte-stable.**
- **oCDtEnemyDefinition** (v1.6) — Serialize `FUN_140319b30`: base +
  `TResourcePtr entity_ref` (settings-class + entity path) + `oCCustomFlagList`
  (combat/role flags) + `f32 spawn_weight` + `TResourcePtr tribe_ref` +
  trailing version-gated scalars / sub-object vectors preserved verbatim as
  an opaque `_tail_hex`. Exposes the high-value editable surface (which
  entity, tribe membership, combat tags, spawn weight) without fully typing
  every v1.0–1.6 migration field. `embed_container` (class table gains
  `oCDtEnemyDefinitionMaxOccurence` when a tail vector is non-empty).
  **81/81 byte-stable.**

A declarative field-DSL (`_dsl_spec`: ordered `tresptr` / `lstr` / `f32` /
`u32` / `u8` / `flaglist` fields, then opaque `_tail_hex`) covers the
simpler classes in one line each. `embed_container` stores every section
but the last verbatim (`lead_sections_hex`) so multi-section files
(sub-objects split into their own sections) round-trip:

- **oCDtDreamShardDefinition** (v1.0, 4/4) — entity_ref
- **oCDtEnemyCampDifficultyDefinition** (v1.1, 6/6) — field_a + 2 f32
- **oCDtEnemyCampTierDefinition** (v1.0, 4/4) — 2 f32 + field_a
- **oCDtIngredientDefinition** (v1.3, 6/6) — icon_ref + name
- **oCDtMapDefinition** (v1.3, 4/4) — level_ref + field_a + tribe_ref
- **MelodyDefinition** (v1.5, 12/12) — field_a + entity_ref

Remaining classes added the same way (leading editable refs typed via the
DSL, everything past the first unknown sub-reader preserved in `_tail_hex`):

- **oCDtTileDefinition** (v1.8, 237/237) — entity_ref
- **AchievementDefinition** (v1.3, 45/45) — guid (blob16) + field_a + 2 u8 + name
- **GameModifierDefinition** (v1.2, 22/22) — icon_ref + field_a + text_ref
- **oCDtHeroDefinition** (v1.27, 12/12) — base + opaque tail
- **oCDtRewardDefinition** (v1.2, 9/9) — base + opaque tail
- **ChallengeDefinition** (v1.1, 5/5) — field_a + text_ref
- **GameModeDefaultDefinition** (v1.1, 1/1) — field_a
- **VersionDefinition** (v1.6, 1/1) — base + opaque tail

**ALL 16 definition classes done: 474/474 byte-stable.** Classes whose body
past the typed prefix isn't field-decoded yet still round-trip exactly via
`_tail_hex`; deepening any of them later just means moving bytes out of the
tail into named DSL fields.

Adding a leaf class = decompile its Serialize (VAs resolved in
`data/cooked_class_map.json`), model the body against samples until 100%
byte-stable across that class's corpus, add a `_DefSpec`. Remaining leaf
classes + their Serialize VAs: oCDtEnemyDefinition `0x140319b30` (v1.6),
oCDtTileDefinition `0x140323d90` (v1.8), AchievementDefinition `0x1403115a0`
(v1.3), GameModifierDefinition `0x140325810` (v1.2), oCDtHeroDefinition
`0x1400c9b70` (v1.27), MelodyDefinition `0x1400c8750` (v1.5),
oCDtRewardDefinition `0x140323bc0` (v1.2, uses `FUN_14020d700` vector),
oCDtEnemyCampDifficultyDefinition `0x140311e90`, + the smaller ones.

### Still undecoded data classes (candidates for the same treatment)

| Class | count | version | notes |
|-------|------:|---------|-------|
| `oCEntitySettingsResource` | 4699 | 1.0 | GUID + entity path + nested `oCEntityCpntValueSettings` / `oCEntityCpntPicker` / `oCEntityValueUnion` component tree — deeply nested |
| `oCScheduledVfxSettings` | 2368 | 1.2 | VFX timelines |
| `oCGameStream` | 390 | 1.1 | level streams |
| `oCDtTileDefinition` | 237 | 1.8 | data-table definitions (`@dt@oe@@`) |
| `oCDtEnemyDefinition` | 81 | 1.6 | enemy stats |
| `AchievementDefinition` | 45 | 1.3 | |
| `oCDtEnemyTribeDefinition` | 25 | 1.1 | |
| `GameModifierDefinition` | 22 | 1.2 | |
| `oCDtHeroDefinition` | 12 | 1.27 | hero stats (many version-gated fields) |
| `MelodyDefinition` | 12 | 1.5 | |
| `oCCollisionMesh` | 11 | 1.3 | |
| `oCDtRewardDefinition` | 9 | 1.2 | |
| ... | | | + 8 more `*Definition` classes, ≤6 files each |

Each needs its own `Serialize` decompile; the wire format is untyped so
there is no generic shortcut. The shared `oCEntityValueUnion` codec above
is reusable for any of them.

## Stage 4 — oCTexture (v1.14) corpus validation

Round-tripped 4450 of 4451 `.tpi` files in shipped corpus through the
schema in `src/rsmm/engine/cooked_schemas/texture.py` (decode + re-emit
== original bytes).

Format distribution (engine_enum):
- `0x04` BC1: 1995 (~45%)
- `0x05` BC3: 1859 (~42%)
- `0x00` RGBA8 / UNKNOWN: 596 (~13%)

The single failure is `Grgtdzy_Fbuqqz_Ngum-Adllv.cjy.Qqpiwuq.tpi` —
a 3840x2160 BC1 texture using the `.cjy` cipher variant (not the
standard `.jzy`/`.iyg` extension). Its header claims blob_size =
4,147,200 B (= 3840*2160/2 = correct BC1 size for that resolution) but
the section payload is only 2,914,556 B. The actual pixel data is
truncated on disk — likely a streamed/external texture where the
final blob lives in a paired resource the loader fetches lazily. Out
of scope for the in-section schema. Decoder raises
`oCTexture payload truncated at blob read` which is correct behavior.

### DDS source encoder

`TextureHandler.encode_container(dds_bytes)` accepts a `.dds` source
file and produces a full cooked `.tpi` byte string ready to drop into
`<install>/DarkTalesResources/_Cooking/...`.

Path:
1. `dds.read()` parses DDS header (legacy DDS_HEADER + optional DDS_HEADER_DXT10).
2. Fourcc / DXGI value resolved to canonical `dds.FORMATS` entry.
3. Mip chain split: level 0 → `schema.pixels`; levels 1..N → `schema.mips`.
4. Engine pixel-format code looked up from `_DDS_NAME_TO_ENGINE` table.
5. Trailing flag fields (`array_size`, `mip_count_field`, `flag_ed`,
   `flag_ee`, `field_bc`, `flag_eb`, `local_40`, `f32_dc/e0/e4`) set to
   corpus-typical defaults.
6. `_encode_payload` re-emits the section payload.
7. `_build_cooked_container` wraps in variant-B container with the
   appropriate class table (adds `oCTextureMip` entry when mips present).

Cooked-format `array_size` is NOT a DDS array dimension — it's an
engine-internal flag with observed values 0/1/3. The DDS writer always
emits a 1-slice file; `dds_to_schema` re-applies the corpus-typical
flag values on the inverse path (`0` when mip-chain present, `1`
otherwise; rare `=3` case not synthesisable from a normal DDS).

cooked→DDS→cooked round-trip verified semantically (width, height,
format, full mip chain) on random samples. Whole-container byte-identity
not guaranteed because the corpus has both `(0,0)` and `(1,1)` value
patterns for plain 2D single-mip textures and the encoder picks one
canonical pair.

## Stage 5 + Stage 6 — oCGeometry (v1.2) round-trip + GLB preview

Schema lands in `src/rsmm/engine/cooked_schemas/geometry.py`. Cooked
→ GLB → cooked round-trip verified across the **full shipped corpus
(3001 / 3001 `.yqz` geometry files)**.

### Container layout

Variant-B cooked container with N sections:

```
sec[0]: aux header — 12 or 16 B
  u32 side_channel_count
  side_channel_count × u32 versions      (7 or 9 in v1.2 corpus)

sec[1..side_channel_count]: side-channel vertex layers
  u32 schema_version (7 or 9)
  lstring layer_name        ("binormal", "tangent", "tangentSign",
                             "uv2", ...)
  u8 comp_mode (v=9 only)   (= 0 = uncompressed)
  u32 vertex_count
  u32 byte_count
  byte_count bytes          (stride depends on class:
                             oCVec3VertexLayer = count * 12,
                             oCFloatVertexLayer = count * 4,
                             oCVec2VertexLayer = count * 8)

sec[N]: main oCGeometry body
  u32 oIResource prelude    (= 0)
  u32 bone_count
  bone_count × {
    16 × f32 matrix         (64 B row-major)
    lstring name_a
    lstring name_b
  }
  u32 submesh_count
  u8  has_skeleton
  submesh_count × SubObject<oCMesh>
  if has_skeleton: SubObject<oCSkeleton>
  6 × f32 AABB              (xMin yMin zMin xMax yMax zMax)
  (v >= 2) trailing struct  (= 0x01010000, 0x01010000, 1)
```

Submesh sub-objects are NOT walked via BEGIN/END markers — large
float vertex buffers contain false marker matches that defeat depth-
balanced scanning. Instead the AABB is located deterministically by
subtracting the fixed 33-byte tail (24 B AABB + 9 B trailing struct)
from the end of the main-body section.

### Round-trip strategy

`decode_cooked(cooked_bytes)` produces a viewer-loadable `.glb`
embedding:
- **One TRIANGLES mesh per submesh** with real POSITION / NORMAL /
  TEXCOORD_0 + index buffer, decoded by `_parse_meshbuffers` from each
  oCMeshBuffer default-buffer uncompressed stream (vertex stride 48 B —
  Stage 5c.i). Validated across the shipped corpus: every default-buffer
  mesh is `unique_flag==0` / `comp_mode==0`, decoded normals are unit
  length, indices in range. Loads correctly in trimesh / Blender.
- One transform-only node per bone (matrix preserved)
- One LINES mesh visualising the AABB
- Side-channel vec3 layers are emitted as a POINTS preview *only* when no
  decodable submesh exists (they are unit vectors — plotted as positions
  they form a "ball of dots", which was the earlier broken-looking output)
- `extras.rsmm.raw_payload_b64` — concatenated section bytes
- `extras.rsmm.cooked_b64` — full cooked-file bytes

`encode_container(glb_bytes)` extracts `cooked_b64` and returns the
original cooked bytes — byte-identical round-trip.

### Stage 6 hard limit

`encode()` deliberately refuses any `.glb` lacking the rsmm marker.
Cooking arbitrary glTF (a real authoring path) requires reversing the
quantization compressors `FUN_1404c3440` (mode-1 20 B/vertex) and
`FUN_1404c3dc0` (mode-2 18 B/vertex). Both remain unreversed; failing
fast prevents modders from shipping silently-broken meshes.

The current pipeline gives mod authors:
- byte-replace `.yqz` mods (already supported via container codec)
- DDS source texture mods (Stage 4)
- viewable mesh previews via Blender / glTF Viewer (Stage 5)

It does NOT yet give mod authors:
- editable-mesh mods sourced from a freshly-authored `.gltf`
- editable-skeleton mods sourced from glTF skin data
- re-encoded animations from glTF tracks
